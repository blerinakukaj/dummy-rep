"""Experiment plan generator for the AIPM pipeline.

Pulls metrics and risk findings, applies policy constraints, and calls the
LLM once to produce a fully-structured experiment plan document.
"""

import json
import logging
import re
from datetime import UTC, datetime

from aipm.core.policy import PolicyPack
from aipm.core.template_engine import load_template, render_template
from aipm.schemas.config import RunConfig
from aipm.schemas.findings import Finding

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior product manager and experimentation specialist designing a rigorous experiment.
Write in clear, quantitative language. Avoid vague statements — use specific thresholds,
percentages, and time windows wherever possible.
Reference finding IDs in brackets (e.g. [metrics-002]) for traceability.

IMPORTANT — Choose the right experiment design based on context:
- For accessibility, compliance, or legal-risk changes: Use a PHASED ROLLOUT (not A/B test).
  Withholding accessibility fixes from a control group of users with disabilities is unethical.
  Instead, design a staged rollout (e.g. 10% → 25% → 50% → 100%) with before/after measurement.
- For optional features, UX variations, or performance optimizations: Use a standard A/B test
  with control and treatment groups.
- For infrastructure or backend changes: Use a canary deployment with progressive traffic ramp.

Return a JSON object with exactly these keys (each value is a markdown string):
  hypothesis, success_metrics, guardrail_metrics, experiment_design,
  sample_size_duration, segmentation, rollback_criteria, data_collection, analysis_plan

Guidelines per section:
- hypothesis: One precise, TESTABLE sentence in the form
    "If we [change X], then [metric Y] will [increase/decrease] by [Z%] because [mechanism]."
  The hypothesis must be about user behaviour or outcomes, NOT about code compliance
  (e.g. "implementing ARIA landmarks will improve task completion" not "will improve compliance rate").
  Then 2-3 sentences of supporting rationale backed by finding IDs.
- success_metrics: Primary metric(s) with specific numeric thresholds (baseline → target),
  measurement window, and measurement method. Include secondary metrics. Use a markdown table
  with columns: Metric, Baseline, Target, Measurement Method, Window.
- guardrail_metrics: Metrics that must NOT degrade beyond stated bounds.
  List each with a specific acceptable degradation threshold (e.g. "no more than 2% decline").
  Use a markdown table with columns: Metric, Current Value, Max Acceptable Degradation, Measurement Method.
- experiment_design: For phased rollouts — describe each phase with traffic percentage, duration,
  and go/no-go criteria for advancing. For A/B tests — describe control vs. treatment,
  traffic allocation (%), targeting rules, and randomisation unit (user / session / device).
  Address ethical considerations for the chosen design.
- sample_size_duration: Estimated sample size with MDE (minimum detectable effect), power (typically 0.8),
  and significance level (typically 0.05) stated explicitly. Show the calculation or formula used.
  Estimated calendar duration given traffic volume. For phased rollouts, specify observation period per phase.
- segmentation: Which cohorts to analyse post-hoc (e.g. screen reader users vs. sighted users,
  keyboard-only vs. mouse users, new vs. returning). Explain why each segment matters
  and how users will be identified/classified.
- rollback_criteria: Concrete conditions (specific metric breaches with numeric thresholds or
  error rate thresholds) that trigger immediate experiment termination or phase reversal.
- data_collection: Specific event names, properties, and logging requirements needed
  to measure the success and guardrail metrics. Include assistive technology detection
  where relevant (screen reader usage, keyboard-only navigation patterns).
- analysis_plan: Statistical test(s) to use (and why — e.g. chi-square for proportions,
  Mann-Whitney U for non-normal distributions, paired t-test for before/after).
  When interim looks are scheduled, how multiple-comparison correction is applied
  (e.g. Bonferroni, Holm-Bonferroni), significance level, and who signs off on results.

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
            f for f in self.metrics_findings if "north-star" in f.tags or "north_star" in f.tags or f.type == "metric"
        ]

    def _extract_input_metrics(self) -> list[Finding]:
        """Return input / driver metric findings."""
        return [
            f
            for f in self.metrics_findings
            if "input-metric" in f.tags or "input_metric" in f.tags or "leading" in f.tags
        ]

    def _extract_guardrail_findings(self) -> list[Finding]:
        """Return findings explicitly tagged as guardrail metrics."""
        return [f for f in self.metrics_findings if "guardrail" in f.tags or "guardrail-metric" in f.tags]

    def _extract_experiment_risks(self) -> list[Finding]:
        """Return risk findings that are relevant to experimentation."""
        experiment_tags = {"experiment", "ab-test", "ab_test", "bias", "sample", "data"}
        return [f for f in self.risk_findings if experiment_tags & {t.lower() for t in f.tags}]

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

    def _extract_metric_baselines(self) -> str:
        """Extract verified baseline/target values from metrics findings metadata.

        Returns a formatted string of hard metric constraints that must be used
        verbatim in the experiment plan — prevents the LLM from hallucinating numbers.
        """
        metric_findings = [f for f in self.metrics_findings if f.type == "metric"]
        if not metric_findings:
            return ""

        lines = [
            "MANDATORY METRIC VALUES — Use these EXACT numbers for baselines and targets. "
            "Do NOT round, estimate, or invent different values:"
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
            self._extract_metric_baselines(),
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
        """Call the LLM using the OpenAI provider."""
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

        # Build findings-based fallbacks so no placeholder is ever left unfilled
        ns = self._format_findings(self._extract_north_star(), "North Star Metrics")
        inp = self._format_findings(self._extract_input_metrics(), "Input / Driver Metrics")
        guard = self._format_findings(self._extract_guardrail_findings(), "Guardrail Metrics")
        all_m = self._format_findings(self.metrics_findings, "All Metrics Findings")
        risks = self._format_findings(self.risk_findings[:5], "Relevant Risks")
        exp_policy = self._build_policy_constraints()

        fallbacks: dict[str, str] = {
            "hypothesis": f"_Hypothesis to be defined based on findings._\n\n{ns}",
            "success_metrics": ns or all_m,
            "guardrail_metrics": guard or "_See policy constraints._",
            "experiment_design": "_Experiment design to be defined._",
            "sample_size_duration": exp_policy,
            "segmentation": "_Segmentation to be defined._",
            "rollback_criteria": risks or "_Rollback criteria to be defined._",
            "data_collection": inp or all_m,
            "analysis_plan": "_Analysis plan to be defined._",
        }

        for key, fallback in fallbacks.items():
            if not sections.get(key):
                sections[key] = fallback

        # Render template
        template = load_template("experiment_plan_template.md")
        context = {
            "product_name": self.product_name or self.run_config.run_id,
            "run_id": self.run_config.run_id,
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            **sections,
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
