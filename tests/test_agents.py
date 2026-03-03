"""Individual agent tests with error handling scenarios.

Tests each AIPM agent in isolation using a mock OpenAI client.
Covers: valid output, evidence linking, empty context, and LLM error handling.
Special tests: risk gate policy enforcement, Lead PM dedup, and conflict resolution.
"""

import json
from pathlib import Path

import pytest

from aipm.agents.competitive_agent import CompetitiveAgent
from aipm.agents.customer_agent import CustomerInsightsAgent
from aipm.agents.feasibility_agent import FeasibilityAgent
from aipm.agents.lead_pm_agent import LeadPMAgent
from aipm.agents.metrics_agent import MetricsAgent
from aipm.agents.requirements_agent import RequirementsAgent
from aipm.agents.risk_agent import RiskAgent
from aipm.core.policy import PolicyPack, RiskGatingPolicy
from aipm.core.resilience import AgentError
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket, DocumentItem, RiskHotspot, TicketItem
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding


# ── Mock OpenAI client infrastructure ──────────────────────────────────────────

class _Usage:
    prompt_tokens = 50
    completion_tokens = 100
    total_tokens = 150


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Completion:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]
        self.usage = _Usage()


def _make_openai_mock(content):
    """Return a mock OpenAI client whose chat.completions.create() returns *content* or raises it."""

    class _Completions:
        def create(self, **kwargs):
            if isinstance(content, Exception):
                raise content
            return _Completion(content)

    class _Chat:
        completions = _Completions()

    class MockClient:
        chat = _Chat()

    MockClient.__module__ = "openai.mock"
    return MockClient()


def _make_routing_mock(response_map: dict[str, str], default: str | None = None):
    """Return a mock client that routes calls based on keywords in message content.

    Args:
        response_map: {keyword: response_json} — first matching keyword wins.
        default: Fallback response when no keyword matches.
    """
    _default = default or json.dumps({"findings": [], "summary": "fallback"})

    class _Completions:
        def create(self, **kwargs):
            messages = kwargs.get("messages", [])
            combined = " ".join(m.get("content", "") for m in messages).lower()
            for keyword, response in response_map.items():
                if keyword.lower() in combined:
                    return _Completion(response)
            return _Completion(_default)

    class _Chat:
        completions = _Completions()

    class MockRoutingClient:
        chat = _Chat()

    MockRoutingClient.__module__ = "openai.mock"
    return MockRoutingClient()


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _write_findings_file(run_config: RunConfig, agent_id: str, data: dict) -> None:
    """Pre-write a serialized AgentOutput JSON file for an upstream agent."""
    findings_dir = Path(run_config.output_dir) / run_config.run_id / "findings"
    findings_dir.mkdir(parents=True, exist_ok=True)
    (findings_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _upstream_output(agent_id: str, run_id: str, source_id: str = "TICKET-001") -> dict:
    """Return a minimal serialized AgentOutput dict for upstream file seeding."""
    return {
        "agent_id": agent_id,
        "agent_name": f"{agent_id.title()} Agent",
        "run_id": run_id,
        "findings": [
            {
                "id": f"{agent_id}-001",
                "agent_id": agent_id,
                "type": "insight",
                "title": f"Mock {agent_id} upstream finding",
                "description": "Upstream finding seeded for testing.",
                "impact": "medium",
                "confidence": "directional",
                "evidence": [
                    {"source_id": source_id, "source_type": "ticket", "excerpt": "upstream test excerpt"}
                ],
                "tags": ["mock"],
                "metadata": {},
            }
        ],
        "summary": f"Mock {agent_id} summary for upstream seeding.",
        "errors": [],
    }


# ── Shared fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def run_config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        input_path="input_bundles/sample_bundle",
        output_dir=str(tmp_path / "output"),
        provider="openai",
        model="gpt-4o-mock",
    )


@pytest.fixture
def default_policy() -> PolicyPack:
    return PolicyPack()


@pytest.fixture
def strict_policy() -> PolicyPack:
    """Policy that blocks all critical privacy/security risks with zero tolerance."""
    return PolicyPack(
        risk_gating=RiskGatingPolicy(
            block_on_critical_privacy=True,
            block_on_critical_security=True,
            require_legal_review_for_pii=True,
            max_unmitigated_high_risks=0,
        )
    )


