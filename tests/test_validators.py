"""Tests for validation utilities in aipm.core.validators."""

import pytest

from aipm.core.validators import (
    generate_evidence_index,
    validate_agent_output,
    validate_context_packet,
    validate_findings_consistency,
)
from aipm.schemas.context import ContextPacket, DocumentItem, TicketItem
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def sample_context_packet():
    """A well-formed context packet for testing."""
    return ContextPacket(
        run_id="test-run-001",
        product_name="TestProduct",
        product_description="A test product for validation tests.",
        raw_input_type="bundle",
        tickets=[
            TicketItem(id="T-001", title="Bug report", description="Something broken", status="open", source="manual"),
            TicketItem(id="T-002", title="Feature request", description="Want a thing", status="open", source="manual"),
        ],
        documents=[
            DocumentItem(id="DOC-001", title="Customer Notes", content="User feedback", doc_type="note"),
            DocumentItem(id="DOC-002", title="Metrics Snapshot", content="DAU: 1000", doc_type="metrics_snapshot"),
        ],
    )


@pytest.fixture
def sample_finding():
    """A valid finding with evidence."""
    return Finding(
        id="customer-001",
        agent_id="customer",
        type="insight",
        title="Users want faster notifications",
        description="Multiple sources indicate latency is a pain point.",
        impact="high",
        confidence="validated",
        evidence=[
            EvidenceItem(source_id="T-001", source_type="ticket", excerpt="Something broken"),
        ],
    )


@pytest.fixture
def sample_agent_output(sample_finding):
    """A valid agent output."""
    return AgentOutput(
        agent_id="customer",
        agent_name="Customer Insights Agent",
        run_id="test-run-001",
        findings=[sample_finding],
        summary="Found 1 insight.",
    )


# ── validate_agent_output tests ──────────────────────────────────────


class TestValidateAgentOutput:
    def test_valid_output_passes(self, sample_agent_output, sample_context_packet):
        warnings = validate_agent_output(sample_agent_output, sample_context_packet)
        assert warnings == []

    def test_duplicate_finding_ids(self, sample_context_packet):
        dup_finding = Finding(
            id="dup-001", agent_id="test", type="insight",
            title="A", description="B", impact="high", confidence="validated",
        )
        output = AgentOutput(
            agent_id="test", agent_name="Test", run_id="run-1",
            findings=[dup_finding, dup_finding],
        )
        warnings = validate_agent_output(output)
        assert any("Duplicate finding ID" in w for w in warnings)

    def test_unknown_evidence_source(self, sample_context_packet):
        finding = Finding(
            id="test-001", agent_id="test", type="insight",
            title="A", description="B", impact="high", confidence="validated",
            evidence=[EvidenceItem(source_id="NONEXISTENT", source_type="ticket", excerpt="x")],
        )
        output = AgentOutput(
            agent_id="test", agent_name="Test", run_id="run-1",
            findings=[finding],
        )
        warnings = validate_agent_output(output, sample_context_packet)
        assert any("unknown source_id 'NONEXISTENT'" in w for w in warnings)

    def test_valid_output_without_context(self, sample_agent_output):
        """Validation without context packet skips evidence checks."""
        warnings = validate_agent_output(sample_agent_output)
        assert warnings == []


# ── validate_context_packet tests ────────────────────────────────────


