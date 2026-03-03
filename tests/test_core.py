"""Unit tests for core modules: config, loader, policy, and validators."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipm.core.config import MODELS, ensure_output_dirs, get_llm_client, load_run_config
from aipm.core.loader import load_bundle, load_prompt, validate_bundle
from aipm.core.policy import PolicyPack, evaluate_risk_gate, load_policy
from aipm.core.validators import (
    generate_evidence_index,
    validate_agent_output,
    validate_context_packet,
    validate_findings_consistency,
)
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket, DocumentItem, TicketItem
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

# ===================================================================
# Config Tests
# ===================================================================


class TestConfig:
    """Tests for src/aipm/core/config.py."""

    def test_load_run_config(self):
        """Verify RunConfig creation with defaults."""
        config = load_run_config("input_bundles/sample_bundle")

        assert isinstance(config, RunConfig)
        assert config.input_path == "input_bundles/sample_bundle"
        assert config.output_dir == "output"
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.temperature == 0.2
        assert len(config.run_id) == 36  # UUID format

    def test_load_run_config_with_overrides(self):
        """Verify RunConfig creation with overrides."""
        config = load_run_config(
            "my_bundle",
            output_dir="/tmp/out",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            temperature=0.5,
        )

        assert config.input_path == "my_bundle"
        assert config.output_dir == "/tmp/out"
        assert config.provider == "anthropic"
        assert config.model == "claude-sonnet-4-20250514"
        assert config.temperature == 0.5

    def test_ensure_output_dirs(self, tmp_path):
        """Verify directories are created."""
        config = RunConfig(input_path="test", output_dir=str(tmp_path))

        run_dir = ensure_output_dirs(config)

        assert run_dir.exists()
        assert (run_dir / "findings").is_dir()
        assert (run_dir / "artifacts").is_dir()
        assert run_dir.name == config.run_id

    def test_get_llm_client_openai(self, monkeypatch):
        """Mock OpenAI and verify client creation."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")

        mock_openai_class = MagicMock()
        mock_module = MagicMock()
        mock_module.OpenAI = mock_openai_class

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = get_llm_client("openai")

        mock_openai_class.assert_called_once_with(api_key="test-key-123")
        assert client == mock_openai_class.return_value

    def test_get_llm_client_anthropic(self, monkeypatch):
        """Mock Anthropic and verify client creation."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-456")

        mock_anthropic_class = MagicMock()
        mock_module = MagicMock()
        mock_module.Anthropic = mock_anthropic_class

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = get_llm_client("anthropic")

        mock_anthropic_class.assert_called_once_with(api_key="test-key-456")
        assert client == mock_anthropic_class.return_value

    def test_get_llm_client_missing_key(self, monkeypatch):
        """Verify error when API key is missing."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
            get_llm_client("openai")

    def test_get_llm_client_invalid_provider(self):
        """Verify error for unsupported provider."""
        with pytest.raises(ValueError, match="Unsupported provider"):
            get_llm_client("gemini")

    def test_models_dict(self):
        """Verify MODELS mapping has expected structure."""
        assert "openai" in MODELS
        assert "anthropic" in MODELS
        assert "default" in MODELS["openai"]
        assert "default" in MODELS["anthropic"]


# ===================================================================
# Loader Tests
# ===================================================================


