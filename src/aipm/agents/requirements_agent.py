"""Agent E — UX & Requirements Agent.

Converts customer insights and metrics findings into user journeys,
functional/non-functional requirements with acceptance criteria, and
backlog candidates (epics and stories with priority, complexity, and phase).
"""

import json
import logging
from pathlib import Path

from aipm.agents.base import BaseAgent
from aipm.core.prompts import SYSTEM_PROMPTS, parse_llm_findings
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)


class RequirementsAgent(BaseAgent):
    """Converts insights into user journeys, requirements, and backlog candidates."""

    agent_id = "requirements"
    agent_name = "UX & Requirements Agent"

    async def analyze(self) -> AgentOutput:
        """Analyze upstream findings and produce requirement findings with backlog."""
        # Load upstream agent findings
        upstream_data = self._load_upstream_findings()

        if not upstream_data.strip():
            self.logger.warning("No upstream findings found for requirements analysis")
            output = AgentOutput(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                run_id=self.run_config.run_id,
                findings=[],
                summary="No upstream findings available for requirements analysis.",
                errors=["No customer or metrics findings found in findings directory"],
            )
            self.save_output(output)
            return output

        # Build prompts
        system = SYSTEM_PROMPTS[self.agent_id]
        user_prompt = self._build_user_prompt(upstream_data)

        # Call LLM
        response = await self.call_llm(system, user_prompt, response_format={"type": "json_object"})

        # Parse findings
        findings = parse_llm_findings(response, self.agent_id)
        errors: list[str] = []

        # Extract and save backlog data separately (parse_llm_findings only handles findings)
        try:
            resp_data = json.loads(response)
            backlog = resp_data.get("backlog")
            if backlog:
                self._save_backlog(backlog)
        except (json.JSONDecodeError, OSError):
            pass

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

    def _load_upstream_findings(self) -> str:
        """Load findings from customer_agent and metrics_agent output files."""
        findings_dir = Path(self.run_config.output_dir) / self.run_config.run_id / "findings"
        sections: list[str] = []

        for agent_file in ("customer.json", "metrics.json"):
            file_path = findings_dir / agent_file
            if file_path.exists():
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    agent_name = data.get("agent_name", agent_file)
                    findings = data.get("findings", [])
                    summary = data.get("summary", "")

                    sections.append(f"## Findings from {agent_name}")
                    if summary:
                        sections.append(f"Summary: {summary}")

                    for f in findings:
                        fid = f.get("id", "?")
                        ftype = f.get("type", "?")
                        title = f.get("title", "Untitled")
                        desc = f.get("description", "")
                        impact = f.get("impact", "?")
                        confidence = f.get("confidence", "?")
                        evidence_refs = [ev.get("source_id", "?") for ev in f.get("evidence", [])]
                        sections.append(
                            f"- [{fid}] ({ftype}, impact={impact}, confidence={confidence}): "
                            f"{title}\n  {desc}"
                            + (f"\n  Evidence: {', '.join(evidence_refs)}" if evidence_refs else "")
                        )
                except (json.JSONDecodeError, OSError) as exc:
                    self.logger.warning("Failed to load %s: %s", file_path, exc)
            else:
                self.logger.info("Upstream file not found: %s", file_path)

        # Also include context packet data for additional context
        packet = self.context_packet
        if packet.tickets:
            sections.append("## Original Tickets (for reference)")
            for t in packet.tickets:
                priority = f" [Priority: {t.priority}]" if t.priority else ""
                sections.append(f"- [{t.id}]{priority}: {t.title}\n  {t.description}")

        if packet.documents:
            sections.append("## Original Documents (for reference)")
            for doc in packet.documents:
                sections.append(f"- [{doc.id}] ({doc.doc_type}): {doc.title}")

        return "\n\n".join(sections)

    def _build_user_prompt(self, upstream_data: str) -> str:
        """Build the user prompt with product context and upstream findings."""
        packet = self.context_packet
        return (
            f"# Product: {packet.product_name}\n"
            f"{packet.product_description}\n\n"
            f"# Upstream Agent Findings & Context\n\n"
            f"{upstream_data}\n\n"
            f"# Risk Hotspots Detected During Intake\n"
            + (
                "\n".join(f"- {h.category} ({h.severity}): {h.description}" for h in packet.risk_hotspots)
                or "None detected."
            )
            + "\n\nConvert the above insights into user journeys, functional and non-functional "
            "requirements with GIVEN/WHEN/THEN acceptance criteria, backlog candidates "
            "(epics and stories with priority, complexity, and phase), edge cases, "
            "and UX/accessibility considerations."
        )

    def _save_backlog(self, backlog: dict) -> None:
        """Save the preliminary backlog as a separate JSON file."""
        findings_dir = Path(self.run_config.output_dir) / self.run_config.run_id / "findings"
        findings_dir.mkdir(parents=True, exist_ok=True)

        backlog_path = findings_dir / "requirements_backlog.json"
        backlog_path.write_text(
            json.dumps(backlog, indent=2),
            encoding="utf-8",
        )
        self.logger.info("Saved preliminary backlog to %s", backlog_path)

    def _extract_summary(self, response: str, findings: list[Finding]) -> str:
        """Extract or generate a summary from the response."""
        try:
            data = json.loads(response)
            if "summary" in data and data["summary"]:
                return data["summary"]
        except (json.JSONDecodeError, KeyError):
            pass

        # Fallback: generate from findings
        req_count = sum(1 for f in findings if f.type == "requirement")
        gap_count = sum(1 for f in findings if f.type == "gap")
        rec_count = sum(1 for f in findings if f.type == "recommendation")
        return (
            f"Defined {req_count} requirements with acceptance criteria, "
            f"identified {gap_count} information gaps, "
            f"and proposed {rec_count} UX/accessibility recommendations."
        )