@pytest.fixture
def sample_context(run_config: RunConfig) -> ContextPacket:
    """Rich context packet with tickets, documents, and risk hotspots."""
    return ContextPacket(
        run_id=run_config.run_id,
        product_name="SmartNotify",
        product_description="Intelligent notification prioritization system using ML.",
        tickets=[
            TicketItem(
                id="TICKET-001",
                title="Notification fatigue",
                description="Users receive too many notifications and mute them entirely.",
                status="open",
                priority="high",
                labels=["ux", "engagement"],
                source="jira",
            ),
            TicketItem(
                id="TICKET-002",
                title="ML prioritization feature",
                description="Use ML model to rank notifications by predicted importance.",
                status="open",
                priority="high",
                labels=["ml", "feature"],
                source="jira",
            ),
        ],
        documents=[
            DocumentItem(
                id="DOC-001",
                title="competitor_analysis.md",
                content="Competitor X uses smart filtering achieving a 40% lower mute rate.",
                doc_type="competitor_brief",
            ),
            DocumentItem(
                id="DOC-002",
                title="metrics_dashboard.md",
                content="DAU: 10k. Notification mute rate: 40%. Weekly retention: 65%.",
                doc_type="metrics_snapshot",
            ),
            DocumentItem(
                id="DOC-003",
                title="customer_interviews.md",
                content="Users want fewer, more relevant notifications. Power users mute to cope.",
                doc_type="note",
            ),
        ],
        risk_hotspots=[
            RiskHotspot(
                category="privacy",
                description="ML model may process user behavioral data constituting PII.",
                severity="high",
                source_ids=["TICKET-002"],
            )
        ],
        raw_input_type="bundle",
    )


@pytest.fixture
def minimal_context(run_config: RunConfig) -> ContextPacket:
    """Minimal context with almost no data to trigger empty-context handling in agents."""
    return ContextPacket(
        run_id=run_config.run_id,
        product_name="MinimalProduct",
        product_description="Minimal product description.",
        tickets=[],
        documents=[],
        risk_hotspots=[],
        raw_input_type="bundle",
    )


# ── Canned mock LLM responses ────────────────────────────────────────────────────

_CUSTOMER_RESPONSE = json.dumps({
    "findings": [
        {
            "id": "customer-001",
            "agent_id": "customer",
            "type": "insight",
            "title": "Notification Fatigue Is the Top Pain Point",
            "description": "Users receive too many notifications, leading to mute behavior and disengagement.",
            "impact": "high",
            "confidence": "validated",
            "assumptions": ["Muted users are more likely to churn"],
            "evidence": [
                {"source_id": "TICKET-001", "source_type": "ticket",
                 "excerpt": "Users receive too many notifications and mute them."}
            ],
            "recommendations": ["Implement ML-based notification priority filtering"],
            "tags": ["ux", "engagement"],
            "metadata": {"segment": "power_users"},
        },
        {
            "id": "customer-002",
            "agent_id": "customer",
            "type": "gap",
            "title": "Missing User Segmentation Data",
            "description": "No data distinguishes casual vs power user notification preferences.",
            "impact": "medium",
            "confidence": "speculative",
            "evidence": [
                {"source_id": "DOC-003", "source_type": "doc",
                 "excerpt": "Users want fewer, more relevant notifications."}
            ],
            "tags": ["research", "segmentation"],
            "metadata": {},
        },
    ],
    "summary": "Identified 1 customer insight and 1 research gap.",
})

_COMPETITIVE_RESPONSE = json.dumps({
    "findings": [
        {
            "id": "competitive-001",
            "agent_id": "competitive",
            "type": "insight",
            "title": "Competitor X Smart Filtering Advantage",
            "description": "Competitor X achieves a 40% lower mute rate via smart notification filtering.",
            "impact": "high",
            "confidence": "directional",
            "evidence": [
                {"source_id": "DOC-001", "source_type": "doc",
                 "excerpt": "Competitor X uses smart filtering achieving a 40% lower mute rate."}
            ],
            "tags": ["competitive", "market"],
            "metadata": {"urgency": "high"},
        }
    ],
    "summary": "Identified 1 key competitive gap against Competitor X.",
})

