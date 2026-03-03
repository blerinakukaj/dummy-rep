"""tests/test_outputs.py — Output artifact quality-validation tests.

Each test generates an artifact via its real generator (with a mocked LLM
client where the generator requires one), writes it to ``tmp_path``, reloads
it, and validates structural quality: required sections, schema conformance,
column completeness, finding-reference format, and recommendation validity.
"""

import csv
import io
import json
import re
from pathlib import Path

import pytest

from aipm.core.backlog_generator import BacklogGenerator
from aipm.core.decision_log_generator import DecisionLogGenerator
from aipm.core.experiment_generator import ExperimentPlanGenerator
from aipm.core.final_plan_generator import FinalPlanGenerator
from aipm.core.policy import PolicyPack
from aipm.core.prd_generator import PRDGenerator
from aipm.core.roadmap_generator import RoadmapGenerator
from aipm.schemas.config import RunConfig
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

# ---------------------------------------------------------------------------
# Mock LLM infrastructure
# ---------------------------------------------------------------------------


class _Completion:
    """Mimics an OpenAI chat completion response object."""

    def __init__(self, content: str) -> None:
        self.choices = [
            type(
                "Choice",
                (),
                {
                    "message": type("Msg", (), {"content": content})(),
                },
            )(),
        ]
        self.usage = type(
            "Usage",
            (),
            {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
        )()


def _make_openai_mock(content: str) -> object:
    """Return a minimal async-compatible OpenAI mock that always returns *content*."""

    class _Completions:
        async def create(self, **kwargs):
            return _Completion(content)

    class _Chat:
        completions = _Completions()

    class MockClient:
        chat = _Chat()

    MockClient.__module__ = "openai.mock"
    return MockClient()


def _make_sequenced_mock(*responses: str) -> object:
    """Return a mock that returns successive *responses* on each call."""
    call_state = {"idx": 0}

    class _Completions:
        async def create(self, **kwargs):
            idx = call_state["idx"]
            call_state["idx"] += 1
            text = responses[idx] if idx < len(responses) else responses[-1]
            return _Completion(text)

    class _Chat:
        completions = _Completions()

    class MockClient:
        chat = _Chat()

    MockClient.__module__ = "openai.mock"
    return MockClient()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run_config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        input_path="input_bundles/sample_bundle",
        output_dir=str(tmp_path / "output"),
        provider="openai",
        model="gpt-4o-mock",
    )


def _finding(
    fid: str,
    agent_id: str,
    ftype: str = "requirement",
    impact: str = "high",
    confidence: str = "validated",
    title: str = "Sample Finding",
    description: str = "Sample description for testing.",
    tags: list[str] | None = None,
    recommendations: list[str] | None = None,
    metadata: dict | None = None,
) -> Finding:
    return Finding(
        id=fid,
        agent_id=agent_id,
        type=ftype,
        title=title,
        description=description,
        impact=impact,
        confidence=confidence,
        evidence=[EvidenceItem(source_id="TICKET-001", source_type="ticket", excerpt="test excerpt")],
        tags=tags or [],
        recommendations=recommendations or ["Implement the feature"],
        assumptions=["Users will adopt the feature"],
        metadata=metadata or {},
    )


# ===================================================================
# Mock LLM responses (constants)
# ===================================================================

