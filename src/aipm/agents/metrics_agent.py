"""Agent D — Metrics & Analytics Agent.

Defines North Star, input, and guardrail metrics, proposes an event taxonomy,
identifies instrumentation gaps, and flags metric integrity issues.
"""

import json
import logging
import re

from aipm.agents.base import BaseAgent
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert product analytics and metrics strategist. Your job is to \
define the measurement framework for a product, including metrics hierarchy, \
event taxonomy, and instrumentation gaps.

Analyze ALL the evidence below and produce structured findings.

You MUST cover each of these areas:

1. **North Star Metric**: Define ONE North Star metric for this product/feature. \
Explain why it best captures the core value delivered to users.

2. **Input Metrics** (3-5): Define the leading indicators that drive the North Star. \
For each, specify: name, definition, measurement method, and expected direction.

3. **Guardrail Metrics** (2-3): Define metrics that must NOT regress when optimizing \
the North Star. Examples: error rate, latency, support ticket volume.

4. **Event Taxonomy**: Propose a list of analytics events to instrument. \
For each event provide:
   - event_name (snake_case)
   - trigger (when the event fires)
   - properties (list of {{name, type, description}})

5. **Instrumentation Gaps**: Identify metrics that are referenced but lack baselines \
or tracking. Flag what needs to be instrumented before launch.

6. **Metric Integrity Issues**: Check for segmentation gaps, missing cohort definitions, \
vanity metrics that don't drive decisions, or conflicting metric definitions.

7. **Measurement Assumptions**: List assumptions about user behavior or data availability \
that need validation before trusting the metrics framework.

You MUST produce findings of these types:
- "metric": North Star, input metrics, and guardrail metric definitions
- "gap": instrumentation gaps and missing baselines
- "recommendation": event taxonomy additions and integrity fixes

IMPORTANT:
- Every finding must reference at least one source_id from the provided data.
- Use the exact source IDs given (document IDs like "DOC-001", ticket IDs like "NOTIFY-101").
- For metric-type findings, include structured details in the metadata field:
  - North Star: {{"metric_role": "north_star", "definition": "...", "measurement": "..."}}
  - Input: {{"metric_role": "input", "definition": "...", "drives": "north_star_name"}}
  - Guardrail: {{"metric_role": "guardrail", "definition": "...", "threshold": "..."}}
- For event taxonomy recommendations, include the event details in metadata:
  {{"event_taxonomy": [{{"event_name": "...", "trigger": "...", "properties": [...]}}]}}
- Return ONLY valid JSON matching the schema below. No markdown fences, no extra text.

{schema}
"""


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
        system = SYSTEM_PROMPT.format(schema=self._build_findings_prompt_section())
        user_prompt = self._build_user_prompt(metrics_data)

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
            "metric", "kpi", "analytics", "tracking", "event", "funnel",
            "conversion", "retention", "churn", "engagement", "dau", "mau",
            "north star", "baseline", "dashboard", "instrumentation",
        ]
        metric_tickets: list[str] = []
        for ticket in packet.tickets:
            text = f"{ticket.title} {ticket.description}".lower()
            if any(kw in text for kw in metric_keywords):
                priority = f" [Priority: {ticket.priority}]" if ticket.priority else ""
                metric_tickets.append(
                    f"- [{ticket.id}]{priority}: {ticket.title}\n  {ticket.description}"
                )

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

    def _parse_response(self, response: str) -> tuple[list[Finding], list[str]]:
        """Parse the LLM JSON response into Finding objects."""
        errors: list[str] = []

        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
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
                        source_type=ev.get("source_type", "metric"),
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
        metric_count = sum(1 for f in findings if f.type == "metric")
        gap_count = sum(1 for f in findings if f.type == "gap")
        rec_count = sum(1 for f in findings if f.type == "recommendation")
        return (
            f"Defined {metric_count} metrics (North Star, input, guardrail), "
            f"identified {gap_count} instrumentation gaps, "
            f"and proposed {rec_count} analytics recommendations."
        )