class TestLoader:
    """Tests for src/aipm/core/loader.py."""

    def _create_bundle(self, tmp_path: Path, include_metrics: bool = True) -> Path:
        """Helper to create a temp bundle directory."""
        bundle_dir = tmp_path / "test_bundle"
        bundle_dir.mkdir()

        # manifest.json
        manifest = {
            "product_name": "TestProduct",
            "description": "A test product for unit tests",
            "input_type": "bundle",
        }
        (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        # tickets.json
        tickets = [
            {
                "id": "TICKET-001",
                "title": "Add feature X",
                "description": "Users want feature X.",
                "status": "open",
                "priority": "high",
                "labels": ["feature"],
                "source": "jira",
            }
        ]
        (bundle_dir / "tickets.json").write_text(json.dumps(tickets), encoding="utf-8")

        # documents
        docs_dir = bundle_dir / "documents"
        docs_dir.mkdir()
        (docs_dir / "customer_notes.md").write_text(
            "# Customer Notes\n\nUsers report they need better onboarding.", encoding="utf-8"
        )
        (docs_dir / "competitor_brief.md").write_text(
            "# Competitor Brief\n\nCompetitor A has feature X.", encoding="utf-8"
        )
        if include_metrics:
            metrics = {"dau": 10000, "retention_7d": 0.55}
            (docs_dir / "metrics_snapshot.json").write_text(json.dumps(metrics), encoding="utf-8")

        return bundle_dir

    def test_load_bundle(self, tmp_path):
        """Create a temp bundle directory, load it, verify structure."""
        bundle_dir = self._create_bundle(tmp_path)

        bundle = load_bundle(str(bundle_dir))

        assert bundle["product_name"] == "TestProduct"
        assert bundle["description"] == "A test product for unit tests"
        assert bundle["input_type"] == "bundle"
        assert len(bundle["tickets"]) == 1
        assert bundle["tickets"][0]["id"] == "TICKET-001"
        assert len(bundle["documents"]) >= 2  # at least customer_notes + competitor_brief

    def test_load_bundle_missing_dir(self):
        """Verify FileNotFoundError for missing directory."""
        with pytest.raises(FileNotFoundError):
            load_bundle("/nonexistent/path")

    def test_load_bundle_missing_manifest(self, tmp_path):
        """Verify FileNotFoundError when manifest.json is absent."""
        empty_dir = tmp_path / "empty_bundle"
        empty_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="manifest.json"):
            load_bundle(str(empty_dir))

    def test_load_prompt(self):
        """Convert a text prompt to bundle format."""
        prompt = "Build a notification system that reduces alert fatigue."

        bundle = load_prompt(prompt)

        assert bundle["product_name"] == prompt[:60].strip()
        assert bundle["description"] == prompt.strip()
        assert bundle["input_type"] == "prompt"
        assert bundle["tickets"] == []
        assert bundle["documents"] == []

    def test_validate_bundle_complete(self, tmp_path):
        """Validate a complete bundle returns no warnings."""
        bundle_dir = self._create_bundle(tmp_path, include_metrics=True)
        bundle = load_bundle(str(bundle_dir))

        warnings = validate_bundle(bundle)

        assert warnings == []

    def test_validate_bundle_missing_metrics(self, tmp_path):
        """Verify warning for missing metrics snapshot."""
        bundle_dir = self._create_bundle(tmp_path, include_metrics=False)
        bundle = load_bundle(str(bundle_dir))

        warnings = validate_bundle(bundle)

        assert any("metrics" in w.lower() for w in warnings)

    def test_validate_bundle_empty(self):
        """Validate a minimal/empty bundle gets multiple warnings."""
        bundle = {
            "product_name": "",
            "description": "",
            "tickets": [],
            "documents": [],
        }

        warnings = validate_bundle(bundle)

        assert len(warnings) >= 3  # missing name, description, tickets, documents


# ===================================================================
# Policy Tests
# ===================================================================