_PRD_SECTIONS_JSON = json.dumps(
    {
        "overview": (
            "SmartNotify addresses notification fatigue [customer-001] by using "
            "ML-based ranking to surface the most important notifications first."
        ),
        "goals": (
            "Increase daily notification engagement by 30% [metrics-001]. "
            "North Star metric: daily active engagement rate."
        ),
        "user_segments": "Mobile professionals receiving 100+ notifications/day [customer-001].",
        "in_scope": "1. ML ranking model [requirements-001]\n2. User preference panel [requirements-002]",
        "out_of_scope": "SMS integration and email channels are deferred to V2.",
        "functional_requirements": (
            "1. Rank notifications by predicted importance [requirements-001]\n"
            "2. Allow user override of ML ranking [requirements-002]"
        ),
        "non_functional_requirements": "Latency < 200 ms per ranking request. 99.9% uptime SLA [feasibility-001].",
        "acceptance_criteria": (
            "**GIVEN** a user with 50+ pending notifications "
            "**WHEN** they open the notification panel "
            "**THEN** notifications are sorted by ML-predicted priority within 200 ms [requirements-001]"
        ),
        "design_ux": "Swipe gestures to override ML ranking [customer-002].",
        "technical_considerations": "Requires ML inference service with < 100 ms P99 [feasibility-001].",
        "risks_mitigations": "**Risk:** Model bias [risk-001]. **Mitigation:** Regular retraining with diverse data.",
        "rollout_plan": "MVP: top 20% users. V1: full rollout. V2: personalisation layer [feasibility-002].",
        "open_questions": "Acceptable false-positive rate for ranking? [gap-001]",
        "evidence_references": (
            "- [customer-001]: Notification fatigue insight\n"
            "- [requirements-001]: ML ranking requirement\n"
            "- [metrics-001]: Daily engagement metric"
        ),
    }
)

_ROADMAP_JSON = json.dumps(
    {
        "product_name": "SmartNotify",
        "themes": [
            {
                "id": "theme-1",
                "title": "Core Ranking",
                "description": "ML-based notification ranking",
                "finding_ids": ["requirements-001"],
            },
            {
                "id": "theme-2",
                "title": "User Control",
                "description": "User preference and override controls",
                "finding_ids": ["requirements-002"],
            },
            {
                "id": "theme-3",
                "title": "Observability",
                "description": "Engagement analytics and monitoring",
                "finding_ids": ["metrics-001"],
            },
        ],
        "milestones": [
            {
                "id": "ms-1",
                "name": "MVP Ranking Engine",
                "phase": "mvp",
                "description": "Basic ML notification ranking for pilot users",
                "items": ["requirements-001"],
                "dependencies": [],
                "success_criteria": "P90 ranking latency < 200 ms for 10 k users",
            },
            {
                "id": "ms-2",
                "name": "V1 Full Rollout",
                "phase": "v1",
                "description": "Full feature rollout with user controls",
                "items": ["requirements-002"],
                "dependencies": ["ms-1"],
                "success_criteria": "30% increase in notification engagement",
            },
            {
                "id": "ms-3",
                "name": "V2 Personalisation",
                "phase": "v2",
                "description": "Advanced per-user personalisation and A/B testing",
                "items": [],
                "dependencies": ["ms-2"],
                "success_criteria": "User retention improves by 15%",
            },
        ],
        "sequencing": [
            {
                "from_milestone": "ms-1",
                "to_milestone": "ms-2",
                "reason": "V1 rollout requires MVP ranking to be stable",
            },
            {
                "from_milestone": "ms-2",
                "to_milestone": "ms-3",
                "reason": "Personalisation depends on full user data from V1",
            },
        ],
        "critical_path": ["ms-1", "ms-2", "ms-3"],
        "phases": {
            "mvp": {"goal": "Prove ML ranking improves engagement", "milestones": ["ms-1"]},
            "v1": {"goal": "Full product launch with user controls", "milestones": ["ms-2"]},
            "v2": {"goal": "Advanced personalisation at scale", "milestones": ["ms-3"]},
        },
    }
)