_METRICS_RESPONSE = json.dumps({
    "findings": [
        {
            "id": "metrics-001",
            "agent_id": "metrics",
            "type": "metric",
            "title": "Notification Engagement Rate as North Star",
            "description": "Percentage of delivered notifications acted on captures SmartNotify's core value.",
            "impact": "high",
            "confidence": "directional",
            "evidence": [
                {"source_id": "DOC-002", "source_type": "metric",
                 "excerpt": "DAU: 10k. Notification mute rate: 40%."}
            ],
            "tags": ["north_star", "analytics"],
            "metadata": {
                "metric_role": "north_star",
                "definition": "% of delivered notifications acted on",
                "measurement": "actions / delivered * 100",
            },
        }
    ],
    "summary": "Defined North Star metric: Notification Engagement Rate.",
})

_REQUIREMENTS_RESPONSE = json.dumps({
    "findings": [
        {
            "id": "requirements-001",
            "agent_id": "requirements",
            "type": "requirement",
            "title": "ML Notification Priority Filter",
            "description": "The system shall rank incoming notifications using an ML model priority score.",
            "impact": "high",
            "confidence": "validated",
            "evidence": [
                {"source_id": "TICKET-001", "source_type": "ticket",
                 "excerpt": "Users receive too many notifications and mute them."}
            ],
            "tags": ["functional", "ml"],
            "metadata": {
                "requirement_type": "functional",
                "acceptance_criteria": (
                    "GIVEN a notification arrives "
                    "WHEN ML priority score < 0.3 "
                    "THEN the notification is suppressed"
                ),
                "priority": "P0",
                "complexity": "M",
                "phase": "MVP",
                "epic_id": "EPIC-001",
                "story_id": "STORY-001",
            },
        }
    ],
    "summary": "Defined 1 functional requirement with acceptance criteria.",
})

_FEASIBILITY_RESPONSE = json.dumps({
    "findings": [
        {
            "id": "feasibility-001",
            "agent_id": "feasibility",
            "type": "dependency",
            "title": "ML Model Serving Infrastructure",
            "description": "Notification prioritization requires a trained ML model serving endpoint.",
            "impact": "high",
            "confidence": "directional",
            "evidence": [
                {"source_id": "TICKET-002", "source_type": "ticket",
                 "excerpt": "Use ML model to rank notifications by predicted importance."}
            ],
            "tags": ["technical", "dependency", "ml"],
            "metadata": {
                "complexity": "complex",
                "phase": "MVP",
                "dependencies": ["ml-serving-infra"],
                "blocking": True,
            },
        }
    ],
    "summary": "Identified 1 blocking ML infrastructure dependency.",
})

_RISK_RESPONSE = json.dumps({
    "findings": [
        {
            "id": "risk-001",
            "agent_id": "risk",
            "type": "risk",
            "title": "PII Collection in ML Training Data",
            "description": "ML model training requires user behavioral data that constitutes PII.",
            "impact": "high",
            "confidence": "directional",
            "evidence": [
                {"source_id": "TICKET-002", "source_type": "ticket",
                 "excerpt": "Use ML model to rank notifications by predicted importance."}
            ],
            "tags": ["privacy", "pii"],
            "metadata": {
                "category": "privacy",
                "is_blocker": False,
                "mitigation": "Implement data minimization and explicit consent mechanism.",
                "policy_rule": "require_collection_justification",
            },
        }
    ],
    "summary": "Identified 1 high-severity privacy risk.",
})

_CRITICAL_PRIVACY_RISK_RESPONSE = json.dumps({
    "findings": [
        {
            "id": "risk-001",
            "agent_id": "risk",
            "type": "risk",
            "title": "Critical PII Exposure Without Consent",
            "description": "ML pipeline ingests raw behavioral PII with no consent mechanism in place.",
            "impact": "critical",
            "confidence": "validated",
            "evidence": [
                {"source_id": "TICKET-002", "source_type": "ticket",
                 "excerpt": "Use ML model to rank notifications by predicted importance."}
            ],
            "tags": ["privacy", "pii", "critical"],
            "metadata": {
                "category": "privacy",
                "is_blocker": True,
                "mitigation": "Block launch until explicit consent mechanism is implemented.",
                "policy_rule": "block_on_critical_privacy",
            },
        }
    ],
    "summary": "Identified 1 critical privacy blocker.",
})

