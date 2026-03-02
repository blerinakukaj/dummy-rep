"""Experiment plan generator for the AIPM pipeline.

Pulls metrics and risk findings, applies policy constraints, and calls the
LLM once to produce a fully-structured experiment plan document.
"""

import json
import logging
import re
from datetime import datetime, timezone

from aipm.core.policy import PolicyPack
from aipm.core.template_engine import load_template, render_template
from aipm.schemas.config import RunConfig
from aipm.schemas.findings import Finding

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior product manager and experimentation specialist designing a rigorous A/B test.
Write in clear, quantitative language. Avoid vague statements — use specific thresholds,
percentages, and time windows wherever possible.
Reference finding IDs in brackets (e.g. [metrics-002]) for traceability.

Return a JSON object with exactly these keys (each value is a markdown string):
  hypothesis, success_metrics, guardrail_metrics, experiment_design,
  sample_size_duration, segmentation, rollback_criteria, data_collection, analysis_plan

Guidelines per section:
- hypothesis: One precise sentence in the form
    "If we [change X], then [metric Y] will [increase/decrease] by [Z%] because [mechanism]."
  Then 2-3 sentences of supporting rationale backed by finding IDs.
- success_metrics: Primary metric(s) with specific numeric thresholds and measurement window.
  Include secondary metrics. Use a markdown table.
- guardrail_metrics: Metrics that must NOT degrade beyond stated bounds.
  List each with acceptable degradation threshold. Use a markdown table.
- experiment_design: Control vs. treatment description, traffic allocation (%),
  targeting rules (which users), and randomisation unit (user / session / device).
- sample_size_duration: Estimated sample size per arm with MDE, power, and significance
  assumptions stated explicitly. Estimated calendar duration given traffic volume.
- segmentation: Which cohorts to analyse post-hoc (e.g. new vs returning, mobile vs desktop).
  Explain why each segment matters.
- rollback_criteria: Concrete conditions (metric breaches or error thresholds) that
  trigger immediate experiment termination.
- data_collection: Specific event names, properties, and logging requirements needed
  to measure the success and guardrail metrics.
- analysis_plan: Statistical test(s) to use, when interim looks are scheduled,
  how multiple-comparison correction is applied, and who signs off on results.