_EXPERIMENT_SECTIONS_JSON = json.dumps(
    {
        "hypothesis": (
            "If we implement ML-based notification ranking, then daily active "
            "notification engagement will increase by 25% because [metrics-001] "
            "shows users engage more with relevance-ranked content. Supporting: "
            "[customer-001] confirms users mute irrelevant notifications."
        ),
        "success_metrics": (
            "| Metric | Threshold | Window |\n"
            "|--------|-----------|--------|\n"
            "| Daily engagement rate | +25% vs control | 14 days |\n"
            "| Time-to-dismiss (top-ranked) | -30% | 14 days |"
        ),
        "guardrail_metrics": (
            "| Guardrail Metric | Max Acceptable Degradation |\n"
            "|------------------|----------------------------|\n"
            "| App crash rate | +0.1% |\n"
            "| Notification opt-out rate | +5% |\n"
            "| P99 ranking latency | 300 ms |"
        ),
        "experiment_design": (
            "Control: existing chronological sort (50%). Treatment: ML ranking (50%). "
            "Targeting: all users with > 20 notifications/day. Randomisation unit: user_id."
        ),
        "sample_size_duration": (
            "Sample size per arm: 50,000 users. MDE: 5%. Power: 80%. "
            "Significance: alpha = 0.05. Estimated duration: 14 calendar days "
            "given daily active volume of 500,000."
        ),
        "segmentation": "New vs returning users; mobile vs desktop; power users (> 50 notifs/day) vs casual.",
        "rollback_criteria": (
            "Terminate immediately if crash rate > +0.5%, opt-out rate > +10%, or P99 latency > 500 ms for > 1 hour."
        ),
        "data_collection": (
            "Events: notification_ranked, notification_tapped, notification_dismissed. "
            "Properties: rank_position, model_version, user_segment."
        ),
        "analysis_plan": (
            "Two-sample t-test with Bonferroni correction. Interim look at day 7. "
            "PM + Data Science lead sign-off required."
        ),
    }
)

_EXEC_SUMMARY_TEXT = (
    "SmartNotify addresses notification fatigue [customer-001]. "
    "Analysis shows a strong market opportunity with ML ranking [requirements-001]. "
    "Recommendation: proceed with development, prioritising privacy compliance."
)

_REASONING_TEXT = (
    "The proceed decision is driven by validated customer evidence [customer-001] "
    "and clear technical feasibility [feasibility-001]. Risk [risk-001] is mitigated "
    "through privacy-preserving ML techniques."
)


# ===================================================================
# test_prd_structure
# ===================================================================


@pytest.mark.asyncio
async def test_prd_structure(tmp_path: Path) -> None:
    """PRD contains required sections, finding references, and GIVEN/WHEN/THEN criteria."""
    cfg = _run_config(tmp_path)
    from aipm.schemas.context import ContextPacket

    context = ContextPacket(
        run_id=cfg.run_id,
        product_name="SmartNotify",
        product_description="Intelligent notification prioritisation using ML.",
        tickets=[],
        documents=[],
        risk_hotspots=[],
        raw_input_type="bundle",
    )
    findings = [
        _finding("customer-001", "customer", ftype="insight", title="Notification Fatigue"),
        _finding("requirements-001", "requirements", title="ML Ranking"),
        _finding("requirements-002", "requirements", title="User Preference Panel"),
        _finding("metrics-001", "metrics", ftype="metric", title="Daily Engagement Rate", tags=["north-star"]),
        _finding("risk-001", "risk", ftype="risk", title="Model Bias Risk"),
        _finding("feasibility-001", "feasibility", ftype="dependency", title="ML Inference Service"),
    ]

    client = _make_openai_mock(_PRD_SECTIONS_JSON)
    generator = PRDGenerator(
        llm_client=client,
        context_packet=context,
        all_findings=findings,
        policy_pack=PolicyPack(),
        run_config=cfg,
    )

    prd_content = await generator.generate(recommendation="proceed")

    # Write and reload from disk
    prd_path = tmp_path / "prd.md"
    prd_path.write_text(prd_content, encoding="utf-8")
    loaded = prd_path.read_text(encoding="utf-8")

    # 1. Required section headers
    required_sections = [
        "## Overview",
        "## Goals",
        "## Scope",
        "## Requirements",
        "## Acceptance Criteria",
        "## Risks",
        "## Rollout",
    ]
    for section in required_sections:
        assert section in loaded, f"Missing required section '{section}' in prd.md"

    # 2. Finding references in [finding-id] format  (e.g. [customer-001])
    finding_refs = re.findall(r"\[\w+-\d+\]", loaded)
    assert len(finding_refs) > 0, "prd.md must contain at least one finding reference in [id-NNN] format"

    # 3. Acceptance criteria use GIVEN / WHEN / THEN
    ac_match = re.search(r"## Acceptance Criteria\s*\n(.*?)(?=\n## |\Z)", loaded, re.DOTALL)
    assert ac_match is not None, "Could not locate Acceptance Criteria section body"
    ac_text = ac_match.group(1)
    assert "GIVEN" in ac_text, "Acceptance criteria must use GIVEN keyword"
    assert "WHEN" in ac_text, "Acceptance criteria must use WHEN keyword"
    assert "THEN" in ac_text, "Acceptance criteria must use THEN keyword"


