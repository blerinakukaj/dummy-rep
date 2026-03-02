"""Agent C — Competitive & Positioning Agent.

Analyzes competitor data from briefs and tickets, builds a feature parity matrix,
identifies gaps and differentiation opportunities, and proposes positioning pillars.
"""

import json
import logging
import re

from aipm.agents.base import BaseAgent
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

logger = logging.getLogger(__name__)

# Keywords that signal competitive mentions in tickets
COMPETITIVE_KEYWORDS = [
    "competitor", "competing", "alternative", "switching to", "moved to",
    "compared to", "vs ", "versus", "beats", "better than", "worse than",
    "market leader", "market share", "benchmark", "parity", "feature gap",
]

SYSTEM_PROMPT = """\
You are an expert competitive intelligence analyst. Your job is to analyze \
competitor data and position the product strategically in its market.

Analyze ALL the evidence below and produce structured findings.

For EACH analysis area you MUST:
1. List identified competitors with their key strengths and weaknesses.
2. Create a feature parity matrix: for each major feature area, note whether \
our product, and each competitor, has it (yes/no/partial).
3. Identify parity gaps — must-have features competitors offer that we lack.
4. Identify differentiation opportunities — areas where we can uniquely win.
5. Propose 3-5 positioning pillars (key messaging angles for go-to-market).
6. Flag an overall competitive urgency level: critical / high / medium / low.

You MUST produce findings of these types:
- "insight": competitor analysis (strengths, weaknesses, parity matrix entries)
- "gap": parity gaps (features competitors have that we lack)
- "recommendation": positioning strategies and differentiation opportunities

IMPORTANT:
- Every finding must reference at least one source_id from the provided data.
- Use the exact source IDs given (document IDs like "DOC-001", ticket IDs like "NOTIFY-101").
- Include the competitive urgency level in a finding's metadata as {{"urgency": "<level>"}}.
- Return ONLY valid JSON matching the schema below. No markdown fences, no extra text.

{schema}
"""


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
        system = SYSTEM_PROMPT.format(schema=self._build_findings_prompt_section())
        user_prompt = self._build_user_prompt(competitive_data)

        # Call LLM
        response = await self.call_llm(system, user_prompt, response_format={"type": "json_object"})

        # Parse findings
        findings, errors = self._parse_response(response)

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
                competitive_tickets.append(
                    f"- [{ticket.id}]{priority}: {ticket.title}\n  {ticket.description}"
                )

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

    def _parse_response(self, response: str) -> tuple[list[Finding], list[str]]:
        """Parse the LLM JSON response into Finding objects."""
        errors: list[str] = []

        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            # Try extracting JSON from markdown fences
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    errors.append(f"Failed to parse LLM response as JSON: {exc}")
                    return [], errors
            else:
                errors.append(f"Failed to parse LLM response as JSON: {exc}")
                return [], errors

        findings: list[Finding] = []
        raw_findings = data.get("findings", [])

        for i, raw in enumerate(raw_findings):
            try:
                raw["agent_id"] = self.agent_id
                if "id" not in raw:
                    raw["id"] = f"{self.agent_id}-{i + 1:03d}"

                # Parse evidence items
                evidence = []
                for ev in raw.get("evidence", []):
                    evidence.append(EvidenceItem(
                        source_id=ev.get("source_id", "UNKNOWN"),
                        source_type=ev.get("source_type", "doc"),
                        excerpt=ev.get("excerpt", ""),
                        url=ev.get("url"),
                    ))
                raw["evidence"] = evidence

                finding = Finding.model_validate(raw)
                findings.append(finding)
            except Exception as exc:
                errors.append(f"Failed to parse finding {i + 1}: {exc}")

        self.logger.info("Parsed %d findings (%d errors)", len(findings), len(errors))
        return findings, errors

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
