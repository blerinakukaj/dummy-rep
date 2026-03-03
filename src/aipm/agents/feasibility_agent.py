"""Agent F — Tech Feasibility & Delivery Agent.

Assesses technical dependencies, constraints, complexity, phased delivery plans,
build-vs-buy decisions, blocking dependencies, and technical risk for each
major requirement.
"""

import json
import logging
from pathlib import Path

from aipm.agents.base import BaseAgent
from aipm.core.prompts import SYSTEM_PROMPTS, parse_llm_findings
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)


class FeasibilityAgent(BaseAgent):
    """Assesses technical feasibility, dependencies, and proposes phased delivery."""

    agent_id = "feasibility"
    agent_name = "Tech Feasibility & Delivery Agent"

    async def analyze(self) -> AgentOutput:
        """Analyze requirements for technical feasibility and delivery planning."""
        # Load upstream requirements findings
        upstream_data = self._load_upstream_findings()

        if not upstream_data.strip():
            self.logger.warning("No upstream findings found for feasibility analysis")
            output = AgentOutput(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                run_id=self.run_config.run_id,
                findings=[],
                summary="No upstream findings available for feasibility analysis.",
                errors=["No requirements findings found in findings directory"],
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
        """Load findings from requirements_agent output file."""
        findings_dir = Path(self.run_config.output_dir) / self.run_config.run_id / "findings"
        sections: list[str] = []

        # Primary: requirements agent findings
        req_path = findings_dir / "requirements.json"
        if req_path.exists():
            try:
                data = json.loads(req_path.read_text(encoding="utf-8"))
                agent_name = data.get("agent_name", "Requirements Agent")
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
                    metadata = f.get("metadata", {})
                    evidence_refs = [ev.get("source_id", "?") for ev in f.get("evidence", [])]

                    meta_str = ""
                    if metadata:
                        meta_parts = []
                        for key in ("requirement_type", "priority", "complexity", "phase", "epic_id", "story_id"):
                            if key in metadata:
                                meta_parts.append(f"{key}={metadata[key]}")
                        if meta_parts:
                            meta_str = f"\n  Metadata: {', '.join(meta_parts)}"

                    sections.append(
                        f"- [{fid}] ({ftype}, impact={impact}): {title}\n  {desc}"
                        + (f"\n  Evidence: {', '.join(evidence_refs)}" if evidence_refs else "")
                        + meta_str
                    )
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warning("Failed to load %s: %s", req_path, exc)
        else:
            self.logger.info("Requirements file not found: %s", req_path)

        # Also load backlog if available
        backlog_path = findings_dir / "requirements_backlog.json"
        if backlog_path.exists():
            try:
                backlog = json.loads(backlog_path.read_text(encoding="utf-8"))
                sections.append("## Preliminary Backlog")
                for epic in backlog.get("epics", []):
                    sections.append(f"### Epic: {epic.get('epic_id', '?')} — {epic.get('title', 'Untitled')}")
                    sections.append(f"  {epic.get('description', '')}")
                    for story in epic.get("stories", []):
                        sections.append(
                            f"  - [{story.get('story_id', '?')}] {story.get('title', '?')} "
                            f"(P={story.get('priority', '?')}, complexity={story.get('complexity', '?')}, "
                            f"phase={story.get('phase', '?')})"
                        )
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warning("Failed to load backlog: %s", exc)

        # Include context packet data for technical context
        packet = self.context_packet
        if packet.tickets:
            sections.append("## Original Tickets (for technical context)")
            for t in packet.tickets:
                priority = f" [Priority: {t.priority}]" if t.priority else ""
                sections.append(f"- [{t.id}]{priority}: {t.title}\n  {t.description}")

        if packet.documents:
            sections.append("## Original Documents (for technical context)")
            for doc in packet.documents:
                sections.append(f"- [{doc.id}] ({doc.doc_type}): {doc.title}")
                if doc.doc_type in ("spec", "prd"):
                    sections.append(f"  {doc.content[:500]}")

        return "\n\n".join(sections)

    def _build_user_prompt(self, upstream_data: str) -> str:
        """Build the user prompt with product context and upstream findings."""
        packet = self.context_packet
        return (
            f"# Product: {packet.product_name}\n"
            f"{packet.product_description}\n\n"
            f"# Requirements & Technical Context\n\n"
            f"{upstream_data}\n\n"
            f"# Risk Hotspots Detected During Intake\n"
            + (
                "\n".join(f"- {h.category} ({h.severity}): {h.description}" for h in packet.risk_hotspots)
                or "None detected."
            )
            + "\n\nAssess the technical feasibility of all requirements above. Identify dependencies, "
            "constraints, and complexity. Propose a phased delivery plan (MVP/V1/V2), "
            "flag build-vs-buy decisions, identify blocking dependencies, "
            "and estimate technical risk for each major component."
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
        dep_count = sum(1 for f in findings if f.type == "dependency")
        risk_count = sum(1 for f in findings if f.type == "risk")
        rec_count = sum(1 for f in findings if f.type == "recommendation")
        return (
            f"Identified {dep_count} technical dependencies, "
            f"{risk_count} technical risks, "
            f"and {rec_count} delivery recommendations."
        )
