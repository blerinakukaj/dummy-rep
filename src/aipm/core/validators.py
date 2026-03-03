"""Validation utilities for agent outputs, context packets, and cross-agent consistency."""

import logging
from collections import Counter
from difflib import SequenceMatcher

from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)

# Valid values defined by the Finding schema
VALID_CONFIDENCE = {"validated", "directional", "speculative"}
VALID_IMPACT = {"critical", "high", "medium", "low"}
VALID_FINDING_TYPES = {"insight", "risk", "requirement", "metric", "gap", "recommendation", "dependency"}

# Threshold for detecting duplicate findings by title similarity
DUPLICATE_SIMILARITY_THRESHOLD = 0.8


def validate_agent_output(output: AgentOutput, context_packet: ContextPacket | None = None) -> list[str]:
    """Validate an AgentOutput for structural and referential integrity.

    Args:
        output: The agent output to validate.
        context_packet: Optional context packet for checking evidence references.

    Returns:
        List of validation warnings. Empty list means the output is valid.
    """
    warnings: list[str] = []

    # Check for unique finding IDs
    finding_ids = [f.id for f in output.findings]
    id_counts = Counter(finding_ids)
    for fid, count in id_counts.items():
        if count > 1:
            warnings.append(f"Duplicate finding ID: '{fid}' appears {count} times")

    # Build set of valid source IDs from context packet
    valid_source_ids: set[str] | None = None
    if context_packet is not None:
        valid_source_ids = set()
        for ticket in context_packet.tickets:
            valid_source_ids.add(ticket.id)
        for doc in context_packet.documents:
            valid_source_ids.add(doc.id)

    for finding in output.findings:
        # Check confidence
        if finding.confidence not in VALID_CONFIDENCE:
            warnings.append(f"Finding '{finding.id}': invalid confidence '{finding.confidence}'")

        # Check impact
        if finding.impact not in VALID_IMPACT:
            warnings.append(f"Finding '{finding.id}': invalid impact '{finding.impact}'")

        # Check finding type
        if finding.type not in VALID_FINDING_TYPES:
            warnings.append(f"Finding '{finding.id}': invalid type '{finding.type}'")

        # Check evidence references
        if valid_source_ids is not None:
            for ev in finding.evidence:
                if ev.source_id not in valid_source_ids:
                    warnings.append(f"Finding '{finding.id}': evidence references unknown source_id '{ev.source_id}'")

    if warnings:
        logger.warning("Agent output '%s' has %d validation warnings", output.agent_id, len(warnings))
    else:
        logger.info("Agent output '%s' passed validation", output.agent_id)

    return warnings


def validate_context_packet(packet: ContextPacket) -> list[str]:
    """Validate a ContextPacket for completeness and consistency.

    Args:
        packet: The context packet to validate.

    Returns:
        List of validation warnings. Empty list means the packet is valid.
    """
    warnings: list[str] = []

    # Check required fields
    if not packet.product_name:
        warnings.append("Missing product_name")
    if not packet.product_description:
        warnings.append("Missing product_description")
    if not packet.run_id:
        warnings.append("Missing run_id")

    # Check unique ticket IDs
    ticket_ids = [t.id for t in packet.tickets]
    ticket_id_counts = Counter(ticket_ids)
    for tid, count in ticket_id_counts.items():
        if count > 1:
            warnings.append(f"Duplicate ticket ID: '{tid}' appears {count} times")

    # Check unique document IDs
    doc_ids = [d.id for d in packet.documents]
    doc_id_counts = Counter(doc_ids)
    for did, count in doc_id_counts.items():
        if count > 1:
            warnings.append(f"Duplicate document ID: '{did}' appears {count} times")

    # Warn if no customer-facing documents
    customer_types = {"note", "interview"}
    has_customer_docs = any(d.doc_type in customer_types for d in packet.documents)
    if not has_customer_docs:
        warnings.append("No customer-facing documents (notes or interviews)")

    # Warn if no metrics data
    has_metrics = any(d.doc_type == "metrics_snapshot" for d in packet.documents)
    if not has_metrics:
        warnings.append("No metrics snapshot documents")

    if warnings:
        logger.warning("Context packet has %d validation warnings", len(warnings))
    else:
        logger.info("Context packet passed validation")

    return warnings


def validate_findings_consistency(all_findings: list[Finding]) -> dict:
    """Analyze cross-agent findings for consistency and detect duplicates.

    Args:
        all_findings: Flat list of findings from all agents.

    Returns:
        Dict with counts by type/agent/confidence/impact, duplicate groups, and total.
    """
    by_type: dict[str, int] = Counter(f.type for f in all_findings)
    by_agent: dict[str, int] = Counter(f.agent_id for f in all_findings)
    by_confidence: dict[str, int] = Counter(f.confidence for f in all_findings)
    by_impact: dict[str, int] = Counter(f.impact for f in all_findings)

    # Detect duplicates across agents by title similarity
    duplicates: list[dict] = []
    seen: list[tuple[str, str, str]] = []  # (id, agent_id, title)

    for finding in all_findings:
        for prev_id, prev_agent, prev_title in seen:
            if finding.agent_id == prev_agent:
                continue  # skip same-agent comparisons
            similarity = SequenceMatcher(None, finding.title.lower(), prev_title.lower()).ratio()
            if similarity >= DUPLICATE_SIMILARITY_THRESHOLD:
                duplicates.append(
                    {
                        "finding_a": prev_id,
                        "finding_b": finding.id,
                        "title_a": prev_title,
                        "title_b": finding.title,
                        "similarity": round(similarity, 3),
                    }
                )
        seen.append((finding.id, finding.agent_id, finding.title))

    result = {
        "total_findings": len(all_findings),
        "by_type": dict(by_type),
        "by_agent": dict(by_agent),
        "by_confidence": dict(by_confidence),
        "by_impact": dict(by_impact),
        "potential_duplicates": duplicates,
    }

    if duplicates:
        logger.warning("Found %d potential cross-agent duplicate findings", len(duplicates))
    logger.info("Findings consistency: %d total, %d types, %d agents", len(all_findings), len(by_type), len(by_agent))

    return result


def generate_evidence_index(all_findings: list[Finding]) -> dict[str, list[str]]:
    """Build an index mapping each source_id to the findings that reference it.

    Useful for traceability and audit: quickly see which findings cite
    a given ticket or document.

    Args:
        all_findings: Flat list of findings from all agents.

    Returns:
        Dict mapping source_id → list of finding IDs that reference it.
    """
    index: dict[str, list[str]] = {}

    for finding in all_findings:
        for ev in finding.evidence:
            if ev.source_id not in index:
                index[ev.source_id] = []
            index[ev.source_id].append(finding.id)

    logger.info("Evidence index: %d sources referenced by %d findings", len(index), len(all_findings))
    return index