Return ONLY valid JSON — no prose outside the JSON object."""


class ExperimentPlanGenerator:
    """Generates experiment_plan.md from metrics + risk findings and policy constraints."""

    def __init__(
        self,
        llm_client: object,
        metrics_findings: list[Finding],
        risk_findings: list[Finding],
        policy_pack: PolicyPack,
        run_config: RunConfig,
        product_name: str = "",
    ) -> None:
        self.llm_client = llm_client
        self.metrics_findings = metrics_findings
        self.risk_findings = risk_findings
        self.policy_pack = policy_pack
        self.run_config = run_config
        self.product_name = product_name

    # ------------------------------------------------------------------
    # Finding extraction helpers
    # ------------------------------------------------------------------

    def _extract_north_star(self) -> list[Finding]:
        """Return findings tagged as north-star or with type 'metric'."""
        return [
            f for f in self.metrics_findings
            if "north-star" in f.tags or "north_star" in f.tags or f.type == "metric"
        ]

    def _extract_input_metrics(self) -> list[Finding]:
        """Return input / driver metric findings."""
        return [
            f for f in self.metrics_findings
            if "input-metric" in f.tags
            or "input_metric" in f.tags
            or "leading" in f.tags
        ]

    def _extract_guardrail_findings(self) -> list[Finding]:
        """Return findings explicitly tagged as guardrail metrics."""
        return [
            f for f in self.metrics_findings
            if "guardrail" in f.tags or "guardrail-metric" in f.tags
        ]

    def _extract_experiment_risks(self) -> list[Finding]:
        """Return risk findings that are relevant to experimentation."""
        experiment_tags = {"experiment", "ab-test", "ab_test", "bias", "sample", "data"}
        return [
            f for f in self.risk_findings
            if experiment_tags & {t.lower() for t in f.tags}
        ]

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_findings(self, findings: list[Finding], label: str) -> str:
        """Format a finding list as a labelled bullet list for the LLM prompt."""
        if not findings:
            return f"{label}: (none identified)"
        lines = [f"{label}:"]
        for f in findings:
            lines.append(
                f"  - [{f.id}] ({f.type}, impact={f.impact}, confidence={f.confidence}): "
                f"{f.title} — {f.description[:400]}"
            )
            if f.recommendations:
                lines.append(f"    Recommendations: {'; '.join(f.recommendations[:2])}")
        return "\n".join(lines)

    def _build_policy_constraints(self) -> str:
        """Render experiment policy constraints as a bullet list."""
        exp = self.policy_pack.experimentation
        lines = [
            "Experiment Policy Constraints (must be respected in your output):",
            f"  - min_sample_size per arm: {exp.min_sample_size}",
            f"  - max_experiment_duration_days: {exp.max_experiment_duration_days}",
            f"  - require_guardrail_metrics: {exp.require_guardrail_metrics}",
            f"  - success_criteria_required: {exp.success_criteria_required}",
        ]
        # Include any extra fields (e.g. from strict / enterprise policy)
        for field, val in (exp.model_extra or {}).items():
            lines.append(f"  - {field}: {val}")
        return "\n".join(lines)

    def _build_user_prompt(self) -> str:
        """Assemble the full user prompt from findings and policy."""
        north_star = self._extract_north_star()
        input_metrics = self._extract_input_metrics()
        guardrails = self._extract_guardrail_findings()
        # Fall back: if no tagged findings, use all metrics findings split evenly
        if not north_star and not input_metrics:
            mid = max(1, len(self.metrics_findings) // 2)
            north_star = self.metrics_findings[:mid]
            input_metrics = self.metrics_findings[mid:]
        experiment_risks = self._extract_experiment_risks()
        all_risks = experiment_risks or self.risk_findings[:5]

        sections = [
            f"Product: {self.product_name or self.run_config.run_id}",
            "",
            self._format_findings(north_star, "North Star Metrics"),
            "",
            self._format_findings(input_metrics, "Input / Driver Metrics"),
            "",
            self._format_findings(guardrails, "Identified Guardrail Metrics"),
            "",
            self._format_findings(self.metrics_findings, "All Metrics Findings"),
            "",
            self._format_findings(all_risks, "Relevant Risks Affecting Experimentation"),
            "",
            self._build_policy_constraints(),
            "",
            (
                "Generate a complete experiment plan. Every numeric threshold in "
                "success_metrics and guardrail_metrics must be justified by the findings above. "
                "sample_size_duration must respect the min_sample_size and max_experiment_duration_days "
                "from the policy constraints. data_collection must list the exact event names "
                "required to measure each success and guardrail metric."
            ),
        ]
        return "\n".join(sections)

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self, system: str, user: str) -> str:
        """Call the LLM using the configured provider."""
        client_module = type(self.llm_client).__module__

        if "openai" in client_module:
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

        elif "anthropic" in client_module:
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self) -> str:
        """Generate experiment_plan.md using the template and findings.

        Steps:
            1. Extract North Star, input metrics, and guardrails from metrics findings.
            2. Extract relevant risks that affect experimentation.
            3. Apply policy constraints (min_sample_size, max_duration, etc.).
            4. Call LLM to populate all template sections in one request.
            5. Render into experiment_plan_template.md.

        Returns:
            Rendered markdown string of the experiment plan.
        """
        user_prompt = self._build_user_prompt()
        raw_response = await self._call_llm(_SYSTEM_PROMPT, user_prompt)

        # Parse JSON response
        sections: dict = {}
        try:
            sections = json.loads(raw_response)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_response, re.DOTALL)
            if match:
                try:
                    sections = json.loads(match.group(1))
                except json.JSONDecodeError:
                    sections = {}

        if not isinstance(sections, dict):
            sections = {}

        # Render template
        template = load_template("experiment_plan_template.md")
        context = {
            "product_name": self.product_name or self.run_config.run_id,
            "run_id": self.run_config.run_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "hypothesis": sections.get("hypothesis", ""),
            "success_metrics": sections.get("success_metrics", ""),
            "guardrail_metrics": sections.get("guardrail_metrics", ""),
            "experiment_design": sections.get("experiment_design", ""),
            "sample_size_duration": sections.get("sample_size_duration", ""),
            "segmentation": sections.get("segmentation", ""),
            "rollback_criteria": sections.get("rollback_criteria", ""),
            "data_collection": sections.get("data_collection", ""),
            "analysis_plan": sections.get("analysis_plan", ""),
        }
        rendered = render_template(template, context)

        logger.info(
            "Experiment plan generated — %d sections filled from %d metrics + %d risk findings",
            sum(1 for v in sections.values() if v),
            len(self.metrics_findings),
            len(self.risk_findings),
        )
        return rendered

    def save(self, content: str, output_path: str) -> None:
        """Write the rendered experiment plan to disk.

        Args:
            content: The rendered markdown string from generate().
            output_path: Full file path to write to.
        """
        from pathlib import Path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(content, encoding="utf-8")
        logger.info("Experiment plan saved to %s", output_path)
