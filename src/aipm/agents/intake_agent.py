"""Agent A — Intake & Context Agent (Gatekeeper).

Ingests raw bundle data, normalizes tickets, deduplicates, detects missing info,
tags risk hotspots, and builds the ContextPacket consumed by all downstream agents.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from aipm.agents.base import BaseAgent
from aipm.core.policy import PolicyPack
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket, DocumentItem, RiskHotspot, TicketItem
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

logger = logging.getLogger(__name__)

# Keywords used to detect risk hotspots in ticket/document content
RISK_KEYWORDS: dict[str, list[str]] = {
    "privacy": ["pii", "personal data", "tracking", "gdpr", "consent", "data collection", "data retention", "opt-out"],
    "auth": ["authentication", "login", "oauth", "sso", "password", "mfa", "credentials", "session"],
    "pricing": ["pricing", "subscription", "tier", "billing", "payment", "churn", "plan", "upgrade"],
    "platform": ["api", "sdk", "integration", "migration", "backward compat", "third-party", "webhook"],
    "accessibility": ["a11y", "screen reader", "wcag", "keyboard nav", "contrast", "aria", "colorblind"],
    "security": ["encryption", "vulnerability", "injection", "xss", "csrf", "sql injection", "auth bypass"],
    "compliance": ["compliance", "regulation", "audit", "soc 2", "hipaa", "ferpa", "legal"],
}


class IntakeAgent(BaseAgent):
    """Gatekeeper agent that normalizes input data and builds the ContextPacket."""

    agent_id = "intake"
    agent_name = "Intake & Context Agent"

    def __init__(
        self,
        llm_client: object,
        run_config: RunConfig,
        policy_pack: PolicyPack,
        context_packet: ContextPacket,
        raw_bundle: dict,
    ) -> None:
        super().__init__(llm_client, run_config, policy_pack, context_packet)
        self.raw_bundle = raw_bundle

    async def analyze(self) -> AgentOutput:
        """Run the full intake pipeline and produce a ContextPacket + findings."""
        findings: list[Finding] = []
        finding_counter = 0

        # Step 1 & 2: Normalize tickets
        tickets = self._normalize_tickets()
        self.logger.info("Normalized %d tickets", len(tickets))

        # Step 3: Deduplicate tickets
        tickets, dedup_log, dedup_findings = await self._deduplicate_tickets(tickets)
        finding_counter = len(dedup_findings)
        findings.extend(dedup_findings)

        # Step 4: Detect missing info
        missing_info = self._detect_missing_info()
        for gap in missing_info:
            finding_counter += 1
            findings.append(Finding(
                id=f"intake-{finding_counter:03d}",
                agent_id=self.agent_id,
                type="gap",
                title=f"Missing data: {gap}",
                description=f"The input bundle is missing: {gap}. This may reduce the quality of downstream agent analysis.",
                impact="medium",
                confidence="validated",
                tags=["data_quality"],
            ))

        # Step 5: Tag risk hotspots
        documents = self._normalize_documents()
        risk_hotspots = self._tag_risk_hotspots(tickets, documents)
        for hotspot in risk_hotspots:
            finding_counter += 1
            findings.append(Finding(
                id=f"intake-{finding_counter:03d}",
                agent_id=self.agent_id,
                type="risk",
                title=f"Risk hotspot detected: {hotspot.category}",
                description=hotspot.description,
                impact=hotspot.severity,
                confidence="directional",
                evidence=[
                    EvidenceItem(source_id=sid, source_type="ticket", excerpt="Keyword match")
                    for sid in hotspot.source_ids
                ],
                tags=[hotspot.category],
            ))

        # Step 6: Build ContextPacket
        packet = ContextPacket(
            run_id=self.run_config.run_id,
            product_name=self.raw_bundle.get("product_name", ""),
            product_description=self.raw_bundle.get("description", ""),
            tickets=tickets,
            documents=documents,
            risk_hotspots=risk_hotspots,
            missing_info=missing_info,
            dedup_log=dedup_log,
            raw_input_type=self.raw_bundle.get("input_type", "bundle"),
        )

        # Step 7: Save context_packet.json
        self._save_context_packet(packet)

        # Generate summary via LLM
        summary = await self._generate_summary(packet)

        output = AgentOutput(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            run_id=self.run_config.run_id,
            findings=findings,
            summary=summary,
        )
        self.save_output(output)
        return output

    def get_context_packet(self) -> ContextPacket:
        """Return the saved ContextPacket after analyze() has been called."""
        packet_path = Path(self.run_config.output_dir) / self.run_config.run_id / "context_packet.json"
        raw = json.loads(packet_path.read_text(encoding="utf-8"))
        return ContextPacket.model_validate(raw)

    # ── Internal methods ─────────────────────────────────────────────

    def _normalize_tickets(self) -> list[TicketItem]:
        """Normalize raw ticket dicts into TicketItem objects.

        Handles field name differences between Jira and ADO exports.
        """
        tickets: list[TicketItem] = []
        for raw in self.raw_bundle.get("tickets", []):
            ticket = TicketItem(
                id=raw.get("id") or raw.get("work_item_id") or raw.get("key", "UNKNOWN"),
                title=raw.get("title") or raw.get("summary") or raw.get("System.Title", ""),
                description=raw.get("description") or raw.get("System.Description") or "",
                status=raw.get("status") or raw.get("System.State") or "unknown",
                priority=raw.get("priority") or raw.get("System.Priority"),
                labels=raw.get("labels") or raw.get("tags") or [],
                created_at=raw.get("created_at") or raw.get("System.CreatedDate"),
                source=raw.get("source") or self._detect_source(raw),
            )
            tickets.append(ticket)
        return tickets

    def _detect_source(self, raw_ticket: dict) -> str:
        """Infer the ticket source system from field naming conventions."""
        if any(k.startswith("System.") for k in raw_ticket):
            return "ado"
        if "key" in raw_ticket and "fields" in raw_ticket:
            return "jira"
        return "manual"

    async def _deduplicate_tickets(
        self, tickets: list[TicketItem]
    ) -> tuple[list[TicketItem], list[str], list[Finding]]:
        """Deduplicate tickets by using the LLM to detect similar titles/descriptions.

        Returns:
            Tuple of (deduplicated tickets, dedup log messages, findings about duplicates).
        """
        if len(tickets) <= 1:
            return tickets, [], []

        ticket_summaries = "\n".join(
            f"- [{t.id}] {t.title}: {t.description[:120]}" for t in tickets
        )

        system_prompt = (
            "You are a data quality analyst. Identify duplicate or near-duplicate tickets from the list below. "
            "Two tickets are duplicates if they describe the same issue or request, even with different wording.\n\n"
            "Return a JSON object: {\"duplicates\": [[\"ID_A\", \"ID_B\", \"reason\"], ...], \"unique_count\": <int>}\n"
            "If no duplicates are found, return: {\"duplicates\": [], \"unique_count\": <total>}\n"
            "Return ONLY valid JSON."
        )

        try:
            response = await self.call_llm(system_prompt, ticket_summaries, response_format={"type": "json_object"})
            result = json.loads(response)
        except Exception as exc:
            self.logger.warning("Dedup LLM call failed, skipping dedup: %s", exc)
            return tickets, [], []

        dedup_log: list[str] = []
        findings: list[Finding] = []
        ids_to_remove: set[str] = set()
        counter = 0

        for dup_group in result.get("duplicates", []):
            if len(dup_group) >= 3:
                id_a, id_b, reason = dup_group[0], dup_group[1], dup_group[2]
                ids_to_remove.add(id_b)
                dedup_log.append(f"Removed {id_b} (duplicate of {id_a}): {reason}")
                counter += 1
                findings.append(Finding(
                    id=f"intake-{counter:03d}",
                    agent_id=self.agent_id,
                    type="insight",
                    title=f"Duplicate ticket detected: {id_b}",
                    description=f"{id_b} is a duplicate of {id_a}. Reason: {reason}",
                    impact="low",
                    confidence="directional",
                    evidence=[
                        EvidenceItem(source_id=id_a, source_type="ticket", excerpt="Original ticket"),
                        EvidenceItem(source_id=id_b, source_type="ticket", excerpt="Duplicate ticket"),
                    ],
                    tags=["data_quality", "dedup"],
                ))

        filtered_tickets = [t for t in tickets if t.id not in ids_to_remove]
        if dedup_log:
            self.logger.info("Deduplicated %d tickets", len(ids_to_remove))

        return filtered_tickets, dedup_log, findings

    def _detect_missing_info(self) -> list[str]:
        """Check the raw bundle for missing or incomplete data."""
        missing: list[str] = []
        docs = self.raw_bundle.get("documents", [])
        doc_types = {d.get("doc_type") or d.get("filename", "") for d in docs}
        doc_content = " ".join(d.get("content", "") + d.get("filename", "") for d in docs).lower()

        if not self.raw_bundle.get("tickets"):
            missing.append("No tickets or work items provided")

        if not docs:
            missing.append("No supporting documents provided")

        if "customer" not in doc_content and "interview" not in doc_content and "note" not in doc_content:
            missing.append("No customer notes or interview data")

        if "metric" not in doc_content and "snapshot" not in doc_content:
            missing.append("No metrics snapshot data")

        if "competitor" not in doc_content and "competitive" not in doc_content:
            missing.append("No competitive analysis or competitor brief")

        # Check for tickets missing priority
        tickets = self.raw_bundle.get("tickets", [])
        no_priority = [t for t in tickets if not t.get("priority")]
        if no_priority:
            missing.append(f"{len(no_priority)} tickets missing priority field")

        return missing

    def _normalize_documents(self) -> list[DocumentItem]:
        """Normalize raw document dicts into DocumentItem objects."""
        documents: list[DocumentItem] = []
        for i, raw in enumerate(self.raw_bundle.get("documents", [])):
            doc = DocumentItem(
                id=raw.get("id") or f"DOC-{i + 1:03d}",
                title=raw.get("title") or raw.get("filename", f"document_{i + 1}"),
                content=raw.get("content", ""),
                doc_type=raw.get("doc_type", "note"),
                tags=raw.get("tags") or [],
            )
            documents.append(doc)
        return documents

    def _tag_risk_hotspots(
        self, tickets: list[TicketItem], documents: list[DocumentItem]
    ) -> list[RiskHotspot]:
        """Scan tickets and documents for risk keywords and tag hotspots."""
        hotspots: list[RiskHotspot] = []
        category_sources: dict[str, set[str]] = {cat: set() for cat in RISK_KEYWORDS}

        # Scan tickets
        for ticket in tickets:
            text = f"{ticket.title} {ticket.description}".lower()
            for category, keywords in RISK_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in text:
                        category_sources[category].add(ticket.id)
                        break

        # Scan documents
        for doc in documents:
            text = f"{doc.title} {doc.content}".lower()
            for category, keywords in RISK_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in text:
                        category_sources[category].add(doc.id)
                        break

        # Build hotspots for categories with matches
        for category, source_ids in category_sources.items():
            if source_ids:
                severity = "high" if len(source_ids) >= 3 else "medium" if len(source_ids) >= 2 else "low"
                hotspots.append(RiskHotspot(
                    category=category,
                    description=f"Detected {category} risk keywords in {len(source_ids)} source(s): {', '.join(sorted(source_ids))}",
                    severity=severity,
                    source_ids=sorted(source_ids),
                ))
                self.logger.info("Risk hotspot: %s (%s) — %d sources", category, severity, len(source_ids))

        return hotspots

    async def _generate_summary(self, packet: ContextPacket) -> str:
        """Use the LLM to generate a brief summary of the product context."""
        system_prompt = (
            "You are a product analyst. Summarize the product context in 2-3 sentences. "
            "Cover: what the product is, key user pain points, and the most important signals from the data. "
            "Be concise and specific."
        )

        user_prompt = (
            f"Product: {packet.product_name}\n"
            f"Description: {packet.product_description}\n"
            f"Tickets: {len(packet.tickets)} items\n"
            f"Documents: {len(packet.documents)} items\n"
            f"Risk hotspots: {', '.join(h.category for h in packet.risk_hotspots) or 'none'}\n"
            f"Missing info: {', '.join(packet.missing_info) or 'none'}\n\n"
            f"Ticket titles:\n"
            + "\n".join(f"- [{t.id}] {t.title}" for t in packet.tickets)
        )

        try:
            return await self.call_llm(system_prompt, user_prompt)
        except Exception as exc:
            self.logger.warning("Summary generation failed: %s", exc)
            return f"Intake processed {len(packet.tickets)} tickets and {len(packet.documents)} documents for {packet.product_name}."

    def _save_context_packet(self, packet: ContextPacket) -> str:
        """Save the ContextPacket to the run output directory."""
        run_dir = Path(self.run_config.output_dir) / self.run_config.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        file_path = run_dir / "context_packet.json"
        file_path.write_text(
            packet.model_dump_json(indent=2),
            encoding="utf-8",
        )
        self.logger.info("Saved context_packet.json to %s", file_path)
        return str(file_path)
