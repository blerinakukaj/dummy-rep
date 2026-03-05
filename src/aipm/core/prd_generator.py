"""Dedicated PRD generation helper for the Lead PM Agent.

Organizes findings by PRD section and calls the LLM once to produce
a complete, evidence-traced Product Requirements Document.
"""

import json
import logging
import re
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
  overview, stakeholders, goals, user_segments, in_scope, out_of_scope,
  functional_requirements, non_functional_requirements, acceptance_criteria,
  design_ux, technical_considerations, risks_mitigations, rollout_plan,
  open_questions, evidence_references

CRITICAL RULES for high-quality output:
1. **stakeholders**: Include a markdown table with columns Role, Team, and Responsibility.
   Identify product owner, engineering lead, design lead, QA lead, compliance/legal, and sponsor.
2. **goals**: Present as a markdown table with columns Goal, Baseline (current measured value),
   Target (specific numeric target), and Standard Reference (e.g. WCAG criteria, ISO standard).
   NEVER leave baselines as unknown — estimate from the findings or state the measurement method.
   Target MUST be different from Baseline — it represents the desired improvement. If the baseline
   is 1200ms, the target should be a lower value like 960ms, NOT 1200ms again.
3. **functional_requirements**: Use MoSCoW prioritization (Must Have, Should Have, Could Have).
   Present as a markdown table with columns Priority, ID, Requirement, and Standard Reference.
   Vary priorities realistically — not everything can be Must Have.
   Requirements must be internally consistent with the goals (e.g. if the goal is full compliance,
   do NOT set a lower percentage target in individual requirements).
4. **acceptance_criteria**: Each criterion must include a measurement method and specific numeric target.
   Present as a markdown table with columns Criterion, Measurement Method, and Target.
5. **risks_mitigations**: Present as a markdown table with columns Risk, Likelihood, Impact, and Mitigation.
   Reference specific laws, regulations, or standards where applicable.
6. **rollout_plan**: Present as a markdown table with columns Phase, Timeline, and Deliverables.
   Reference specific requirement IDs from functional_requirements.
7. **user_segments**: Present as a markdown table with columns Segment and Jobs To Be Done.
8. **evidence_references**: Present as a markdown table with columns Reference ID, Source, and Description.

