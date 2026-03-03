"""Dedicated PRD generation helper for the Lead PM Agent.

Organizes findings by PRD section and calls the LLM once to produce
a complete, evidence-traced Product Requirements Document.
"""

import json
import logging
from datetime import UTC, datetime

from aipm.core.policy import PolicyPack
from aipm.core.template_engine import load_template, render_template
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)

PRD_SYSTEM = """\
You are a senior product manager writing a Product Requirements Document (PRD).
Write in clear, professional product management language.
Reference finding IDs in brackets (e.g. [customer-003]) for traceability.
Include acceptance criteria in GIVEN/WHEN/THEN format.
Be specific — use actual data from the findings, not generic filler.

Return a JSON object with these keys (each value is a markdown string):
  overview, goals, user_segments, in_scope, out_of_scope,
  functional_requirements, non_functional_requirements, acceptance_criteria,
  design_ux, technical_considerations, risks_mitigations, rollout_plan,
  open_questions, evidence_references

Return ONLY valid JSON."""


class PRDGenerator:
    """Generates a complete PRD from pipeline findings and context."""

    def __init__(
        self,
        llm_client: object,
        context_packet: ContextPacket,
        all_findings: list[Finding],
        policy_pack: PolicyPack,
        run_config: RunConfig,
        all_agent_outputs: list[AgentOutput] | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.context_packet = context_packet
        self.all_findings = all_findings
        self.policy_pack = policy_pack
        self.run_config = run_config
        self.all_agent_outputs = all_agent_outputs or []

    def _findings_by_agent(self, agent_id: str) -> list[Finding]:
        """Return findings produced by a specific agent."""
        return [f for f in self.all_findings if f.agent_id == agent_id]

    def _format_findings(self, findings: list[Finding], label: str) -> str:
        """Format a list of findings into a bullet list for the LLM prompt."""
        if not findings:
            return f"{label}: (no findings available)"
        lines = [f"{label}:"]
        for f in findings:
            lines.append(f"  - [{f.id}] ({f.type}, {f.impact}, {f.confidence}): {f.title} — {f.description[:400]}")
            if f.recommendations:
                lines.append(f"    Recommendations: {'; '.join(f.recommendations[:3])}")
        return "\n".join(lines)

    def _organize_findings(self) -> dict[str, str]:
        """Organize all findings into PRD section buckets and format them."""
        intake = self._findings_by_agent("intake")
        customer = self._findings_by_agent("customer")
        competitive = self._findings_by_agent("competitive")
        metrics = self._findings_by_agent("metrics")
        requirements = self._findings_by_agent("requirements")
        feasibility = self._findings_by_agent("feasibility")
        risk = self._findings_by_agent("risk")

        # Separate requirements by type
        func_reqs = [f for f in requirements if f.type == "requirement"]
        nonfunc_reqs = [f for f in requirements if f.type != "requirement"]
        design_findings = [f for f in requirements if "ux" in f.tags or "design" in f.tags]
        rollout_findings = [f for f in feasibility if (f.metadata or {}).get("phase")]

        return {
            "overview": self._format_findings(intake + competitive, "Product Context & Competitive Landscape"),
            "goals": self._format_findings(metrics, "Metrics & Success Criteria (North Star, Input Metrics)"),
            "users": self._format_findings(customer, "User Segments & Jobs-to-be-Done"),
            "scope": self._format_findings(func_reqs, "In-Scope Requirements"),
            "requirements_func": self._format_findings(func_reqs, "Functional Requirements"),
            "requirements_nonfunc": self._format_findings(nonfunc_reqs, "Non-Functional Requirements"),
            "design": self._format_findings(design_findings or requirements[:3], "Design & UX Considerations"),
            "tech": self._format_findings(feasibility, "Technical Feasibility & Considerations"),
            "risks": self._format_findings(risk, "Risks & Mitigations"),
            "rollout": self._format_findings(rollout_findings or feasibility, "Rollout & Phasing"),
        }

    async def generate(self, recommendation: str = "proceed") -> str:
        """Generate a complete PRD markdown document.

        Args:
            recommendation: The overall product recommendation
                (proceed, proceed_with_mitigations, validate_first, do_not_pursue).

        Returns:
            The rendered PRD markdown string.
        """
        packet = self.context_packet
        sections = self._organize_findings()

        # Build the user prompt with all organized findings
        user_prompt = (
            f"Product: {packet.product_name}\n"
            f"Description: {packet.product_description}\n\n"
            f"Recommendation: {recommendation}\n\n"
            f"Policy Principles: {', '.join(self.policy_pack.product_principles)}\n"
            f"Non-Goals: {', '.join(self.policy_pack.non_goals)}\n\n"
            f"--- ORGANIZED FINDINGS ---\n\n"
            f"{sections['overview']}\n\n"
            f"{sections['goals']}\n\n"
            f"{sections['users']}\n\n"
            f"{sections['scope']}\n\n"
            f"{sections['requirements_func']}\n\n"
            f"{sections['requirements_nonfunc']}\n\n"
            f"{sections['design']}\n\n"
            f"{sections['tech']}\n\n"
            f"{sections['risks']}\n\n"
            f"{sections['rollout']}\n\n"
            f"--- END FINDINGS ---\n\n"
            f"Generate the PRD sections. For acceptance_criteria, use GIVEN/WHEN/THEN format. "
            f"For evidence_references, list all finding IDs used and their source agents."
        )

        response = await self._call_llm(PRD_SYSTEM, user_prompt)

        # Parse JSON response
        try:
            prd_sections = json.loads(response)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown fences
            import re

            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
            if match:
                try:
                    prd_sections = json.loads(match.group(1))
                except json.JSONDecodeError:
                    prd_sections = {}
            else:
                prd_sections = {}

        if not isinstance(prd_sections, dict):
            prd_sections = {}

        # Render into template
        template = load_template("prd_template.md")
        context = {
            "product_name": packet.product_name,
            "run_id": self.run_config.run_id,
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "recommendation": recommendation,
            **prd_sections,
        }
        rendered = render_template(template, context)

        logger.info(
            "PRD generated — %d sections filled, %d findings referenced",
            len(prd_sections),
            len(self.all_findings),
        )
        return rendered

    async def _call_llm(self, system: str, user: str) -> str:
        """Call the LLM using the appropriate provider API."""
        client_type = type(self.llm_client).__module__

        if "openai" in client_type:
            response = await self.llm_client.chat.completions.create(
                model=self.run_config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            return response.choices[0].message.content or ""

        elif "anthropic" in client_type:
            response = await self.llm_client.messages.create(
                model=self.run_config.model,
                max_tokens=4096,
                system=system + "\n\nRespond with valid JSON only.",
                messages=[{"role": "user", "content": user}],
                temperature=0.3,
            )
            return response.content[0].text if response.content else ""

        else:
            raise ValueError(f"Unsupported LLM client type: {type(self.llm_client)}")
