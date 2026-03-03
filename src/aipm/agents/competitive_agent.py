"""Agent C — Competitive & Positioning Agent.

Analyzes competitor data from briefs and tickets, builds a feature parity matrix,
identifies gaps and differentiation opportunities, and proposes positioning pillars.
"""

import json
import logging

from aipm.agents.base import BaseAgent
from aipm.core.prompts import SYSTEM_PROMPTS, parse_llm_findings
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)

# Keywords that signal competitive mentions in tickets
COMPETITIVE_KEYWORDS = [
    "competitor",
    "competing",
    "alternative",
    "switching to",
    "moved to",
    "compared to",
    "vs ",
    "versus",
    "beats",
    "better than",
    "worse than",
    "market leader",
    "market share",
    "benchmark",
    "parity",
    "feature gap",
]


class CompetitiveAgent(BaseAgent):
    """Analyzes competitive landscape, parity gaps, and positioning opportunities."""

    agent_id = "competitive"
    agent_name = "Competitive & Positioning Agent"

    async def analyze(self) -> AgentOutput:
        """Analyze competitor data and produce competitive findings."""
        # Gather competitive data
        competitive_data = self._gather_competitive_data()

        if not competitive_data.strip():
            self.logger.warning("No competitive data found in context packet")
            output = AgentOutput(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                run_id=self.run_config.run_id,
                findings=[],
                summary="No competitive data available for analysis.",
                errors=["No competitor briefs or competitive mentions found in context packet"],
            )
            self.save_output(output)
            return output

        # Build prompts
        system = SYSTEM_PROMPTS["competitive"]
        user_prompt = self._build_user_prompt(competitive_data)

        # Call LLM
        response = await self.call_llm(system, user_prompt, response_format={"type": "json_object"})

        # Parse findings
        findings = parse_llm_findings(response, self.agent_id)
        errors: list[str] = []

        summary = self._extract_summary(response, findings)

        output = AgentOutput(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            run_id=self.run_config.run_id,
            findings=findings,
            summary=summary,
            errors=errors,
        )
        self.save_output(output)
        return output

    def _gather_competitive_data(self) -> str:
        """Collect all competitive data from the context packet."""
        packet = self.context_packet
        sections: list[str] = []

        # Competitor brief documents
        for doc in packet.documents:
            if doc.doc_type == "competitor_brief":
                sections.append(f"## Competitor Brief: {doc.title} (ID: {doc.id})")
                sections.append(doc.content)

        # Also include docs with competitive keywords in the title
        for doc in packet.documents:
            if doc.doc_type != "competitor_brief":
                title_lower = doc.title.lower()
                if any(kw in title_lower for kw in ("competitor", "competitive", "market", "benchmark")):
                    sections.append(f"## Document: {doc.title} (ID: {doc.id}, type: {doc.doc_type})")
                    sections.append(doc.content)

        # Scan tickets for competitive mentions
        competitive_tickets: list[str] = []
        for ticket in packet.tickets:
            text = f"{ticket.title} {ticket.description}".lower()
            if any(kw in text for kw in COMPETITIVE_KEYWORDS):
                priority = f" [Priority: {ticket.priority}]" if ticket.priority else ""
                competitive_tickets.append(f"- [{ticket.id}]{priority}: {ticket.title}\n  {ticket.description}")

        if competitive_tickets:
            sections.append("## Tickets with Competitive Mentions")
            sections.extend(competitive_tickets)

        return "\n\n".join(sections)

    def _build_user_prompt(self, competitive_data: str) -> str:
        """Build the user prompt with product context and competitive data."""
        packet = self.context_packet
        return (
            f"# Product: {packet.product_name}\n"
            f"{packet.product_description}\n\n"
            f"# Competitive Data\n\n"
            f"{competitive_data}\n\n"
            f"# Risk Hotspots Detected During Intake\n"
            + (
                "\n".join(f"- {h.category} ({h.severity}): {h.description}" for h in packet.risk_hotspots)
                or "None detected."
            )
            + "\n\nAnalyze all the above data. Identify competitors, build a feature parity matrix, "
            "find gaps and differentiation opportunities, propose positioning pillars, "
            "and flag the competitive urgency level."
        )

    def _extract_summary(self, response: str, findings: list[Finding]) -> str:
        """Extract or generate a summary from the response."""
        try:
            data = json.loads(response)
            if "summary" in data and data["summary"]:
                return data["summary"]
        except (json.JSONDecodeError, KeyError):
            pass

        # Fallback: generate from findings
        insight_count = sum(1 for f in findings if f.type == "insight")
        gap_count = sum(1 for f in findings if f.type == "gap")
        rec_count = sum(1 for f in findings if f.type == "recommendation")
        return (
            f"Identified {insight_count} competitive insights, {gap_count} parity gaps, "
            f"and {rec_count} positioning recommendations from "
            f"{len(self.context_packet.documents)} documents and "
            f"{len(self.context_packet.tickets)} tickets."
        )
