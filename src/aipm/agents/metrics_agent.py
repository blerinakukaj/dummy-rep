"""Agent D — Metrics & Analytics Agent.

Defines North Star, input, and guardrail metrics, proposes an event taxonomy,
identifies instrumentation gaps, and flags metric integrity issues.
"""

import json
import logging

from aipm.agents.base import BaseAgent
from aipm.core.prompts import SYSTEM_PROMPTS, parse_llm_findings
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)


class MetricsAgent(BaseAgent):
    """Defines the metrics framework, event taxonomy, and identifies instrumentation gaps."""

    agent_id = "metrics"
    agent_name = "Metrics & Analytics Agent"

    async def analyze(self) -> AgentOutput:
        """Analyze metrics data and produce metric/gap/recommendation findings."""
        # Gather metrics data
        metrics_data = self._gather_metrics_data()

        if not metrics_data.strip():
            self.logger.warning("No metrics data found in context packet")
            output = AgentOutput(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                run_id=self.run_config.run_id,
                findings=[],
                summary="No metrics data available for analysis.",
                errors=["No metrics snapshots or metric-related data found in context packet"],
            )
            self.save_output(output)
            return output

        # Build prompts
        system = SYSTEM_PROMPTS["metrics"]
        user_prompt = self._build_user_prompt(metrics_data)

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

    def _gather_metrics_data(self) -> str:
        """Collect all metrics-related data from the context packet."""
        packet = self.context_packet
        sections: list[str] = []

        # Metrics snapshot documents
        for doc in packet.documents:
            if doc.doc_type == "metrics_snapshot":
                sections.append(f"## Metrics Snapshot: {doc.title} (ID: {doc.id})")
                sections.append(doc.content)

        # Also include docs with metrics-related keywords in the title
        for doc in packet.documents:
            if doc.doc_type != "metrics_snapshot":
                title_lower = doc.title.lower()
                if any(kw in title_lower for kw in ("metric", "analytics", "kpi", "dashboard", "funnel", "cohort")):
                    sections.append(f"## Document: {doc.title} (ID: {doc.id}, type: {doc.doc_type})")
                    sections.append(doc.content)

        # Extract metric-related tickets
        metric_keywords = [
            "metric",
            "kpi",
            "analytics",
            "tracking",
            "event",
            "funnel",
            "conversion",
            "retention",
            "churn",
            "engagement",
            "dau",
            "mau",
            "north star",
            "baseline",
            "dashboard",
            "instrumentation",
        ]
        metric_tickets: list[str] = []
        for ticket in packet.tickets:
            text = f"{ticket.title} {ticket.description}".lower()
            if any(kw in text for kw in metric_keywords):
                priority = f" [Priority: {ticket.priority}]" if ticket.priority else ""
                metric_tickets.append(f"- [{ticket.id}]{priority}: {ticket.title}\n  {ticket.description}")

        if metric_tickets:
            sections.append("## Tickets with Metrics / Analytics Mentions")
            sections.extend(metric_tickets)

        # Include all tickets for broader context even if not metric-specific
        if not metric_tickets and packet.tickets:
            sections.append("## All Tickets (for context)")
            for t in packet.tickets:
                priority = f" [Priority: {t.priority}]" if t.priority else ""
                sections.append(f"- [{t.id}]{priority}: {t.title}\n  {t.description}")

        return "\n\n".join(sections)

    def _build_user_prompt(self, metrics_data: str) -> str:
        """Build the user prompt with product context and metrics data."""
        packet = self.context_packet
        return (
            f"# Product: {packet.product_name}\n"
            f"{packet.product_description}\n\n"
            f"# Metrics & Analytics Data\n\n"
            f"{metrics_data}\n\n"
            f"# Risk Hotspots Detected During Intake\n"
            + (
                "\n".join(f"- {h.category} ({h.severity}): {h.description}" for h in packet.risk_hotspots)
                or "None detected."
            )
            + "\n\nAnalyze all the above data. Define the North Star metric, input metrics, "
            "guardrail metrics, propose an event taxonomy, identify instrumentation gaps, "
            "check for metric integrity issues, and list measurement assumptions to validate."
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
        metric_count = sum(1 for f in findings if f.type == "metric")
        gap_count = sum(1 for f in findings if f.type == "gap")
        rec_count = sum(1 for f in findings if f.type == "recommendation")
        return (
            f"Defined {metric_count} metrics (North Star, input, guardrail), "
            f"identified {gap_count} instrumentation gaps, "
            f"and proposed {rec_count} analytics recommendations."
        )