# ===================================================================
# test_roadmap_schema
# ===================================================================


@pytest.mark.asyncio
async def test_roadmap_schema(tmp_path: Path) -> None:
    """Roadmap JSON has themes/milestones/sequencing, valid deps, and correct phase order."""
    cfg = _run_config(tmp_path)
    findings = [
        _finding("requirements-001", "requirements", title="ML Ranking", metadata={"phase": "MVP", "priority": "P0"}),
        _finding("requirements-002", "requirements", title="User Controls", metadata={"phase": "V1", "priority": "P1"}),
        _finding(
            "feasibility-001",
            "feasibility",
            ftype="dependency",
            title="ML Service",
            metadata={"phase": "MVP", "complexity": "complex"},
        ),
    ]

    client = _make_openai_mock(_ROADMAP_JSON)
    generator = RoadmapGenerator(llm_client=client, all_findings=findings, run_config=cfg)
    roadmap = await generator.generate()

    # Write and reload
    roadmap_path = tmp_path / "roadmap.json"
    generator.save(roadmap, str(roadmap_path))
    loaded = json.loads(roadmap_path.read_text(encoding="utf-8"))

    # 1. Required top-level keys
    for key in ("themes", "milestones", "sequencing"):
        assert key in loaded, f"roadmap.json must have '{key}' key"
        assert isinstance(loaded[key], list), f"'{key}' must be a list"

    assert len(loaded["themes"]) > 0, "roadmap.json must have at least one theme"
    assert len(loaded["milestones"]) > 0, "roadmap.json must have at least one milestone"

    # 2. All milestone dependencies reference valid milestone IDs
    valid_ids = {m["id"] for m in loaded["milestones"]}
    for ms in loaded["milestones"]:
        for dep in ms.get("dependencies", []):
            assert dep in valid_ids, f"Milestone '{ms['id']}' dependency '{dep}' is not a valid milestone ID"

    # 3. Phases in correct order (MVP before V1 before V2)
    phase_rank = {"mvp": 0, "v1": 1, "v2": 2}
    ms_phase = {m["id"]: m.get("phase", "").lower() for m in loaded["milestones"]}

    for seq in loaded.get("sequencing", []):
        from_phase = ms_phase.get(seq["from_milestone"], "")
        to_phase = ms_phase.get(seq["to_milestone"], "")
        if from_phase in phase_rank and to_phase in phase_rank:
            assert phase_rank[from_phase] <= phase_rank[to_phase], (
                f"Sequencing violation: {from_phase} -> {to_phase} is out of phase order"
            )


# ===================================================================
# test_backlog_csv
# ===================================================================