# Lead PM routing responses
_DEDUP_NO_CLUSTERS = json.dumps({"clusters": []})
_DEDUP_WITH_CLUSTER = json.dumps({
    "clusters": [
        {
            "finding_ids": ["customer-001", "competitive-001"],
            "reason": "Both describe the same notification fatigue problem from different perspectives.",
        }
    ]
})
_RANKING_TWO_SCORES = json.dumps({
    "scores": [
        {"finding_id": "customer-001", "user_impact": 9, "business_value": 8, "effort": 3, "risk": 7},
        {"finding_id": "competitive-001", "user_impact": 7, "business_value": 6, "effort": 2, "risk": 5},
    ]
})
_RANKING_CONFLICT_SCORES = json.dumps({
    "scores": [
        {"finding_id": "requirements-001", "user_impact": 8, "business_value": 7, "effort": 4, "risk": 8},
        {"finding_id": "risk-001", "user_impact": 5, "business_value": 5, "effort": 2, "risk": 9},
    ]
})
_CONFLICT_NO_CONFLICTS = json.dumps({"conflicts": []})
_CONFLICT_WITH_CONFLICT = json.dumps({
    "conflicts": [
        {
            "finding_a": "requirements-001",
            "finding_b": "risk-001",
            "description": "Data collection requirement conflicts with GDPR-blocking privacy risk.",
            "resolution": "Implement data minimization and obtain explicit consent before collecting any PII.",
            "reasoning": "Privacy compliance takes precedence per policy; feature can proceed with reduced scope.",
        }
    ]
})


# ── CUSTOMER AGENT TESTS ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_customer_valid_output(run_config, default_policy, sample_context):
    """CustomerInsightsAgent returns AgentOutput with correct agent_id and non-empty findings."""
    client = _make_openai_mock(_CUSTOMER_RESPONSE)
    agent = CustomerInsightsAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "customer"
    assert len(output.findings) > 0
    for f in output.findings:
        assert f.agent_id == "customer"
        assert f.type in {"insight", "gap", "recommendation"}
        assert f.impact in {"critical", "high", "medium", "low"}
        assert f.confidence in {"validated", "directional", "speculative"}
        assert f.title
        assert f.description


@pytest.mark.asyncio
async def test_customer_evidence_linking(run_config, default_policy, sample_context):
    """Each customer finding references a valid source_id from the context_packet."""
    valid_ids = {t.id for t in sample_context.tickets} | {d.id for d in sample_context.documents}
    client = _make_openai_mock(_CUSTOMER_RESPONSE)
    agent = CustomerInsightsAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    for f in output.findings:
        assert f.evidence, f"Finding {f.id} has no evidence items"
        for ev in f.evidence:
            assert ev.source_id in valid_ids, (
                f"Finding {f.id} references unknown source_id '{ev.source_id}'"
            )
            assert ev.excerpt.strip(), f"Evidence excerpt for finding {f.id} is empty"


