"""Agent B — Customer Insights Agent.

Synthesizes user needs from tickets, notes, and interviews. Segments users,
frames JTBD, classifies confidence, identifies research gaps, and suggests
validation plans.
"""

import json
import logging

from aipm.agents.base import BaseAgent
from aipm.core.prompts import SYSTEM_PROMPTS, parse_llm_findings
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)


class CustomerInsightsAgent(BaseAgent):
    """Synthesizes customer insights from tickets, notes, and interview data."""

    agent_id = "customer"
    agent_name = "Customer Insights Agent"

    async def analyze(self) -> AgentOutput:
        """Analyze customer-facing data and produce insight findings."""
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
        system = SYSTEM_PROMPTS["customer"]
        user_prompt = self._build_user_prompt(customer_data)

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
                sections.append(f"- [{t.id}]{priority}{labels}: {t.title}\n  {t.description}")

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