def test_backlog_csv(tmp_path: Path) -> None:
    """Backlog CSV has correct header, valid priorities/phases, and non-empty required fields."""
    requirements = [
        _finding(
            "requirements-001",
            "requirements",
            title="ML Notification Ranking",
            description="Rank notifications using ML to reduce fatigue.",
            tags=["ml", "ranking"],
            metadata={
                "epic_id": "EPIC-1",
                "epic_title": "Core Ranking",
                "story_id": "STORY-1",
                "story_title": "Basic ML Ranking",
                "priority": "P0",
                "complexity": "complex",
                "phase": "MVP",
                "acceptance_criteria": ["GIVEN a notification list WHEN ranked THEN sorted by priority"],
            },
        ),
        _finding(
            "requirements-002",
            "requirements",
            title="User Preference Controls",
            description="Allow users to override ranking preferences.",
            tags=["ux", "preferences"],
            metadata={
                "epic_id": "EPIC-1",
                "epic_title": "Core Ranking",
                "story_id": "STORY-2",
                "story_title": "Preference Settings",
                "priority": "P1",
                "complexity": "medium",
                "phase": "V1",
                "acceptance_criteria": ["GIVEN a user WHEN they update preferences THEN ranking updates"],
            },
        ),
        _finding(
            "requirements-003",
            "requirements",
            title="Analytics Dashboard",
            description="Show notification engagement metrics.",
            tags=["analytics"],
            metadata={
                "epic_id": "EPIC-2",
                "epic_title": "Analytics",
                "story_id": "STORY-3",
                "story_title": "Engagement Dashboard",
                "priority": "P2",
                "complexity": "medium",
                "phase": "V2",
            },
        ),
    ]
    feasibility = [
        _finding(
            "feasibility-001",
            "feasibility",
            ftype="dependency",
            title="ML Service Dependency",
            description="Requires ML inference.",
            metadata={"story_id": "STORY-1", "complexity": "complex", "phase": "MVP"},
        ),
    ]

    generator = BacklogGenerator()
    csv_content = generator.generate(requirements, feasibility)

    # Write and reload
    csv_path = tmp_path / "backlog.csv"
    generator.save_csv(csv_content, str(csv_path))
    loaded_text = csv_path.read_text(encoding="utf-8")

    reader = csv.DictReader(io.StringIO(loaded_text))
    rows = list(reader)

    # 1. Header matches expected columns
    expected_columns = [
        "epic_id",
        "epic_title",
        "story_id",
        "story_title",
        "description",
        "acceptance_criteria",
        "priority",
        "complexity",
        "phase",
        "labels",
        "dependencies",
    ]
    assert list(reader.fieldnames) == expected_columns, (
        f"Header mismatch: got {reader.fieldnames}, expected {expected_columns}"
    )

    # 2. Non-empty required fields in every row
    required_fields = ["epic_id", "story_id", "story_title", "priority", "phase"]
    for i, row in enumerate(rows):
        for field in required_fields:
            assert row.get(field, "").strip(), f"Row {i} has empty required field '{field}': {row}"

    # 3. Priorities are valid (P0-P3)
    valid_priorities = {"P0", "P1", "P2", "P3"}
    for i, row in enumerate(rows):
        assert row["priority"] in valid_priorities, f"Row {i} has invalid priority '{row['priority']}'"

    # 4. Phases are valid (MVP / V1 / V2)
    valid_phases = {"MVP", "V1", "V2"}
    for i, row in enumerate(rows):
        assert row["phase"] in valid_phases, f"Row {i} has invalid phase '{row['phase']}'"


# ===================================================================
# test_decision_log_completeness
# ===================================================================


