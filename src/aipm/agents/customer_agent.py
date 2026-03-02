"""Agent B — Customer Insights Agent.

Synthesizes user needs from tickets, notes, and interviews. Segments users,
frames JTBD, classifies confidence, identifies research gaps, and suggests
validation plans.
"""

import json
import logging

from aipm.agents.base import BaseAgent
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert UX researcher and customer insights analyst. Your job is to \
synthesize user needs, pain points, and opportunities from the provided product data.

Analyze ALL the evidence below and produce structured findings.

For EACH finding you MUST:
1. Synthesize user needs and pain points from tickets, customer notes, and interview data.
2. Segment users into distinct groups (e.g., power users, casual users, enterprise admins).
3. Frame a Jobs-to-be-Done (JTBD) statement for each segment: "When [situation], I want to [motivation], so I can [expected outcome]."
4. Classify confidence:
   - "validated": corroborated by 2+ independent sources
   - "directional": supported by 1 strong source
   - "speculative": inferred or assumed, needs validation
5. Identify research gaps — what do we NOT know but should?
6. For speculative insights, suggest a minimal validation plan (survey, A/B test, interview).

You MUST produce findings of these types:
- "insight": user needs, pain points, JTBD, segment analysis
- "gap": research gaps, things we don't know
- "recommendation": validation plans for speculative findings

IMPORTANT:
- Every finding must reference at least one source_id from the provided data.
- Use the exact source IDs given (ticket IDs like "NOTIFY-101", document IDs like "DOC-001").
- Return ONLY valid JSON matching the schema below. No markdown fences, no extra text.

{schema}
"""


class CustomerInsightsAgent(BaseAgent):
    """Synthesizes customer insights from tickets, notes, and interview data."""

    agent_id = "customer"
    agent_name = "Customer Insights Agent"

    async def analyze(self) -> AgentOutput:
        """Analyze customer-facing data and produce insight findings."""
        packet = self.context_packet

        # Gather customer-facing data
        customer_data = self._gather_customer_data()

        if not customer_data.strip():
            self.logger.warning("No customer-facing data found in context packet")
            output = AgentOutput(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                run_id=self.run_config.run_id,
                findings=[],
                summary="No customer-facing data available for analysis.",
                errors=["No tickets, notes, or interview data found in context packet"],
            )
            self.save_output(output)
            return output

        # Build prompts
        system = SYSTEM_PROMPT.format(schema=self._build_findings_prompt_section())
        user_prompt = self._build_user_prompt(customer_data)

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

    def _gather_customer_data(self) -> str:
        """Collect all customer-facing data from the context packet into a single text block."""
        packet = self.context_packet
        sections: list[str] = []

        # Tickets
        if packet.tickets:
            sections.append("## Tickets")
            for t in packet.tickets:
                priority = f" [Priority: {t.priority}]" if t.priority else ""
                labels = f" Labels: {', '.join(t.labels)}" if t.labels else ""
                sections.append(
                    f"- [{t.id}]{priority}{labels}: {t.title}\n  {t.description}"
                )

        # Customer notes, interviews, and NPS docs
        customer_doc_types = {"note", "interview"}
        for doc in packet.documents:
            if doc.doc_type in customer_doc_types:
                sections.append(f"## Document: {doc.title} (ID: {doc.id}, type: {doc.doc_type})")
                sections.append(doc.content)

        # Also include any doc with "customer" or "interview" or "nps" in the title
        for doc in packet.documents:
            if doc.doc_type not in customer_doc_types:
                title_lower = doc.title.lower()
                if any(kw in title_lower for kw in ("customer", "interview", "nps", "feedback", "survey")):
                    sections.append(f"## Document: {doc.title} (ID: {doc.id}, type: {doc.doc_type})")
                    sections.append(doc.content)

        return "\n\n".join(sections)

    def _build_user_prompt(self, customer_data: str) -> str:
        """Build the user prompt with product context and customer data."""
        packet = self.context_packet
        return (
            f"# Product: {packet.product_name}\n"
            f"{packet.product_description}\n\n"
            f"# Customer-Facing Data\n\n"
            f"{customer_data}\n\n"
            f"# Risk Hotspots Detected During Intake\n"
            + (
                "\n".join(f"- {h.category} ({h.severity}): {h.description}" for h in packet.risk_hotspots)
                or "None detected."
            )
            + "\n\nAnalyze all the above data and produce your findings."
        )

    def _parse_response(self, response: str) -> tuple[list[Finding], list[str]]:
        """Parse the LLM JSON response into Finding objects.

        Returns:
            Tuple of (findings list, error messages).
        """
        errors: list[str] = []

        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            # Try extracting JSON from markdown fences
            import re
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
                # Ensure required fields and correct agent_id
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
            f"Identified {insight_count} customer insights, {gap_count} research gaps, "
            f"and {rec_count} validation recommendations from "
            f"{len(self.context_packet.tickets)} tickets and "
            f"{len(self.context_packet.documents)} documents."
        )