class TestValidateContextPacket:
    def test_valid_packet_passes(self, sample_context_packet):
        warnings = validate_context_packet(sample_context_packet)
        assert warnings == []

    def test_missing_product_name(self):
        packet = ContextPacket(
            run_id="run-1", product_name="", product_description="desc",
            raw_input_type="bundle",
        )
        warnings = validate_context_packet(packet)
        assert any("Missing product_name" in w for w in warnings)

    def test_duplicate_ticket_ids(self):
        packet = ContextPacket(
            run_id="run-1", product_name="P", product_description="D",
            raw_input_type="bundle",
            tickets=[
                TicketItem(id="T-001", title="A", description="B", status="open", source="manual"),
                TicketItem(id="T-001", title="C", description="D", status="open", source="manual"),
            ],
        )
        warnings = validate_context_packet(packet)
        assert any("Duplicate ticket ID" in w for w in warnings)

    def test_no_customer_docs_warning(self):
        packet = ContextPacket(
            run_id="run-1", product_name="P", product_description="D",
            raw_input_type="bundle",
            documents=[
                DocumentItem(id="DOC-001", title="Spec", content="x", doc_type="spec"),
            ],
        )
        warnings = validate_context_packet(packet)
        assert any("No customer-facing documents" in w for w in warnings)

    def test_no_metrics_warning(self):
        packet = ContextPacket(
            run_id="run-1", product_name="P", product_description="D",
            raw_input_type="bundle",
            documents=[
                DocumentItem(id="DOC-001", title="Notes", content="x", doc_type="note"),
            ],
        )
        warnings = validate_context_packet(packet)
        assert any("No metrics snapshot" in w for w in warnings)


# ── validate_findings_consistency tests ──────────────────────────────


class TestValidateFindingsConsistency:
    def test_counts_by_type(self):
        findings = [
            Finding(id="a-001", agent_id="a", type="insight", title="X", description="D", impact="high", confidence="validated"),
            Finding(id="a-002", agent_id="a", type="gap", title="Y", description="D", impact="medium", confidence="directional"),
            Finding(id="b-001", agent_id="b", type="insight", title="Z", description="D", impact="low", confidence="speculative"),
        ]
        result = validate_findings_consistency(findings)
        assert result["total_findings"] == 3
        assert result["by_type"]["insight"] == 2
        assert result["by_type"]["gap"] == 1
        assert result["by_agent"]["a"] == 2
        assert result["by_agent"]["b"] == 1

    def test_detects_cross_agent_duplicates(self):
        findings = [
            Finding(id="a-001", agent_id="a", type="insight", title="Users want faster notifications", description="D", impact="high", confidence="validated"),
            Finding(id="b-001", agent_id="b", type="insight", title="Users want faster notifications", description="D", impact="high", confidence="validated"),
        ]
        result = validate_findings_consistency(findings)
        assert len(result["potential_duplicates"]) >= 1
        dup = result["potential_duplicates"][0]
        assert dup["finding_a"] == "a-001"
        assert dup["finding_b"] == "b-001"

    def test_no_duplicates_within_same_agent(self):
        findings = [
            Finding(id="a-001", agent_id="a", type="insight", title="Same title here", description="D", impact="high", confidence="validated"),
            Finding(id="a-002", agent_id="a", type="insight", title="Same title here", description="D", impact="high", confidence="validated"),
        ]
        result = validate_findings_consistency(findings)
        assert result["potential_duplicates"] == []

    def test_empty_findings(self):
        result = validate_findings_consistency([])
        assert result["total_findings"] == 0
        assert result["potential_duplicates"] == []


# ── generate_evidence_index tests ────────────────────────────────────


class TestGenerateEvidenceIndex:
    def test_basic_index(self):
        findings = [
            Finding(
                id="a-001", agent_id="a", type="insight", title="X", description="D",
                impact="high", confidence="validated",
                evidence=[EvidenceItem(source_id="T-001", source_type="ticket", excerpt="x")],
            ),
            Finding(
                id="b-001", agent_id="b", type="gap", title="Y", description="D",
                impact="medium", confidence="directional",
                evidence=[
                    EvidenceItem(source_id="T-001", source_type="ticket", excerpt="y"),
                    EvidenceItem(source_id="DOC-001", source_type="doc", excerpt="z"),
                ],
            ),
        ]
        index = generate_evidence_index(findings)
        assert "T-001" in index
        assert len(index["T-001"]) == 2
        assert "a-001" in index["T-001"]
        assert "b-001" in index["T-001"]
        assert index["DOC-001"] == ["b-001"]

    def test_empty_findings(self):
        index = generate_evidence_index([])
        assert index == {}

    def test_findings_with_no_evidence(self):
        findings = [
            Finding(id="a-001", agent_id="a", type="insight", title="X", description="D", impact="high", confidence="validated"),
        ]
        index = generate_evidence_index(findings)
        assert index == {}