Return ONLY valid JSON. Do NOT wrap in a root key — the top-level object
must contain exactly the 15 keys listed above."""


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
            lines.append(
                f"  - [{f.id}] ({f.type}, {f.impact}, {f.confidence}): "
                f"{f.title} — {f.description[:300]}"
            )
            if f.recommendations:
                lines.append(f"    Recommendations: {'; '.join(f.recommendations[:2])}")
        return "\n".join(lines)

    def _extract_metric_baselines(self) -> str:
        """Extract verified baseline/target values from metrics findings metadata.

        Returns a formatted string of metric constraints that must be used
        verbatim in the PRD — prevents the LLM from hallucinating numbers.
        """
        metric_findings = [f for f in self.all_findings if f.agent_id == "metrics" and f.type == "metric"]
        if not metric_findings:
            return ""

        lines = [
            "MANDATORY METRIC VALUES — Copy these EXACTLY into the PRD goals table. "
            "Do NOT round, estimate, or change any number:"
        ]
        for f in metric_findings:
            meta = f.metadata or {}
            baseline = meta.get("baseline", "unknown")
            target = meta.get("target", "unknown")
            method = meta.get("measurement_method", "")
            lines.append(f"  - {f.title}: baseline={baseline}, target={target}")
            if method:
                lines.append(f"    measurement_method: {method}")
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

        func_reqs = [f for f in requirements if f.type == "requirement"]
        nonfunc_reqs = [f for f in requirements if f.type != "requirement"]
        design_findings = [f for f in requirements if "ux" in f.tags or "design" in f.tags]
        rollout_findings = [f for f in feasibility if (f.metadata or {}).get("phase")]

        return {
            "overview": self._format_findings(intake + competitive, "Product Context & Competitive Landscape"),
            "goals": self._format_findings(metrics, "Metrics & Success Criteria"),
            "users": self._format_findings(customer, "User Segments & JTBD"),
            "scope": self._format_findings(func_reqs, "In-Scope Requirements"),
            "requirements_func": self._format_findings(func_reqs, "Functional Requirements"),
            "requirements_nonfunc": self._format_findings(nonfunc_reqs, "Non-Functional Requirements"),
            "design": self._format_findings(design_findings or requirements[:3], "Design & UX"),
            "tech": self._format_findings(feasibility, "Technical Feasibility"),
            "risks": self._format_findings(risk, "Risks & Mitigations"),
            "rollout": self._format_findings(rollout_findings or feasibility, "Rollout & Phasing"),
        }

    def _parse_llm_response(self, response: str) -> dict:
        """Parse the LLM JSON response, handling common failure modes."""
        if not response:
            logger.warning("PRD LLM returned empty response — using findings fallback")
            return {}

        # Attempt 1: direct parse
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            # Attempt 2: extract from markdown fences
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                except json.JSONDecodeError:
                    logger.warning(
                        "PRD JSON parse failed (fence extract). Response head: %.200s",
                        response,
                    )
                    return {}
            else:
                logger.warning(
                    "PRD JSON parse failed (no fences). Response head: %.200s",
                    response,
                )
                return {}

        if not isinstance(parsed, dict):
            return {}

        # Attempt 3: unwrap single root key (e.g. {"prd": {...}} or {"sections": {...}})
        if len(parsed) == 1:
            single_val = next(iter(parsed.values()))
            if isinstance(single_val, dict):
                logger.debug("PRD response had single root key — unwrapping")
                parsed = single_val

        return parsed

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
        metric_baselines = self._extract_metric_baselines()
        current_date = datetime.now(UTC).strftime("%Y-%m-%d")
        current_year = datetime.now(UTC).year

        user_prompt = (
            f"Product: {packet.product_name}\n"
            f"Description: {packet.product_description}\n\n"
            f"Today's Date: {current_date}\n"
            f"IMPORTANT: All timeline references (rollout plan, milestones) must use "
            f"{current_year} or later. Never reference past years.\n\n"
            f"Recommendation: {recommendation}\n\n"
            f"Policy Principles: {', '.join(self.policy_pack.product_principles)}\n"
            f"Non-Goals: {', '.join(self.policy_pack.non_goals)}\n\n"
            + (f"{metric_baselines}\n\n" if metric_baselines else "")
            + f"--- ORGANIZED FINDINGS ---\n\n"
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
        prd_sections = self._parse_llm_response(response)

        # Build fallbacks from already-formatted findings so no placeholder
        # is ever left unfilled if the LLM response is empty or missing a key.
        non_goals_md = (
            "\n".join(f"- {g}" for g in self.policy_pack.non_goals)
            if self.policy_pack.non_goals
            else "_Not specified in policy._"
        )
        evidence_md = (
            "\n".join(f"- [{f.id}] ({f.agent_id}): {f.title}" for f in self.all_findings[:30])
            or "_No findings available._"
        )
        stakeholders_md = (
            "| Role | Team | Responsibility |\n|------|------|----------------|\n"
            "| Product Owner | PM Team | Final approval on scope and release decisions |\n"
            "| Engineering Lead | Engineering | Implementation and technical decisions |\n"
            "| Design Lead | UX/UI | Design patterns and UX validation |\n"
            "| QA Lead | Quality Assurance | Testing and compliance validation |\n"
            "| Compliance | Legal/Compliance | Regulatory risk assessment |\n"
            "| Sponsor | Leadership | Budget approval and stakeholder communication |"
        )
        fallbacks: dict[str, str] = {
            "overview": sections["overview"],
            "stakeholders": stakeholders_md,
            "goals": sections["goals"],
            "user_segments": sections["users"],
            "in_scope": sections["scope"],
            "out_of_scope": non_goals_md,
            "functional_requirements": sections["requirements_func"],
            "non_functional_requirements": sections["requirements_nonfunc"],
            "acceptance_criteria": sections["requirements_func"],
            "design_ux": sections["design"],
            "technical_considerations": sections["tech"],
            "risks_mitigations": sections["risks"],
            "rollout_plan": sections["rollout"],
            "open_questions": "_No open questions recorded. See decision log for assumptions._",
            "evidence_references": evidence_md,
        }

        filled = 0
        for key, fallback in fallbacks.items():
            if prd_sections.get(key):
                filled += 1
            else:
                prd_sections[key] = fallback

        if filled < len(fallbacks):
            logger.warning(
                "PRD LLM response missing %d/%d section(s) — filled from findings fallback",
                len(fallbacks) - filled,
                len(fallbacks),
            )

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
            "PRD generated — %d/%d sections from LLM, %d findings referenced",
            filled,
            len(fallbacks),
            len(self.all_findings),
        )
        return rendered

    async def _call_llm(self, system: str, user: str) -> str:
        """Call the LLM and return the raw text response."""
        resp = await self.llm_client.chat.completions.create(
            model=self.run_config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=8192,
        )
        choice = resp.choices[0]
        finish = getattr(choice, "finish_reason", None)
        if finish == "length":
            logger.warning("PRD LLM response truncated (finish_reason=length) — output may be incomplete")
        content = choice.message.content
        if not content:
            logger.warning("PRD LLM returned None content (finish_reason=%s)", finish)
            return ""
        return content
