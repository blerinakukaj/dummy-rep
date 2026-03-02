"""Agent E — UX & Requirements Agent.

Converts customer insights and metrics findings into user journeys,
functional/non-functional requirements with acceptance criteria, and
backlog candidates (epics and stories with priority, complexity, and phase).
"""

import json
import logging
import re
from pathlib import Path

from aipm.agents.base import BaseAgent
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert UX designer and product requirements engineer. Your job is to \
convert customer insights and metrics findings into actionable requirements and \
a structured product backlog.

Analyze ALL the evidence below and produce structured findings.

You MUST cover each of these areas:

1. **User Journeys**: For each key user segment or need identified in the insights, \
define a user journey covering:
   - Happy path (ideal flow)
   - Edge cases and error scenarios
   - Entry and exit points

2. **Functional Requirements**: Define clear requirements using acceptance criteria format:
   GIVEN [context] WHEN [action] THEN [expected result]
   Each requirement must have a unique story_id.

3. **Non-Functional Requirements**: Define performance, scalability, security, and \
accessibility requirements. Include measurable thresholds where possible.

4. **Backlog Candidates**: Organize requirements into epics and stories:
   - **Epic**: A high-level capability grouping related stories
   - **Story**: A specific implementable unit with:
     - Acceptance criteria (GIVEN/WHEN/THEN)
     - Priority: P0 (critical launch blocker), P1 (must-have for launch), \
P2 (should-have for V1), P3 (nice-to-have / V2+)
     - Complexity: S (small, <1 day), M (medium, 1-3 days), L (large, 3-5 days), \
XL (extra-large, 5+ days)
     - Suggested phase: MVP, V1, or V2

5. **Edge Cases & Error Scenarios**: Identify failure modes, boundary conditions, \
and error states that must be handled.

6. **UX Considerations**: Note accessibility requirements (WCAG 2.1 AA), \
responsive design needs, and key interaction patterns.

You MUST produce findings of these types:
- "requirement": each functional or non-functional requirement
- "recommendation": UX considerations, accessibility, and suggested approaches
- "gap": missing information needed to finalize requirements

For each requirement finding, include structured metadata:
{{
  "requirement_type": "functional" | "non_functional" | "ux" | "accessibility",
  "acceptance_criteria": "GIVEN ... WHEN ... THEN ...",
  "priority": "P0" | "P1" | "P2" | "P3",
  "complexity": "S" | "M" | "L" | "XL",
  "phase": "MVP" | "V1" | "V2",
  "epic_id": "<epic identifier>",
  "story_id": "<story identifier>"
}}

Also include a "backlog" key in the top-level JSON with the preliminary backlog:
{{
  "backlog": {{
    "epics": [
      {{
        "epic_id": "EPIC-001",
        "title": "...",
        "description": "...",
        "stories": [
          {{
            "story_id": "STORY-001",
            "title": "...",
            "acceptance_criteria": "GIVEN ... WHEN ... THEN ...",
            "priority": "P0",
            "complexity": "M",
            "phase": "MVP"
          }}
        ]
      }}
    ]
  }}
}}

IMPORTANT:
- Every finding must reference at least one source_id from the provided data.
- Use the exact source IDs given (finding IDs like "customer-001", document IDs like "DOC-001").
- Return ONLY valid JSON matching the schema below. No markdown fences, no extra text.

{schema}
"""


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
        system = SYSTEM_PROMPT.format(schema=self._build_findings_prompt_section())
        user_prompt = self._build_user_prompt(upstream_data)

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
                        evidence_refs = [
                            ev.get("source_id", "?") for ev in f.get("evidence", [])
                        ]
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
                        source_type=ev.get("source_type", "doc"),
                        excerpt=ev.get("excerpt", ""),
                        url=ev.get("url"),
                    ))
                raw["evidence"] = evidence

                finding = Finding.model_validate(raw)
                findings.append(finding)
            except Exception as exc:
                errors.append(f"Failed to parse finding {i + 1}: {exc}")

        # Save backlog data as separate metadata file if present
        backlog = data.get("backlog")
        if backlog:
            self._save_backlog(backlog)

        self.logger.info("Parsed %d findings (%d errors)", len(findings), len(errors))
        return findings, errors

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