class TestPolicy:
    """Tests for src/aipm/core/policy.py."""

    def test_load_default_policy(self, project_root):
        """Load the default YAML and verify all sections."""
        policy_path = project_root / "src" / "aipm" / "policies" / "default_policy.yaml"
        policy = load_policy(str(policy_path))

        assert isinstance(policy, PolicyPack)
        assert len(policy.product_principles) > 0
        assert len(policy.non_goals) > 0
        assert policy.data_handling.require_collection_justification is True
        assert policy.data_handling.retention_limit_days == 90
        assert policy.experimentation.min_sample_size == 1000
        assert policy.accessibility.wcag_level == "AA"
        assert policy.risk_gating.block_on_critical_privacy is True
        assert policy.risk_gating.max_unmitigated_high_risks == 2

    def test_load_policy_not_found(self):
        """Verify FileNotFoundError for missing policy file."""
        with pytest.raises(FileNotFoundError):
            load_policy("/nonexistent/policy.yaml")

    def test_risk_gate_pass(self):
        """Findings with no critical issues pass the gate."""
        policy = PolicyPack()
        findings = [
            Finding(
                id="risk-001",
                agent_id="risk",
                type="risk",
                title="Minor UI inconsistency",
                description="Button color differs from design spec.",
                impact="low",
                confidence="validated",
                tags=["ux"],
            ),
        ]

        result = evaluate_risk_gate(findings, policy)

        assert result["passed"] is True
        assert result["blockers"] == []

    def test_risk_gate_block(self):
        """Critical privacy finding with block_on_critical_privacy blocks."""
        policy = PolicyPack()  # defaults have block_on_critical_privacy = True
        findings = [
            Finding(
                id="risk-010",
                agent_id="risk",
                type="risk",
                title="User PII exposed in logs",
                description="Application logs contain unmasked email addresses.",
                impact="critical",
                confidence="validated",
                tags=["privacy", "pii"],
            ),
        ]

        result = evaluate_risk_gate(findings, policy)

        assert result["passed"] is False
        assert len(result["blockers"]) >= 1
        assert any("privacy" in b.lower() for b in result["blockers"])

    def test_risk_gate_warnings(self):
        """High-severity findings generate warnings but still pass if under threshold."""
        policy = PolicyPack()  # max_unmitigated_high_risks = 2
        findings = [
            Finding(
                id="risk-020",
                agent_id="risk",
                type="risk",
                title="Auth token rotation missing",
                description="Tokens never expire, posing a security risk.",
                impact="high",
                confidence="directional",
                tags=["security"],
            ),
            Finding(
                id="risk-021",
                agent_id="risk",
                type="risk",
                title="Privacy consent banner incomplete",
                description="GDPR consent flow does not cover all data types.",
                impact="high",
                confidence="validated",
                tags=["privacy"],
            ),
        ]

        result = evaluate_risk_gate(findings, policy)

        # 2 high risks = exactly at the limit, should pass
        assert result["passed"] is True
        # Privacy-tagged findings should trigger legal review warnings
        assert len(result["warnings"]) >= 1

    def test_risk_gate_block_too_many_high(self):
        """Exceeding max_unmitigated_high_risks triggers a blocker."""
        policy = PolicyPack()  # max = 2
        findings = [
            Finding(
                id=f"risk-{i:03d}",
                agent_id="risk",
                type="risk",
                title=f"High risk #{i}",
                description=f"Unmitigated high risk number {i}.",
                impact="high",
                confidence="directional",
                tags=["platform"],
            )
            for i in range(3)
        ]

        result = evaluate_risk_gate(findings, policy)

        assert result["passed"] is False
        assert any("exceed" in b.lower() or "high risk" in b.lower() for b in result["blockers"])


# ===================================================================
# Validators Tests
# ===================================================================