def test_decision_log_completeness(tmp_path: Path) -> None:
    """Decision log has table entries with rationale and finding-ID evidence references."""
    dedup_decisions = [
        {
            "kept_id": "customer-001",
            "merged_ids": ["competitive-001"],
            "reason": "Customer insight has higher confidence and direct user evidence",
            "finding_title": "Notification Fatigue Insight",
            "confidence": "validated",
            "kept_rationale": "Validated customer finding supersedes directional competitive insight",
        },
    ]

    conflict_resolutions = [
        {
            "id": "conflict-001",
            "finding_a": "requirements-001",
            "finding_b": "risk-001",
            "what_conflicted": "Data collection requirement conflicts with privacy risk",
            "resolution": "Implement privacy-preserving ML with differential privacy",
            "resolution_rule": "block_on_critical_privacy",
            "confidence": "directional",
            "alternatives": "Remove data collection; use anonymised data only",
            "tradeoffs": "Reduced model accuracy in exchange for privacy compliance",
        },
    ]

    risk_gate_results = {
        "passed": True,
        "blockers": [],
        "warnings": ["Legal review required for PII — Notification Data Collection [risk-001]"],
        "label": "Primary Risk Gate",
    }

    generator = DecisionLogGenerator(
        dedup_decisions=dedup_decisions,
        conflict_resolutions=conflict_resolutions,
        risk_gate_results=risk_gate_results,
        policy_pack=PolicyPack(),
        product_name="SmartNotify",
        run_id="test-run-001",
    )

    content = generator.generate()

    # Write and reload
    log_path = tmp_path / "decision_log.md"
    generator.save(content, str(log_path))
    loaded = log_path.read_text(encoding="utf-8")

    # 1. Table has numbered entries (not the empty-placeholder row)
    table_entries = re.findall(r"^\|\s*\d+\s*\|", loaded, re.MULTILINE)
    assert len(table_entries) > 0, "Decision log must have at least one numbered table entry"

    # 2. Entries contain rationale text
    assert "Customer insight has higher confidence" in loaded, "Dedup decision rationale must appear in the log"
    assert "privacy-preserving ML" in loaded, "Conflict resolution rationale must appear in the log"

    # 3. Evidence references — finding IDs appear in the document
    finding_id_re = re.compile(r"\b(?:customer|competitive|requirements|risk|feasibility|metrics)-\d+\b")
    evidence_refs = finding_id_re.findall(loaded)
    assert len(evidence_refs) >= 2, "Decision log must reference finding IDs as evidence (expected >= 2)"


# ===================================================================
# test_experiment_plan_content
# ===================================================================


@pytest.mark.asyncio
async def test_experiment_plan_content(tmp_path: Path) -> None:
    """Experiment plan has specific hypothesis, guardrail metrics, and sample size/duration."""
    cfg = _run_config(tmp_path)

    metrics_findings = [
        _finding(
            "metrics-001",
            "metrics",
            ftype="metric",
            title="Daily Engagement Rate",
            description="North Star: daily active notification engagement rate.",
            tags=["north-star"],
        ),
    ]
    risk_findings = [
        _finding(
            "risk-001",
            "risk",
            ftype="risk",
            title="Model Bias Risk",
            description="ML ranking model may exhibit demographic bias.",
            impact="high",
        ),
    ]

    client = _make_openai_mock(_EXPERIMENT_SECTIONS_JSON)
    generator = ExperimentPlanGenerator(
        llm_client=client,
        metrics_findings=metrics_findings,
        risk_findings=risk_findings,
        policy_pack=PolicyPack(),
        run_config=cfg,
        product_name="SmartNotify",
    )

    content = await generator.generate()

    # Write and reload
    exp_path = tmp_path / "experiment_plan.md"
    exp_path.write_text(content, encoding="utf-8")
    loaded = exp_path.read_text(encoding="utf-8")

    # 1. Hypothesis section exists and is specific
    assert "## Hypothesis" in loaded, "Experiment plan must have a Hypothesis section"
    hyp_match = re.search(r"## Hypothesis\s*\n(.*?)(?=\n## |\Z)", loaded, re.DOTALL)
    assert hyp_match is not None
    hyp_text = hyp_match.group(1).strip()
    assert len(hyp_text) > 50, "Hypothesis must be specific (not empty or trivially short)"
    assert re.search(r"[Ii]f\b", hyp_text), "Hypothesis should state an 'If … then' prediction"

    # 2. Guardrail metrics are listed
    assert "Guardrail" in loaded, "Experiment plan must include guardrail metrics"
    guardrail_match = re.search(r"Guardrail Metric", loaded)
    assert guardrail_match is not None, "Guardrail metrics table must be present"

    # 3. Sample size / duration are specified
    assert "## Sample Size" in loaded, "Experiment plan must have a Sample Size & Duration section"
    sample_match = re.search(r"## Sample Size.*?\n(.*?)(?=\n## |\Z)", loaded, re.DOTALL)
    assert sample_match is not None
    sample_text = sample_match.group(1).strip()
    assert re.search(r"\d+", sample_text), "Sample Size section must contain numeric values"


