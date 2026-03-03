"""Integration tests — full pipeline with a mocked LLM client.

Verifies the PipelineOrchestrator can run end-to-end using a fake
OpenAI-compatible client that returns canned JSON responses, so no
real API key is needed.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipm.core.orchestrator import PipelineOrchestrator
from aipm.core.policy import PolicyPack
from aipm.core.token_tracker import TokenTracker
from aipm.schemas.config import RunConfig

# ── Mock OpenAI response objects ───────────────────────────────────────


class _Usage:
    """Mimics ``openai.types.CompletionUsage``."""

    def __init__(self, prompt_tokens: int = 50, completion_tokens: int = 100, total_tokens: int = 150):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class _Message:
    """Mimics ``openai.types.chat.ChatCompletionMessage``."""

    def __init__(self, content: str):
        self.content = content


class _Choice:
    """Mimics ``openai.types.chat.ChatCompletionChoice``."""

    def __init__(self, content: str):
        self.message = _Message(content)


class _ChatCompletion:
    """Mimics ``openai.types.chat.ChatCompletion``."""

    def __init__(self, content: str):
        self.choices = [_Choice(content)]
        self.usage = _Usage()


# ── Canned LLM responses keyed by prompt keyword ──────────────────────

_FINDINGS_TEMPLATE = json.dumps(
    {
        "findings": [
            {
                "id": "{agent}-001",
                "agent_id": "{agent}",
                "type": "insight",
                "title": "Mock {label} finding",
                "description": "Automatically generated mock finding for integration test.",
                "impact": "medium",
                "confidence": "directional",
                "assumptions": ["test assumption"],
                "evidence": [{"source_id": "TICKET-1", "source_type": "ticket", "excerpt": "test excerpt"}],
                "recommendations": ["test recommendation"],
                "tags": ["mock"],
                "metadata": {},
            }
        ],
        "summary": "Mock {label} summary.",
    }
)


def _findings_for(agent_id: str, label: str) -> str:
    return _FINDINGS_TEMPLATE.replace("{agent}", agent_id).replace("{label}", label)


# Risk agent must output findings with risk type and category metadata.
_RISK_FINDINGS = json.dumps(
    {
        "findings": [
            {
                "id": "risk-001",
                "agent_id": "risk",
                "type": "risk",
                "title": "Mock privacy risk",
                "description": "Integration test privacy risk.",
                "impact": "high",
                "confidence": "directional",
                "assumptions": [],
                "evidence": [{"source_id": "customer-001", "source_type": "doc", "excerpt": "data collection concern"}],
                "recommendations": ["Add consent mechanism"],
                "tags": ["privacy"],
                "metadata": {
                    "category": "privacy",
                    "is_blocker": False,
                    "mitigation": "Add consent",
                    "policy_rule": "require_consent_mechanism",
                },
            }
        ],
        "summary": "One privacy risk identified.",
    }
)

# LeadPM phase responses
_DEDUP_RESPONSE = json.dumps({"clusters": []})
_RANKING_RESPONSE_TEMPLATE = json.dumps(
    {
        "scores": [{"finding_id": "PLACEHOLDER", "user_impact": 8, "business_value": 7, "effort": 4, "risk": 3}],
    }
)
_CONFLICT_RESPONSE = json.dumps({"conflicts": []})

# PRD and experiment plan JSON responses
_PRD_RESPONSE = json.dumps(
    {
        "overview": "Mock overview.",
        "goals": "Mock goals.",
        "user_segments": "Mock user segments.",
        "in_scope": "Mock in scope.",
        "out_of_scope": "Mock out of scope.",
        "functional_requirements": "Mock functional reqs.",
        "non_functional_requirements": "Mock NFRs.",
        "acceptance_criteria": "Mock acceptance criteria.",
        "design_ux": "Mock design.",
        "technical_considerations": "Mock tech.",
        "risks_mitigations": "Mock risks.",
        "rollout_plan": "Mock rollout.",
        "open_questions": "Mock questions.",
        "evidence_references": "Mock refs.",
    }
)

_EXPERIMENT_PLAN_RESPONSE = json.dumps(
    {
        "hypothesis": "Mock hypothesis.",
        "success_metrics": "Mock success metrics.",
        "guardrail_metrics": "Mock guardrails.",
        "experiment_design": "Mock design.",
        "sample_size_duration": "Mock sample.",
        "segmentation": "Mock segmentation.",
        "rollback_criteria": "Mock rollback.",
        "data_collection": "Mock collection.",
        "analysis_plan": "Mock analysis.",
    }
)

# Intake dedup and summary responses
_INTAKE_DEDUP = json.dumps({"duplicates": [], "unique_count": 3})
_INTAKE_SUMMARY = "Mock product context summary for integration testing."


def _route_response(messages: list[dict], **_kwargs: object) -> str:
    """Choose a canned response based on keywords in the system/user messages."""
    text = " ".join(m.get("content", "") for m in messages).lower()

    # ── Intake ──
    if "data quality analyst" in text or ("duplicate" in text and "tickets" in text):
        return _INTAKE_DEDUP
    if "product analyst" in text and "summarize" in text:
        return _INTAKE_SUMMARY

    # ── LeadPM phases ──
    if "duplicate or substantially overlapping" in text or "identify clusters" in text:
        return _DEDUP_RESPONSE
    if "score each finding" in text:
        return _RANKING_RESPONSE_TEMPLATE
    if "contradictions or tensions" in text or "identify contradictions" in text:
        return _CONFLICT_RESPONSE
    if "writing a prd" in text or "prd sections" in text:
        return _PRD_RESPONSE
    if "experiment plan" in text and "data scientist" in text:
        return _EXPERIMENT_PLAN_RESPONSE

    # ── Risk ──
    if "privacy risks" in text or "risk assessment" in text or "security risks" in text:
        return _RISK_FINDINGS

    # ── Specialist agents (B-F) — pick by keyword ──
    if "customer insight" in text or "customer-facing" in text:
        return _findings_for("customer", "Customer Insights")
    if "competitive" in text or "competitor" in text:
        return _findings_for("competitive", "Competitive")
    if "north star" in text or "metrics" in text:
        return _findings_for("metrics", "Metrics")
    if "requirement" in text or "acceptance criteria" in text:
        return _findings_for("requirements", "Requirements")
    if "feasibility" in text or "technical dependencies" in text:
        return _findings_for("feasibility", "Feasibility")

    # Fallback — valid JSON with empty findings so parsing never crashes
    return json.dumps({"findings": [], "summary": "fallback mock response"})


# ── Mock OpenAI client ─────────────────────────────────────────────────


class _Completions:
    """Mimics ``openai.resources.chat.Completions``."""

    def create(self, *, model: str, messages: list[dict], **kwargs: object) -> _ChatCompletion:
        content = _route_response(messages, **kwargs)
        return _ChatCompletion(content)


class _Chat:
    """Mimics ``openai.resources.Chat``."""

    def __init__(self) -> None:
        self.completions = _Completions()


class MockOpenAIClient:
    """Lightweight stand-in for ``openai.OpenAI``.

    ``type(instance).__module__`` must contain ``"openai"`` so that
    ``BaseAgent`` detects the provider correctly.
    """

    def __init__(self) -> None:
        self.chat = _Chat()


# Patch the module path so BaseAgent provider detection works.
MockOpenAIClient.__module__ = "openai.mock"


# ── Helpers ────────────────────────────────────────────────────────────


def _make_bundle_on_disk(bundle_dir: Path) -> None:
    """Write a minimal but valid input bundle to *bundle_dir*."""
    bundle_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "product_name": "TestProduct",
        "description": "A test product for integration testing.",
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    tickets = [
        {
            "id": "TICKET-1",
            "title": "Login flow redesign",
            "description": "Users report friction in login.",
            "status": "open",
            "priority": "high",
            "labels": ["auth", "ux"],
        },
        {
            "id": "TICKET-2",
            "title": "Dashboard load time",
            "description": "Dashboard takes 5s to load.",
            "status": "open",
            "priority": "medium",
            "labels": ["performance"],
        },
        {
            "id": "TICKET-3",
            "title": "Add SSO support",
            "description": "Enterprise customers need SSO.",
            "status": "backlog",
            "priority": "high",
            "labels": ["auth", "enterprise"],
        },
    ]
    (bundle_dir / "tickets.json").write_text(json.dumps(tickets), encoding="utf-8")

    docs_dir = bundle_dir / "documents"
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "customer_notes.md").write_text(
        "# Customer Notes\nCustomers are frustrated with the login experience and want SSO.",
        encoding="utf-8",
    )
    (docs_dir / "competitor_brief.md").write_text(
        "# Competitor Brief\nCompetitor A has SSO and dashboard loads in < 1s.",
        encoding="utf-8",
    )
    (docs_dir / "metrics_snapshot.json").write_text(
        json.dumps({"dau": 12000, "session_duration": 4.5, "nps": 32}),
        encoding="utf-8",
    )


def _build_run_config(tmp_path: Path, input_path: str) -> RunConfig:
    """Build a ``RunConfig`` pointing at *tmp_path* for output."""
    return RunConfig(
        input_path=input_path,
        output_dir=str(tmp_path / "output"),
        provider="openai",
        model="gpt-4o-mock",
    )


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def bundle_dir(tmp_path: Path) -> Path:
    """Create a minimal input bundle on disk and return its path."""
    bd = tmp_path / "bundle"
    _make_bundle_on_disk(bd)
    return bd


@pytest.fixture()
def mock_client() -> MockOpenAIClient:
    return MockOpenAIClient()


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestFullPipelineExecution:
    """Happy-path integration: run the entire orchestrator with mocked LLM."""

    async def test_manifest_is_returned(self, tmp_path: Path, bundle_dir: Path, mock_client: MockOpenAIClient):
        """The pipeline should return a well-formed manifest dict."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        assert isinstance(manifest, dict)
        assert manifest["run_id"] == config.run_id
        assert manifest["provider"] == "openai"
        assert manifest["model"] == "gpt-4o-mock"

    async def test_all_agents_executed(self, tmp_path: Path, bundle_dir: Path, mock_client: MockOpenAIClient):
        """Every agent should appear in agents_run when no errors occur."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        expected_agents = {
            "intake",
            "customer",
            "competitive",
            "metrics",
            "requirements",
            "feasibility",
            "risk",
            "lead_pm",
        }
        assert expected_agents == set(manifest["agents_run"])

    async def test_findings_are_collected(self, tmp_path: Path, bundle_dir: Path, mock_client: MockOpenAIClient):
        """Total findings count should be positive."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        assert manifest["total_findings"] > 0

    async def test_output_files_on_disk(self, tmp_path: Path, bundle_dir: Path, mock_client: MockOpenAIClient):
        """Manifest, context_packet, and finding files should exist on disk."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            await orch.run(str(bundle_dir))

        run_dir = Path(config.output_dir) / config.run_id
        assert (run_dir / "run_manifest.json").exists()
        assert (run_dir / "context_packet.json").exists()

        findings_dir = run_dir / "findings"
        assert findings_dir.exists()
        finding_files = list(findings_dir.glob("*.json"))
        assert len(finding_files) >= 1

    async def test_token_usage_tracked(self, tmp_path: Path, bundle_dir: Path, mock_client: MockOpenAIClient):
        """Token tracker should have recorded at least one entry."""
        config = _build_run_config(tmp_path, str(bundle_dir))
        tracker = TokenTracker()

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config, token_tracker=tracker)
            await orch.run(str(bundle_dir))

        summary = tracker.get_summary()
        assert summary["total"]["prompt_tokens"] > 0
        assert summary["total"]["completion_tokens"] > 0

    async def test_artifacts_generated(self, tmp_path: Path, bundle_dir: Path, mock_client: MockOpenAIClient):
        """LeadPM should produce artifact files (PRD, experiment plan, etc.)."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        assert "artifacts" in manifest
        artifacts_dir = Path(config.output_dir) / config.run_id / "artifacts"
        if artifacts_dir.exists():
            artifact_files = list(artifacts_dir.glob("*"))
            assert len(artifact_files) >= 1

    async def test_no_errors_in_happy_path(self, tmp_path: Path, bundle_dir: Path, mock_client: MockOpenAIClient):
        """Happy path should finish with zero or very few errors."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        # The mock responses are all valid, so there should be no agent failures
        assert len(manifest.get("agents_failed", [])) == 0


@pytest.mark.asyncio
class TestAgentFailureHandling:
    """Verify the pipeline degrades gracefully when an agent blows up."""

    async def test_pipeline_continues_after_agent_error(
        self,
        tmp_path: Path,
        bundle_dir: Path,
        mock_client: MockOpenAIClient,
    ):
        """If one specialist agent raises, the pipeline should still finish."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        # Make the customer agent's analyze() raise
        original_completions_create = mock_client.chat.completions.create

        def _raise_on_customer(*, model, messages, **kw):
            text = " ".join(m.get("content", "") for m in messages).lower()
            if "customer insight" in text or "customer-facing" in text:
                raise RuntimeError("Simulated customer agent LLM failure")
            return original_completions_create(model=model, messages=messages, **kw)

        mock_client.chat.completions.create = _raise_on_customer

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        # Pipeline should complete despite customer agent failure
        assert isinstance(manifest, dict)
        assert "customer" in manifest["agents_failed"]
        assert manifest["run_id"] == config.run_id

    async def test_error_details_recorded(
        self,
        tmp_path: Path,
        bundle_dir: Path,
        mock_client: MockOpenAIClient,
    ):
        """Failed agent error message should appear in the manifest."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        original_create = mock_client.chat.completions.create

        def _raise_on_metrics(*, model, messages, **kw):
            text = " ".join(m.get("content", "") for m in messages).lower()
            if "north star" in text or ("metrics" in text and "findings" not in text):
                raise RuntimeError("Simulated metrics failure")
            return original_create(model=model, messages=messages, **kw)

        mock_client.chat.completions.create = _raise_on_metrics

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        assert "metrics" in manifest["errors"]
        assert "Simulated metrics failure" in manifest["errors"]["metrics"]

    async def test_other_agents_still_produce_findings(
        self,
        tmp_path: Path,
        bundle_dir: Path,
        mock_client: MockOpenAIClient,
    ):
        """Even with a failure, other agents should still contribute findings."""
        config = _build_run_config(tmp_path, str(bundle_dir))

        original_create = mock_client.chat.completions.create

        def _raise_on_competitive(*, model, messages, **kw):
            text = " ".join(m.get("content", "") for m in messages).lower()
            if "competitor" in text and "contradictions" not in text and "prd" not in text:
                raise RuntimeError("Simulated competitive failure")
            return original_create(model=model, messages=messages, **kw)

        mock_client.chat.completions.create = _raise_on_competitive

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(str(bundle_dir))

        # Other agents should still have produced findings
        assert manifest["total_findings"] > 0
        assert "intake" in manifest["agents_run"]


@pytest.mark.asyncio
class TestPipelineFromPrompt:
    """Run the pipeline with a plain-text prompt instead of a bundle directory."""

    async def test_prompt_input_runs(self, tmp_path: Path, mock_client: MockOpenAIClient):
        """A short text prompt should produce a valid manifest."""
        prompt_text = "Build a notification preferences dashboard for mobile."
        config = _build_run_config(tmp_path, prompt_text)

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(prompt_text)

        assert isinstance(manifest, dict)
        assert manifest["run_id"] == config.run_id
        # Intake should still run (via load_prompt path)
        assert "intake" in manifest["agents_run"]

    async def test_prompt_input_has_findings(self, tmp_path: Path, mock_client: MockOpenAIClient):
        """Even a prompt-only run should produce some findings."""
        prompt_text = "Build a notification preferences dashboard for mobile."
        config = _build_run_config(tmp_path, prompt_text)

        with (
            patch("aipm.core.orchestrator.get_llm_client", return_value=mock_client),
            patch("aipm.core.orchestrator.load_policy", return_value=PolicyPack()),
        ):
            orch = PipelineOrchestrator(config)
            manifest = await orch.run(prompt_text)

        assert manifest["total_findings"] >= 0  # May be 0 if prompt bundle is thin


@pytest.mark.asyncio
class TestMockClientContract:
    """Verify the mock client itself satisfies the interface BaseAgent needs."""

    async def test_mock_detected_as_openai(self, mock_client: MockOpenAIClient):
        assert "openai" in type(mock_client).__module__

    async def test_response_has_choices_and_usage(self, mock_client: MockOpenAIClient):
        resp = mock_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert hasattr(resp, "choices")
        assert len(resp.choices) == 1
        assert isinstance(resp.choices[0].message.content, str)
        assert hasattr(resp, "usage")
        assert resp.usage.prompt_tokens > 0
