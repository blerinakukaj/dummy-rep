"""Comprehensive unit tests for all Pydantic schemas."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from aipm.schemas.config import RunConfig
from aipm.schemas.context import (
    ContextPacket,
    DocumentItem,
    RiskHotspot,
    TicketItem,
)
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_ticket():
    """A valid TicketItem dict."""
    return {
        "id": "TICKET-001",
        "title": "Add notification preferences",
        "description": "Users need a way to configure which notifications they receive.",
        "status": "open",
        "priority": "high",
        "labels": ["feature", "ux"],
        "created_at": "2025-11-15",
        "source": "jira",
    }


@pytest.fixture
def sample_document():
    """A valid DocumentItem dict."""
    return {
        "id": "DOC-001",
        "title": "customer_notes.md",
        "content": "Interview with power users revealed engagement issues.",
        "doc_type": "note",
        "tags": ["customer", "interview"],
    }


@pytest.fixture
def sample_risk_hotspot():
    """A valid RiskHotspot dict."""
    return {
        "category": "privacy",
        "description": "User data collection without explicit consent mechanism",
        "severity": "high",
        "source_ids": ["TICKET-003"],
    }


@pytest.fixture
def sample_evidence():
    """A valid EvidenceItem dict."""
    return {
        "source_id": "TICKET-042",
        "source_type": "ticket",
        "excerpt": "Users report notification fatigue with 20+ alerts daily",
        "url": None,
    }


@pytest.fixture
def sample_finding(sample_evidence):
    """A valid Finding dict with all fields populated."""
    return {
        "id": "customer-001",
        "agent_id": "customer",
        "type": "insight",
        "title": "Notification fatigue is the top user pain point",
        "description": "Multiple sources confirm users are overwhelmed by notification volume.",
        "impact": "high",
        "confidence": "validated",
        "assumptions": ["Users who mute notifications are less likely to return"],
        "evidence": [sample_evidence],
        "recommendations": ["Implement ML-based notification prioritization"],
        "tags": ["ux", "engagement"],
        "metadata": {"segment": "power_users"},
    }


@pytest.fixture
def sample_context_packet(sample_ticket, sample_document, sample_risk_hotspot):
    """A valid ContextPacket dict."""
    return {
        "run_id": "run-test-001",
        "product_name": "SmartNotify",
        "product_description": "Intelligent notification prioritization system",
        "tickets": [sample_ticket],
        "documents": [sample_document],
        "risk_hotspots": [sample_risk_hotspot],
        "missing_info": ["No competitor brief provided"],
        "dedup_log": ["Merged TICKET-002 into TICKET-001 (duplicate)"],
        "raw_input_type": "bundle",
    }


# ===================================================================
# ContextPacket Tests
# ===================================================================


class TestContextPacket:
    """Tests for the ContextPacket schema."""

    def test_valid_context_packet(self, sample_context_packet):
        """Create a valid ContextPacket and verify all fields."""
        packet = ContextPacket(**sample_context_packet)

        assert packet.run_id == "run-test-001"
        assert packet.product_name == "SmartNotify"
        assert packet.product_description == "Intelligent notification prioritization system"
        assert len(packet.tickets) == 1
        assert packet.tickets[0].id == "TICKET-001"
        assert len(packet.documents) == 1
        assert packet.documents[0].doc_type == "note"
        assert len(packet.risk_hotspots) == 1
        assert packet.risk_hotspots[0].category == "privacy"
        assert packet.missing_info == ["No competitor brief provided"]
        assert len(packet.dedup_log) == 1
        assert packet.raw_input_type == "bundle"

    def test_context_packet_defaults(self):
        """Verify default values and auto-generated fields."""
        packet = ContextPacket(
            run_id="run-defaults",
            product_name="TestProduct",
            product_description="A test product",
            raw_input_type="prompt",
        )

        # Lists should default to empty
        assert packet.tickets == []
        assert packet.documents == []
        assert packet.risk_hotspots == []
        assert packet.missing_info == []
        assert packet.dedup_log == []

        # created_at should be auto-generated as a UTC datetime
        assert isinstance(packet.created_at, datetime)
        assert packet.created_at.tzinfo is not None

    def test_invalid_ticket_source(self, sample_ticket):
        """Verify Literal validation rejects invalid source types."""
        sample_ticket["source"] = "github"  # not in Literal["jira", "ado", "manual"]

        with pytest.raises(ValidationError) as exc_info:
            TicketItem(**sample_ticket)

        errors = exc_info.value.errors()
        assert any("source" in str(e["loc"]) for e in errors)

    def test_invalid_raw_input_type(self):
        """Verify Literal validation rejects invalid raw_input_type."""
        with pytest.raises(ValidationError):
            ContextPacket(
                run_id="run-bad",
                product_name="X",
                product_description="Y",
                raw_input_type="file",  # not in Literal["prompt", "bundle"]
            )

    def test_risk_hotspot_categories(self):
        """Test all valid risk hotspot categories."""
        valid_categories = [
            "privacy",
            "auth",
            "pricing",
            "platform",
            "accessibility",
            "security",
            "compliance",
        ]

        for category in valid_categories:
            hotspot = RiskHotspot(
                category=category,
                description=f"Test {category} risk",
                severity="medium",
                source_ids=["SRC-001"],
            )
            assert hotspot.category == category

    def test_risk_hotspot_invalid_category(self):
        """Verify invalid risk hotspot category is rejected."""
        with pytest.raises(ValidationError):
            RiskHotspot(
                category="unknown_category",
                description="Bad category",
                severity="medium",
            )

    def test_document_types(self):
        """Test all valid document types."""
        valid_types = ["prd", "spec", "note", "interview", "metrics_snapshot", "competitor_brief"]

        for doc_type in valid_types:
            doc = DocumentItem(
                id=f"DOC-{doc_type}",
                title=f"Test {doc_type}",
                content="Test content",
                doc_type=doc_type,
            )
            assert doc.doc_type == doc_type


# ===================================================================
# Finding Tests
# ===================================================================


class TestFinding:
    """Tests for the Finding schema."""

    def test_valid_finding(self, sample_finding):
        """Create a Finding with all fields and verify serialization."""
        finding = Finding(**sample_finding)

        assert finding.id == "customer-001"
        assert finding.agent_id == "customer"
        assert finding.type == "insight"
        assert finding.title == "Notification fatigue is the top user pain point"
        assert finding.impact == "high"
        assert finding.confidence == "validated"
        assert len(finding.assumptions) == 1
        assert len(finding.evidence) == 1
        assert finding.evidence[0].source_id == "TICKET-042"
        assert len(finding.recommendations) == 1
        assert "ux" in finding.tags
        assert finding.metadata["segment"] == "power_users"

        # Verify serialization produces a dict with all keys
        data = finding.model_dump()
        assert "id" in data
        assert "evidence" in data
        assert data["evidence"][0]["source_type"] == "ticket"

    def test_finding_json_roundtrip(self, sample_finding):
        """Serialize to JSON and back, verify equality."""
        original = Finding(**sample_finding)

        json_str = original.model_dump_json()
        restored = Finding.model_validate_json(json_str)

        assert original.id == restored.id
        assert original.agent_id == restored.agent_id
        assert original.type == restored.type
        assert original.title == restored.title
        assert original.description == restored.description
        assert original.impact == restored.impact
        assert original.confidence == restored.confidence
        assert original.assumptions == restored.assumptions
        assert original.recommendations == restored.recommendations
        assert original.tags == restored.tags
        assert original.metadata == restored.metadata
        assert len(original.evidence) == len(restored.evidence)
        assert original.evidence[0].source_id == restored.evidence[0].source_id

    def test_finding_id_format(self):
        """Verify Finding accepts properly formatted IDs."""
        # Standard agent-number format
        finding = Finding(
            id="metrics-003",
            agent_id="metrics",
            type="metric",
            title="North Star metric",
            description="DAU is the North Star metric.",
            impact="critical",
            confidence="validated",
        )
        assert finding.id == "metrics-003"

        # Another valid pattern
        finding2 = Finding(
            id="risk-100",
            agent_id="risk",
            type="risk",
            title="Security concern",
            description="Auth weakness detected.",
            impact="high",
            confidence="directional",
        )
        assert finding2.id == "risk-100"

    def test_confidence_levels(self):
        """Test all three confidence levels."""
        levels = ["validated", "directional", "speculative"]

        for level in levels:
            finding = Finding(
                id=f"test-{level[:3]}",
                agent_id="test",
                type="insight",
                title=f"Test {level}",
                description=f"Confidence level: {level}",
                impact="medium",
                confidence=level,
            )
            assert finding.confidence == level

    def test_invalid_confidence_level(self):
        """Verify invalid confidence level is rejected."""
        with pytest.raises(ValidationError):
            Finding(
                id="test-bad",
                agent_id="test",
                type="insight",
                title="Bad confidence",
                description="Should fail",
                impact="medium",
                confidence="uncertain",  # not valid
            )

    def test_finding_types(self):
        """Test all valid finding types."""
        valid_types = [
            "insight",
            "risk",
            "requirement",
            "metric",
            "gap",
            "recommendation",
            "dependency",
        ]

        for ftype in valid_types:
            finding = Finding(
                id=f"test-{ftype[:3]}",
                agent_id="test",
                type=ftype,
                title=f"Test {ftype}",
                description=f"Finding type: {ftype}",
                impact="low",
                confidence="speculative",
            )
            assert finding.type == ftype

    def test_finding_defaults(self):
        """Verify list fields default to empty lists."""
        finding = Finding(
            id="test-def",
            agent_id="test",
            type="insight",
            title="Minimal finding",
            description="Only required fields.",
            impact="low",
            confidence="speculative",
        )

        assert finding.assumptions == []
        assert finding.evidence == []
        assert finding.recommendations == []
        assert finding.tags == []
        assert finding.metadata == {}

    def test_evidence_item_url_optional(self, sample_evidence):
        """Verify EvidenceItem works with and without URL."""
        ev_no_url = EvidenceItem(**sample_evidence)
        assert ev_no_url.url is None

        sample_evidence["url"] = "https://jira.example.com/TICKET-042"
        ev_with_url = EvidenceItem(**sample_evidence)
        assert ev_with_url.url == "https://jira.example.com/TICKET-042"


# ===================================================================
# AgentOutput Tests
# ===================================================================


class TestAgentOutput:
    """Tests for the AgentOutput schema."""

    def test_agent_output_with_findings(self, sample_finding):
        """Create AgentOutput with multiple findings."""
        finding1 = Finding(**sample_finding)
        finding2_data = sample_finding.copy()
        finding2_data["id"] = "customer-002"
        finding2_data["title"] = "Enterprise users need admin controls"
        finding2 = Finding(**finding2_data)

        output = AgentOutput(
            agent_id="customer",
            agent_name="Customer Insights Agent",
            run_id="run-test-001",
            findings=[finding1, finding2],
            summary="Identified 2 key user pain points.",
        )

        assert output.agent_id == "customer"
        assert output.agent_name == "Customer Insights Agent"
        assert output.run_id == "run-test-001"
        assert len(output.findings) == 2
        assert output.findings[0].id == "customer-001"
        assert output.findings[1].id == "customer-002"
        assert output.summary == "Identified 2 key user pain points."
        assert output.errors == []

    def test_agent_output_serialization(self, sample_finding):
        """Full JSON serialization test."""
        finding = Finding(**sample_finding)
        output = AgentOutput(
            agent_id="customer",
            agent_name="Customer Insights Agent",
            run_id="run-test-001",
            findings=[finding],
            summary="Test summary.",
        )

        json_str = output.model_dump_json()
        parsed = json.loads(json_str)

        assert parsed["agent_id"] == "customer"
        assert parsed["agent_name"] == "Customer Insights Agent"
        assert parsed["run_id"] == "run-test-001"
        assert len(parsed["findings"]) == 1
        assert parsed["findings"][0]["id"] == "customer-001"
        assert "timestamp" in parsed
        assert parsed["summary"] == "Test summary."
        assert parsed["errors"] == []

        # Roundtrip back to model
        restored = AgentOutput.model_validate_json(json_str)
        assert restored.agent_id == output.agent_id
        assert len(restored.findings) == len(output.findings)

    def test_empty_findings_allowed(self):
        """Verify agent can return 0 findings."""
        output = AgentOutput(
            agent_id="metrics",
            agent_name="Metrics & Analytics Agent",
            run_id="run-empty",
            findings=[],
            summary="No actionable findings.",
        )

        assert len(output.findings) == 0
        assert output.summary == "No actionable findings."

    def test_agent_output_defaults(self):
        """Verify default fields in AgentOutput."""
        output = AgentOutput(
            agent_id="intake",
            agent_name="Intake Agent",
            run_id="run-defaults",
        )

        assert output.findings == []
        assert output.summary == ""
        assert output.errors == []
        assert isinstance(output.timestamp, datetime)
        assert output.timestamp.tzinfo is not None

    def test_agent_output_with_errors(self):
        """Verify errors list captures agent errors."""
        output = AgentOutput(
            agent_id="risk",
            agent_name="Risk Agent",
            run_id="run-err",
            findings=[],
            summary="Partial analysis completed.",
            errors=["LLM timeout on first attempt", "Retried successfully"],
        )

        assert len(output.errors) == 2
        assert "LLM timeout" in output.errors[0]


# ===================================================================
# RunConfig Tests
# ===================================================================


class TestRunConfig:
    """Tests for the RunConfig schema."""

    def test_default_run_config(self):
        """Verify defaults when only required fields are provided."""
        config = RunConfig(input_path="input_bundles/sample_bundle")

        # run_id should be auto-generated UUID
        assert config.run_id is not None
        assert len(config.run_id) == 36  # UUID format: 8-4-4-4-12

        # Check defaults
        assert config.output_dir == "output"
        assert config.provider == "openai"
        assert config.model == "gpt-4o-mini"
        assert config.temperature == 0.2
        assert config.policy_path == "src/aipm/policies/default_policy.yaml"

    def test_custom_run_config(self):
        """Override all fields and verify."""
        config = RunConfig(
            run_id="custom-run-id",
            input_path="/data/my_bundle",
            output_dir="/data/output",
            provider="openai",
            model="gpt-4o-mini",
            temperature=0.7,
            policy_path="policies/strict_privacy_policy.yaml",
        )

        assert config.run_id == "custom-run-id"
        assert config.input_path == "/data/my_bundle"
        assert config.output_dir == "/data/output"
        assert config.provider == "openai"
        assert config.model == "gpt-4o-mini"
        assert config.temperature == 0.7
        assert config.policy_path == "policies/strict_privacy_policy.yaml"

    def test_run_config_unique_ids(self):
        """Verify auto-generated run_ids are unique across instances."""
        config1 = RunConfig(input_path="a")
        config2 = RunConfig(input_path="b")

        assert config1.run_id != config2.run_id

    def test_run_config_temperature_bounds(self):
        """Verify temperature respects ge=0.0, le=2.0 constraints."""
        # Valid boundaries
        low = RunConfig(input_path="x", temperature=0.0)
        assert low.temperature == 0.0

        high = RunConfig(input_path="x", temperature=2.0)
        assert high.temperature == 2.0

        # Invalid: below 0
        with pytest.raises(ValidationError):
            RunConfig(input_path="x", temperature=-0.1)

        # Invalid: above 2
        with pytest.raises(ValidationError):
            RunConfig(input_path="x", temperature=2.1)

    def test_run_config_invalid_provider(self):
        """Verify invalid provider is rejected."""
        with pytest.raises(ValidationError):
            RunConfig(input_path="x", provider="gemini")