# ===================================================================
# test_final_plan_recommendation
# ===================================================================


@pytest.mark.asyncio
async def test_final_plan_recommendation(tmp_path: Path) -> None:
    """Final plan recommendation is one of 4 valid types; reasoning references findings."""
    cfg = _run_config(tmp_path)

    all_findings = [
        _finding(
            "customer-001",
            "customer",
            ftype="insight",
            impact="high",
            confidence="validated",
            title="Notification Fatigue",
            description="Users mute notifications due to overload.",
            recommendations=["Implement ML ranking"],
        ),
        _finding(
            "requirements-001",
            "requirements",
            impact="high",
            confidence="validated",
            title="ML Ranking Feature",
            description="Rank notifications by predicted importance.",
            recommendations=["Build ML ranking engine"],
        ),
        _finding(
            "feasibility-001",
            "feasibility",
            ftype="dependency",
            impact="medium",
            confidence="directional",
            title="ML Service Dependency",
            description="Requires ML inference service.",
            metadata={"phase": "MVP", "complexity": "complex"},
        ),
    ]

    # Minimal lead_pm AgentOutput with a top-priorities finding
    lead_pm_output = AgentOutput(
        agent_id="lead_pm",
        agent_name="Lead PM Agent",
        run_id=cfg.run_id,
        findings=[
            Finding(
                id="lead_pm-002",
                agent_id="lead_pm",
                type="recommendation",
                title="Top Priorities",
                description="Ranked finding priorities.",
                impact="high",
                confidence="validated",
                evidence=[EvidenceItem(source_id="customer-001", source_type="doc", excerpt="ranked")],
                tags=[],
                metadata={
                    "top_priorities": [
                        {"finding_id": "customer-001", "score": 0.9},
                        {"finding_id": "requirements-001", "score": 0.85},
                    ],
                },
            ),
        ],
        summary="Lead PM synthesis complete.",
        errors=[],
    )

    # Mock returns exec-summary first, reasoning second
    client = _make_sequenced_mock(_EXEC_SUMMARY_TEXT, _REASONING_TEXT)

    generator = FinalPlanGenerator(
        llm_client=client,
        lead_pm_output=lead_pm_output,
        all_findings=all_findings,
        policy_pack=PolicyPack(),
        run_config=cfg,
        product_name="SmartNotify",
    )

    plan = await generator.generate()

    # Write and reload
    plan_path = tmp_path / "final_plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(plan_path.read_text(encoding="utf-8"))

    # 1. Recommendation is one of the 4 valid decision types
    valid_decisions = {"proceed", "proceed_with_mitigations", "validate_first", "do_not_pursue"}
    recommendation = loaded["recommendation"]
    assert recommendation["decision"] in valid_decisions, (
        f"Recommendation '{recommendation['decision']}' is not one of {valid_decisions}"
    )

    # 2. Reasoning references specific finding IDs
    reasoning = recommendation.get("reasoning", "")
    assert len(reasoning) > 0, "Recommendation must include non-empty reasoning"
    finding_refs = re.findall(r"\[\w+-\d+\]", reasoning)
    assert len(finding_refs) > 0, "Recommendation reasoning must reference specific findings in [id-NNN] format"