class TestValidators:
    """Tests for src/aipm/core/validators.py."""

    def test_validate_unique_finding_ids(self):
        """Duplicate IDs caught."""
        dup_finding = Finding(
            id="test-001",
            agent_id="test",
            type="insight",
            title="Finding A",
            description="Desc A.",
            impact="medium",
            confidence="validated",
        )
        output = AgentOutput(
            agent_id="test",
            agent_name="Test Agent",
            run_id="run-dup",
            findings=[dup_finding, dup_finding],  # same ID twice
        )

        warnings = validate_agent_output(output)

        assert any("Duplicate finding ID" in w for w in warnings)

    def test_validate_evidence_references(self):
        """Missing source_ids flagged."""
        finding = Finding(
            id="test-002",
            agent_id="test",
            type="insight",
            title="Finding with bad ref",
            description="References nonexistent source.",
            impact="medium",
            confidence="directional",
            evidence=[
                EvidenceItem(
                    source_id="NONEXISTENT-999",
                    source_type="ticket",
                    excerpt="Some excerpt",
                ),
            ],
        )
        output = AgentOutput(
            agent_id="test",
            agent_name="Test Agent",
            run_id="run-ref",
            findings=[finding],
        )
        # Create a context packet with no matching source
        packet = ContextPacket(
            run_id="run-ref",
            product_name="Test",
            product_description="Test product",
            raw_input_type="bundle",
            tickets=[
                TicketItem(
                    id="TICKET-001",
                    title="Real ticket",
                    description="Existing ticket.",
                    status="open",
                    source="jira",
                ),
            ],
        )

        warnings = validate_agent_output(output, context_packet=packet)

        assert any("unknown source_id" in w for w in warnings)
        assert any("NONEXISTENT-999" in w for w in warnings)

    def test_validate_agent_output_valid(self):
        """A well-formed output produces no warnings (no context packet)."""
        finding = Finding(
            id="clean-001",
            agent_id="clean",
            type="insight",
            title="Clean finding",
            description="All fields valid.",
            impact="high",
            confidence="validated",
        )
        output = AgentOutput(
            agent_id="clean",
            agent_name="Clean Agent",
            run_id="run-clean",
            findings=[finding],
        )

        warnings = validate_agent_output(output)

        assert warnings == []

    def test_validate_context_packet_complete(self):
        """Valid context packet passes validation."""
        packet = ContextPacket(
            run_id="run-ok",
            product_name="GoodProduct",
            product_description="A fine product.",
            raw_input_type="bundle",
            tickets=[
                TicketItem(id="T-1", title="T", description="D", status="open", source="jira"),
            ],
            documents=[
                DocumentItem(id="D-1", title="notes", content="content", doc_type="note"),
                DocumentItem(id="D-2", title="metrics", content="{}", doc_type="metrics_snapshot"),
            ],
        )

        warnings = validate_context_packet(packet)

        assert warnings == []

    def test_validate_context_packet_missing_customer_docs(self):
        """Warn when no customer-facing documents exist."""
        packet = ContextPacket(
            run_id="run-noc",
            product_name="NoCustomerDocs",
            product_description="Product missing customer notes.",
            raw_input_type="bundle",
            documents=[
                DocumentItem(id="D-1", title="spec", content="spec content", doc_type="spec"),
            ],
        )

        warnings = validate_context_packet(packet)

        assert any("customer" in w.lower() for w in warnings)

    def test_findings_consistency_stats(self):
        """Verify correct counting by type, agent, confidence, impact."""
        findings = [
            Finding(
                id="a-001",
                agent_id="customer",
                type="insight",
                title="User pain point",
                description="Pain.",
                impact="high",
                confidence="validated",
            ),
            Finding(
                id="b-001",
                agent_id="metrics",
                type="metric",
                title="North Star metric",
                description="DAU.",
                impact="critical",
                confidence="validated",
            ),
            Finding(
                id="c-001",
                agent_id="risk",
                type="risk",
                title="Privacy risk",
                description="PII issue.",
                impact="high",
                confidence="directional",
            ),
        ]

        stats = validate_findings_consistency(findings)

        assert stats["total_findings"] == 3
        assert stats["by_type"]["insight"] == 1
        assert stats["by_type"]["metric"] == 1
        assert stats["by_type"]["risk"] == 1
        assert stats["by_agent"]["customer"] == 1
        assert stats["by_agent"]["metrics"] == 1
        assert stats["by_agent"]["risk"] == 1
        assert stats["by_confidence"]["validated"] == 2
        assert stats["by_confidence"]["directional"] == 1
        assert stats["by_impact"]["high"] == 2
        assert stats["by_impact"]["critical"] == 1

    def test_findings_consistency_duplicates(self):
        """Cross-agent duplicates detected by title similarity."""
        findings = [
            Finding(
                id="cust-001",
                agent_id="customer",
                type="insight",
                title="Users need better notification controls",
                description="From customer interviews.",
                impact="high",
                confidence="validated",
            ),
            Finding(
                id="req-001",
                agent_id="requirements",
                type="requirement",
                title="Users need better notification controls",  # almost identical
                description="From requirements analysis.",
                impact="high",
                confidence="directional",
            ),
        ]

        stats = validate_findings_consistency(findings)

        assert len(stats["potential_duplicates"]) >= 1

    def test_generate_evidence_index(self):
        """Verify source_id → finding_id mapping."""
        findings = [
            Finding(
                id="f-001",
                agent_id="customer",
                type="insight",
                title="Finding 1",
                description="Desc 1.",
                impact="medium",
                confidence="validated",
                evidence=[
                    EvidenceItem(source_id="TICKET-001", source_type="ticket", excerpt="E1"),
                    EvidenceItem(source_id="DOC-001", source_type="doc", excerpt="E2"),
                ],
            ),
            Finding(
                id="f-002",
                agent_id="metrics",
                type="metric",
                title="Finding 2",
                description="Desc 2.",
                impact="high",
                confidence="directional",
                evidence=[
                    EvidenceItem(source_id="TICKET-001", source_type="ticket", excerpt="E3"),
                ],
            ),
        ]

        index = generate_evidence_index(findings)

        assert "TICKET-001" in index
        assert set(index["TICKET-001"]) == {"f-001", "f-002"}
        assert "DOC-001" in index
        assert index["DOC-001"] == ["f-001"]

    def test_generate_evidence_index_empty(self):
        """Empty findings list produces empty index."""
        index = generate_evidence_index([])

        assert index == {}