@pytest.mark.asyncio
async def test_customer_handles_empty_context(run_config, default_policy, minimal_context):
    """CustomerInsightsAgent returns empty findings gracefully when no customer data exists."""
    client = _make_openai_mock(_CUSTOMER_RESPONSE)
    agent = CustomerInsightsAgent(client, run_config, default_policy, minimal_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "customer"
    assert output.findings == []
    assert len(output.errors) > 0


@pytest.mark.asyncio
async def test_customer_handles_llm_error(run_config, default_policy, sample_context):
    """CustomerInsightsAgent raises AgentError with correct agent_id when LLM call fails."""
    client = _make_openai_mock(RuntimeError("simulated LLM failure"))
    agent = CustomerInsightsAgent(client, run_config, default_policy, sample_context)

    with pytest.raises(AgentError) as exc_info:
        await agent.analyze()

    assert exc_info.value.agent_id == "customer"


# ── COMPETITIVE AGENT TESTS ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_competitive_valid_output(run_config, default_policy, sample_context):
    """CompetitiveAgent returns AgentOutput with correct agent_id and non-empty findings."""
    client = _make_openai_mock(_COMPETITIVE_RESPONSE)
    agent = CompetitiveAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "competitive"
    assert len(output.findings) > 0
    for f in output.findings:
        assert f.agent_id == "competitive"
        assert f.type in {"insight", "gap", "recommendation"}
        assert f.impact in {"critical", "high", "medium", "low"}
        assert f.confidence in {"validated", "directional", "speculative"}
        assert f.title
        assert f.description


@pytest.mark.asyncio
async def test_competitive_evidence_linking(run_config, default_policy, sample_context):
    """Each competitive finding references a valid source_id from the context_packet."""
    valid_ids = {t.id for t in sample_context.tickets} | {d.id for d in sample_context.documents}
    client = _make_openai_mock(_COMPETITIVE_RESPONSE)
    agent = CompetitiveAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    for f in output.findings:
        assert f.evidence, f"Finding {f.id} has no evidence items"
        for ev in f.evidence:
            assert ev.source_id in valid_ids, (
                f"Finding {f.id} references unknown source_id '{ev.source_id}'"
            )
            assert ev.excerpt.strip(), f"Evidence excerpt for finding {f.id} is empty"


@pytest.mark.asyncio
async def test_competitive_handles_empty_context(run_config, default_policy, minimal_context):
    """CompetitiveAgent returns empty findings gracefully when no competitive data exists."""
    client = _make_openai_mock(_COMPETITIVE_RESPONSE)
    agent = CompetitiveAgent(client, run_config, default_policy, minimal_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "competitive"
    assert output.findings == []
    assert len(output.errors) > 0


@pytest.mark.asyncio
async def test_competitive_handles_llm_error(run_config, default_policy, sample_context):
    """CompetitiveAgent raises AgentError with correct agent_id when LLM call fails."""
    client = _make_openai_mock(RuntimeError("simulated LLM failure"))
    agent = CompetitiveAgent(client, run_config, default_policy, sample_context)

    with pytest.raises(AgentError) as exc_info:
        await agent.analyze()

    assert exc_info.value.agent_id == "competitive"


# ── METRICS AGENT TESTS ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_valid_output(run_config, default_policy, sample_context):
    """MetricsAgent returns AgentOutput with correct agent_id and metric findings."""
    client = _make_openai_mock(_METRICS_RESPONSE)
    agent = MetricsAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "metrics"
    assert len(output.findings) > 0
    for f in output.findings:
        assert f.agent_id == "metrics"
        assert f.type in {"metric", "gap", "recommendation"}
        assert f.impact in {"critical", "high", "medium", "low"}
        assert f.confidence in {"validated", "directional", "speculative"}
        assert f.title
        assert f.description


@pytest.mark.asyncio
async def test_metrics_evidence_linking(run_config, default_policy, sample_context):
    """Each metrics finding references a valid source_id from the context_packet."""
    valid_ids = {t.id for t in sample_context.tickets} | {d.id for d in sample_context.documents}
    client = _make_openai_mock(_METRICS_RESPONSE)
    agent = MetricsAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    for f in output.findings:
        assert f.evidence, f"Finding {f.id} has no evidence items"
        for ev in f.evidence:
            assert ev.source_id in valid_ids, (
                f"Finding {f.id} references unknown source_id '{ev.source_id}'"
            )
            assert ev.excerpt.strip(), f"Evidence excerpt for finding {f.id} is empty"


@pytest.mark.asyncio
async def test_metrics_handles_empty_context(run_config, default_policy, minimal_context):
    """MetricsAgent returns empty findings gracefully when no metrics data exists."""
    client = _make_openai_mock(_METRICS_RESPONSE)
    agent = MetricsAgent(client, run_config, default_policy, minimal_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "metrics"
    assert output.findings == []
    assert len(output.errors) > 0


@pytest.mark.asyncio
async def test_metrics_handles_llm_error(run_config, default_policy, sample_context):
    """MetricsAgent raises AgentError with correct agent_id when LLM call fails."""
    client = _make_openai_mock(RuntimeError("simulated LLM failure"))
    agent = MetricsAgent(client, run_config, default_policy, sample_context)

    with pytest.raises(AgentError) as exc_info:
        await agent.analyze()

    assert exc_info.value.agent_id == "metrics"


# ── REQUIREMENTS AGENT TESTS ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_requirements_valid_output(run_config, default_policy, sample_context):
    """RequirementsAgent returns AgentOutput with requirement findings."""
    # Pre-seed upstream findings so _load_upstream_findings has rich data
    _write_findings_file(run_config, "customer", _upstream_output("customer", run_config.run_id))
    _write_findings_file(run_config, "metrics", _upstream_output("metrics", run_config.run_id))

    client = _make_openai_mock(_REQUIREMENTS_RESPONSE)
    agent = RequirementsAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "requirements"
    assert len(output.findings) > 0
    for f in output.findings:
        assert f.agent_id == "requirements"
        assert f.type in {"requirement", "gap", "recommendation"}
        assert f.impact in {"critical", "high", "medium", "low"}
        assert f.title
        assert f.description


@pytest.mark.asyncio
async def test_requirements_evidence_linking(run_config, default_policy, sample_context):
    """Each requirement finding has non-empty evidence items with source_ids and excerpts."""
    _write_findings_file(run_config, "customer", _upstream_output("customer", run_config.run_id))

    client = _make_openai_mock(_REQUIREMENTS_RESPONSE)
    agent = RequirementsAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    for f in output.findings:
        assert f.evidence, f"Finding {f.id} has no evidence items"
        for ev in f.evidence:
            assert ev.source_id, f"Evidence source_id for finding {f.id} is empty"
            assert ev.excerpt.strip(), f"Evidence excerpt for finding {f.id} is empty"


@pytest.mark.asyncio
async def test_requirements_handles_empty_context(run_config, default_policy, minimal_context):
    """RequirementsAgent returns empty findings when context has no data and no upstream files."""
    client = _make_openai_mock(_REQUIREMENTS_RESPONSE)
    agent = RequirementsAgent(client, run_config, default_policy, minimal_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "requirements"
    assert output.findings == []


@pytest.mark.asyncio
async def test_requirements_handles_llm_error(run_config, default_policy, sample_context):
    """RequirementsAgent raises AgentError with correct agent_id when LLM call fails."""
    # Seed upstream data so the agent reaches the LLM call
    _write_findings_file(run_config, "customer", _upstream_output("customer", run_config.run_id))

    client = _make_openai_mock(RuntimeError("simulated LLM failure"))
    agent = RequirementsAgent(client, run_config, default_policy, sample_context)

    with pytest.raises(AgentError) as exc_info:
        await agent.analyze()

    assert exc_info.value.agent_id == "requirements"


# ── FEASIBILITY AGENT TESTS ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feasibility_valid_output(run_config, default_policy, sample_context):
    """FeasibilityAgent returns AgentOutput with dependency/risk findings."""
    _write_findings_file(run_config, "requirements", _upstream_output("requirements", run_config.run_id))

    client = _make_openai_mock(_FEASIBILITY_RESPONSE)
    agent = FeasibilityAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "feasibility"
    assert len(output.findings) > 0
    for f in output.findings:
        assert f.agent_id == "feasibility"
        assert f.type in {"dependency", "risk", "recommendation"}
        assert f.impact in {"critical", "high", "medium", "low"}
        assert f.title
        assert f.description


@pytest.mark.asyncio
async def test_feasibility_evidence_linking(run_config, default_policy, sample_context):
    """Each feasibility finding has non-empty evidence items with source_ids and excerpts."""
    _write_findings_file(run_config, "requirements", _upstream_output("requirements", run_config.run_id))

    client = _make_openai_mock(_FEASIBILITY_RESPONSE)
    agent = FeasibilityAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    for f in output.findings:
        assert f.evidence, f"Finding {f.id} has no evidence items"
        for ev in f.evidence:
            assert ev.source_id, f"Evidence source_id for finding {f.id} is empty"
            assert ev.excerpt.strip(), f"Evidence excerpt for finding {f.id} is empty"


@pytest.mark.asyncio
async def test_feasibility_handles_empty_context(run_config, default_policy, minimal_context):
    """FeasibilityAgent returns empty findings when context has no data and no upstream files."""
    client = _make_openai_mock(_FEASIBILITY_RESPONSE)
    agent = FeasibilityAgent(client, run_config, default_policy, minimal_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "feasibility"
    assert output.findings == []


@pytest.mark.asyncio
async def test_feasibility_handles_llm_error(run_config, default_policy, sample_context):
    """FeasibilityAgent raises AgentError with correct agent_id when LLM call fails."""
    _write_findings_file(run_config, "requirements", _upstream_output("requirements", run_config.run_id))

    client = _make_openai_mock(RuntimeError("simulated LLM failure"))
    agent = FeasibilityAgent(client, run_config, default_policy, sample_context)

    with pytest.raises(AgentError) as exc_info:
        await agent.analyze()

    assert exc_info.value.agent_id == "feasibility"


# ── RISK AGENT TESTS ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_valid_output(run_config, default_policy, sample_context):
    """RiskAgent returns AgentOutput with risk-type findings."""
    # sample_context has risk_hotspots → upstream_data is non-empty without extra files
    client = _make_openai_mock(_RISK_RESPONSE)
    agent = RiskAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "risk"
    assert len(output.findings) > 0
    for f in output.findings:
        assert f.agent_id == "risk"
        assert f.type == "risk"
        assert f.impact in {"critical", "high", "medium", "low"}
        assert f.confidence in {"validated", "directional", "speculative"}
        assert f.title
        assert f.description


@pytest.mark.asyncio
async def test_risk_evidence_linking(run_config, default_policy, sample_context):
    """Each risk finding has non-empty evidence items with source_ids and excerpts."""
    client = _make_openai_mock(_RISK_RESPONSE)
    agent = RiskAgent(client, run_config, default_policy, sample_context)

    output = await agent.analyze()

    for f in output.findings:
        assert f.evidence, f"Finding {f.id} has no evidence items"
        for ev in f.evidence:
            assert ev.source_id, f"Evidence source_id for finding {f.id} is empty"
            assert ev.excerpt.strip(), f"Evidence excerpt for finding {f.id} is empty"


@pytest.mark.asyncio
async def test_risk_handles_empty_context(run_config, default_policy, minimal_context):
    """RiskAgent returns empty findings when there are no upstream files and no risk hotspots."""
    client = _make_openai_mock(_RISK_RESPONSE)
    agent = RiskAgent(client, run_config, default_policy, minimal_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "risk"
    assert output.findings == []


@pytest.mark.asyncio
async def test_risk_handles_llm_error(run_config, default_policy, sample_context):
    """RiskAgent raises AgentError with correct agent_id when LLM call fails."""
    # sample_context has risk_hotspots → agent reaches LLM call
    client = _make_openai_mock(RuntimeError("simulated LLM failure"))
    agent = RiskAgent(client, run_config, default_policy, sample_context)

    with pytest.raises(AgentError) as exc_info:
        await agent.analyze()

    assert exc_info.value.agent_id == "risk"


@pytest.mark.asyncio
async def test_risk_agent_policy_gate(run_config, strict_policy, sample_context):
    """RiskAgent correctly applies policy gating: critical privacy finding blocks the pipeline."""
    client = _make_openai_mock(_CRITICAL_PRIVACY_RISK_RESPONSE)
    agent = RiskAgent(client, run_config, strict_policy, sample_context)

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "risk"
    # Summary must report a FAILED gate
    assert "FAILED" in output.summary
    assert "blocker" in output.summary.lower()

    # Verify risk_gate_result.json was written with passed=False
    gate_path = (
        Path(run_config.output_dir)
        / run_config.run_id
        / "findings"
        / "risk_gate_result.json"
    )
    assert gate_path.exists(), "risk_gate_result.json was not created"
    gate_result = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate_result["passed"] is False
    assert len(gate_result["blockers"]) > 0


# ── LEAD PM AGENT SPECIAL TESTS ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lead_pm_dedup(run_config, default_policy, sample_context):
    """LeadPMAgent deduplicates similar findings, keeping the highest-confidence one."""
    # Two findings about the same notification fatigue topic — customer has higher confidence
    finding_customer = Finding(
        id="customer-001",
        agent_id="customer",
        type="insight",
        title="Notification fatigue is the top user pain point",
        description="Users mute all notifications due to overwhelming volume.",
        impact="high",
        confidence="validated",
        evidence=[EvidenceItem(
            source_id="TICKET-001", source_type="ticket",
            excerpt="Users receive too many notifications and mute them.",
        )],
    )
    finding_competitive = Finding(
        id="competitive-001",
        agent_id="competitive",
        type="insight",
        title="Users overwhelmed by notification volume",
        description="Same notification fatigue issue surfaced in competitive analysis.",
        impact="medium",
        confidence="directional",
        evidence=[EvidenceItem(
            source_id="DOC-001", source_type="doc",
            excerpt="Competitor X uses smart filtering achieving a 40% lower mute rate.",
        )],
    )

    output_a = AgentOutput(
        agent_id="customer", agent_name="Customer Agent",
        run_id=run_config.run_id, findings=[finding_customer],
    )
    output_b = AgentOutput(
        agent_id="competitive", agent_name="Competitive Agent",
        run_id=run_config.run_id, findings=[finding_competitive],
    )

    client = _make_routing_mock({
        "duplicate or substantially overlapping": _DEDUP_WITH_CLUSTER,
        "score each finding on four dimensions": json.dumps({"scores": [
            {"finding_id": "customer-001", "user_impact": 9, "business_value": 8, "effort": 3, "risk": 7},
        ]}),
        "contradictions or tensions": _CONFLICT_NO_CONFLICTS,
    })

    agent = LeadPMAgent(
        llm_client=client,
        run_config=run_config,
        policy_pack=default_policy,
        context_packet=sample_context,
        all_agent_outputs=[output_a, output_b],
    )

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "lead_pm"

    # Dedup: customer-001 kept (validated > directional), competitive-001 removed
    assert len(agent.consolidated_findings) == 1
    assert agent.consolidated_findings[0].id == "customer-001"
    assert len(agent.dedup_log) == 1
    assert "competitive-001" in agent.dedup_log[0]["removed"]


@pytest.mark.asyncio
async def test_lead_pm_conflict_resolution(run_config, default_policy, sample_context):
    """LeadPMAgent identifies and records a resolution for contradictory findings."""
    finding_req = Finding(
        id="requirements-001",
        agent_id="requirements",
        type="requirement",
        title="Collect user browsing history for ML training",
        description="ML model accuracy requires access to user browsing history.",
        impact="high",
        confidence="validated",
        evidence=[EvidenceItem(
            source_id="TICKET-002", source_type="ticket",
            excerpt="Use ML model to rank notifications by predicted importance.",
        )],
    )
    finding_risk = Finding(
        id="risk-001",
        agent_id="risk",
        type="risk",
        title="Browsing history collection violates GDPR without consent",
        description="Collecting browsing history without explicit opt-in consent is a GDPR violation.",
        impact="critical",
        confidence="validated",
        evidence=[EvidenceItem(
            source_id="requirements-001", source_type="doc",
            excerpt="browsing history collection requirement",
        )],
        tags=["privacy"],
    )

    output_req = AgentOutput(
        agent_id="requirements", agent_name="Requirements Agent",
        run_id=run_config.run_id, findings=[finding_req],
    )
    output_risk = AgentOutput(
        agent_id="risk", agent_name="Risk Agent",
        run_id=run_config.run_id, findings=[finding_risk],
    )

    client = _make_routing_mock({
        "duplicate or substantially overlapping": _DEDUP_NO_CLUSTERS,
        "score each finding on four dimensions": _RANKING_CONFLICT_SCORES,
        "contradictions or tensions": _CONFLICT_WITH_CONFLICT,
    })

    agent = LeadPMAgent(
        llm_client=client,
        run_config=run_config,
        policy_pack=default_policy,
        context_packet=sample_context,
        all_agent_outputs=[output_req, output_risk],
    )

    output = await agent.analyze()

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "lead_pm"

    # Conflict detected and recorded
    assert len(agent.conflicts) == 1
    conflict = agent.conflicts[0]
    assert conflict["finding_a"] == "requirements-001"
    assert conflict["finding_b"] == "risk-001"
    assert "resolution" in conflict
    assert conflict["resolution"]
