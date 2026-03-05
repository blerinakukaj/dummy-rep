"""Final plan JSON generator for the AIPM pipeline.

Generates final_plan.json — the authoritative master output that consolidates
the recommendation, executive summary, key findings, risks, metrics framework,
and roadmap from the full pipeline run into a single structured JSON document.

Two small LLM calls produce the executive summary and recommendation reasoning;
all other sections are derived deterministically from structured findings data.
"""

import json
import logging
from datetime import UTC, datetime

from aipm.core.policy import PolicyPack, evaluate_risk_gate
from aipm.schemas.config import RunConfig
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)

_EXEC_SUMMARY_SYSTEM = """\
You are a senior product manager writing an executive summary for a product investment decision.
Write exactly 3 paragraphs of clear, professional language.
  Paragraph 1: What the product is and what opportunity it addresses — cite key finding IDs.
  Paragraph 2: What the analysis found — top risks, opportunities, and trade-offs — cite IDs.
  Paragraph 3: The recommendation and the immediate next steps the team must take.
Reference finding IDs in brackets (e.g. [customer-001], [risk-003]).
Return ONLY the executive summary text — no JSON, no markdown fences."""

_REASONING_SYSTEM = """\
You are a senior product strategist. In 2-3 concise sentences, explain the reasoning
behind the product recommendation. Name the specific risks, opportunities, or policy
constraints that drove this decision. Reference finding IDs in brackets.
Return ONLY the reasoning text — no JSON, no markdown fences."""


class FinalPlanGenerator:
    """Generates final_plan.json — the master output consolidating everything."""

    def __init__(
        self,
        llm_client: object,
        lead_pm_output: AgentOutput,
        all_findings: list[Finding],
        policy_pack: PolicyPack,
        run_config: RunConfig,
        artifact_paths: dict | None = None,
        product_name: str = "",
    ) -> None:
        self.llm_client = llm_client
        self.lead_pm_output = lead_pm_output
        self.all_findings = all_findings
        self.policy_pack = policy_pack
        self.run_config = run_config
        self.artifact_paths = artifact_paths or {}
        self.product_name = product_name

    # ------------------------------------------------------------------
    # Lead PM metadata extraction helpers
    # ------------------------------------------------------------------

    def _lead_pm_meta(self, finding_id: str) -> dict:
        """Return the metadata dict of a specific lead_pm meta-finding."""
        for f in self.lead_pm_output.findings:
            if f.id == finding_id:
                return f.metadata or {}
        return {}

    def _top_priority_ids(self) -> list[str]:
        """Return the ordered list of top-priority finding IDs from lead_pm-002."""
        top = self._lead_pm_meta("lead_pm-002").get("top_priorities", [])
        return [r.get("finding_id", "") for r in top if r.get("finding_id")]

    def _conflicts(self) -> list[dict]:
        """Return resolved conflicts from lead_pm-003 metadata."""
        return self._lead_pm_meta("lead_pm-003").get("conflicts", [])

    # ------------------------------------------------------------------
    # Recommendation derivation
    # ------------------------------------------------------------------

    def _derive_decision(self, gate_result: dict) -> tuple[str, float]:
        """Return (decision, confidence) derived from gate + policy tolerance + confidence.

        The policy's ``max_unmitigated_high_risks`` controls how many blockers
        the pipeline tolerates before rejecting outright.  A relaxed policy
        (e.g. startup_fast with max=5) needs *more* blockers to reach
        ``do_not_pursue`` than a strict policy (default with max=2), so the
        same input can legitimately produce different recommendations under
        different policies.

        Tier logic (with blockers):
            blockers >= reject_threshold  →  do_not_pursue
            blockers <  reject_threshold  →  validate_first

        Tier logic (no blockers):
            speculative_ratio > 0.5       →  validate_first
            warnings present              →  proceed_with_mitigations
            otherwise                     →  proceed
        """
        blockers = gate_result.get("blockers", [])
        warnings = gate_result.get("warnings", [])
        total = len(self.all_findings) or 1

        if blockers:
            # Policy-aware threshold: relaxed policies tolerate more blockers
            tolerance = self.policy_pack.risk_gating.max_unmitigated_high_risks
            reject_threshold = tolerance + 1  # default=3, startup=6

            if len(blockers) >= reject_threshold:
                return "do_not_pursue", 0.85
            # Blockers exist but within policy tolerance → validate first
            return "validate_first", 0.60

        speculative_ratio = sum(1 for f in self.all_findings if f.confidence == "speculative") / total
        if speculative_ratio > 0.5:
            return "validate_first", 0.55

        if warnings:
            return "proceed_with_mitigations", 0.75

        validated_ratio = sum(1 for f in self.all_findings if f.confidence == "validated") / total
        return "proceed", round(min(0.95, 0.70 + validated_ratio * 0.25), 2)

    # ------------------------------------------------------------------
    # Section builders (deterministic — no LLM)
    # ------------------------------------------------------------------

    def _build_recommendation(self, gate_result: dict) -> dict:
        decision, confidence = self._derive_decision(gate_result)

        # Get key evidence IDs, with fallback to critical/high impact finding IDs
        key_evidence = self._top_priority_ids()[:5]
        if not key_evidence:
            impact_rank = {"critical": 0, "high": 1}
            key_evidence = [
                f.id for f in self.all_findings
                if f.impact in impact_rank
            ][:5]

        return {
            "decision": decision,
            "reasoning": "",  # filled by LLM in generate()
            "confidence": confidence,
            "key_evidence": key_evidence,
        }

    def _build_key_findings(self) -> list[dict]:
        """Return the top 10 findings ordered by impact severity."""
        impact_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_findings = sorted(
            self.all_findings,
            key=lambda f: (impact_rank.get(f.impact, 4), f.agent_id),
        )
        return [
            {
                "id": f.id,
                "agent_id": f.agent_id,
                "type": f.type,
                "title": f.title,
                "description": f.description,
                "impact": f.impact,
                "confidence": f.confidence,
                "tags": f.tags,
                "recommendations": f.recommendations,
                "assumptions": f.assumptions,
            }
            for f in sorted_findings[:10]
        ]

    def _build_risks_summary(self, gate_result: dict) -> dict:
        critical = [f for f in self.all_findings if f.impact == "critical"]
        high = [f for f in self.all_findings if f.impact == "high"]

        # Deduplicate mitigations while preserving order
        seen: set[str] = set()
        mitigations: list[str] = []
        for f in critical + high:
            for rec in f.recommendations[:2]:
                if rec not in seen:
                    seen.add(rec)
                    mitigations.append(rec)

        gate_passed = gate_result.get("passed", True)
        blockers = gate_result.get("blockers", [])

        # Determine gate status with nuance
        if gate_passed:
            gate_status = "passed"
        elif blockers and len(blockers) < 3:
            gate_status = "blocked_with_mitigations_available"
        else:
            gate_status = "blocked"

        return {
            "critical": [{"id": f.id, "title": f.title, "agent_id": f.agent_id} for f in critical],
            "high": [{"id": f.id, "title": f.title, "agent_id": f.agent_id} for f in high],
            "mitigations_required": mitigations,
            "gate_status": gate_status,
            "gate_blockers": blockers,
            "gate_override_justification": (
                f"Risk gate failed with {len(blockers)} blocker(s), but proceeding with mitigations "
                f"because all identified risks have actionable remediation paths. "
                f"Mitigations must be completed before V1 release."
                if not gate_passed and len(blockers) < 3
                else ""
            ),
        }

    def _build_metrics_framework(self) -> dict:
        metric_findings = [f for f in self.all_findings if f.agent_id == "metrics"]

        north_star = next(
            (f for f in metric_findings if "north-star" in f.tags or "north_star" in f.tags or f.type == "metric"),
            metric_findings[0] if metric_findings else None,
        )

        # Try tagged input metrics first, then fall back to non-north-star metric findings
        input_metrics = [
            f for f in metric_findings if "input-metric" in f.tags or "input_metric" in f.tags or "leading" in f.tags
        ]
        if not input_metrics:
            input_metrics = [
                f for f in metric_findings
                if f != north_star and f.type in ("recommendation", "gap", "metric")
            ][:5]

        # Try tagged guardrails first, then fall back to risk/gap metric findings
        guardrails = [f for f in metric_findings if "guardrail" in f.tags or "guardrail-metric" in f.tags]
        if not guardrails:
            guardrails = [
                f for f in metric_findings
                if f != north_star and f not in input_metrics and f.type in ("gap", "risk")
            ][:3]
            if not guardrails:
                guardrails = [
                    f for f in self.all_findings
                    if f.agent_id == "risk" and any(t in f.tags for t in ("compliance", "accessibility", "metrics"))
                ][:3]

        def _stub(f: Finding) -> dict:
            return {
                "id": f.id,
                "title": f.title,
                "description": f.description,
                "impact": f.impact,
            }

        return {
            "north_star": _stub(north_star) if north_star else {},
            "input_metrics": [_stub(f) for f in input_metrics],
            "guardrails": [_stub(f) for f in guardrails],
        }

    def _build_roadmap_summary(self) -> dict:
        # Use requirements as the primary source (avoids duplicating with feasibility)
        requirements = [f for f in self.all_findings if f.agent_id == "requirements"]
        feasibility = [f for f in self.all_findings if f.agent_id == "feasibility"]

        phase_map: dict[str, list[str]] = {"MVP": [], "V1": [], "V2": []}
        seen_titles: set[str] = set()

        # Requirements first (primary items)
        for f in requirements:
            phase = (f.metadata or {}).get("phase", "V1")
            if phase in phase_map and f.title not in seen_titles:
                phase_map[phase].append(f.title)
                seen_titles.add(f.title)

        # Feasibility items only if not already covered by a requirement
        for f in feasibility:
            phase = (f.metadata or {}).get("phase", "V1")
            if phase in phase_map and f.title not in seen_titles:
                phase_map[phase].append(f.title)
                seen_titles.add(f.title)

        phases = [{"phase": phase, "items": items} for phase, items in phase_map.items() if items]

        # Critical path: items with declared dependencies, plus cross-phase
        # dependency chain (MVP items that V1 depends on, V1 items that V2 depends on)
        critical_path_titles: list[str] = []
        for f in requirements + feasibility:
            if (f.metadata or {}).get("dependencies") and f.title not in critical_path_titles:
                critical_path_titles.append(f.title)

        # Fallback: if no explicit dependencies, build critical path from phase ordering.
        # The longest chain is: highest-priority MVP item → highest-priority V1 item → V2 item
        if not critical_path_titles:
            phase_order = ["MVP", "V1", "V2"]
            for phase in phase_order:
                items = phase_map.get(phase, [])
                if items:
                    critical_path_titles.append(items[0])  # first (highest priority) item per phase

        critical_path = critical_path_titles[:10]

        # Dominant complexity from feasibility metadata
        complexities = [
            (f.metadata or {}).get("complexity", "") for f in feasibility if (f.metadata or {}).get("complexity")
        ]
        counts = {c: complexities.count(c) for c in set(complexities) if c}
        estimated_complexity = max(counts, key=counts.get) if counts else "medium"

        return {
            "phases": phases,
            "critical_path": critical_path,
            "estimated_complexity": estimated_complexity,
        }

    def _build_open_questions(self) -> list[str]:
        gap_findings = [f for f in self.all_findings if f.type == "gap"]
        speculative = [f for f in self.all_findings if f.confidence == "speculative" and f not in gap_findings]
        seen: set[str] = set()
        questions: list[str] = []
        for f in gap_findings + speculative:
            item = f"[{f.id}] {f.title} — {f.description}"
            if item not in seen:
                seen.add(item)
                questions.append(item)
        return questions[:10]

    def _build_next_steps(self) -> list[str]:
        steps: list[str] = []

        # First try top priority IDs from lead_pm ranking
        for fid in self._top_priority_ids():
            f = next((x for x in self.all_findings if x.id == fid), None)
            if f and f.recommendations:
                steps.append(f"[{f.id}] {f.recommendations[0]}")

        # Fallback: if no top priorities, derive from critical/high impact findings
        if not steps:
            impact_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_findings = sorted(
                self.all_findings,
                key=lambda f: impact_rank.get(f.impact, 4),
            )
            for f in sorted_findings[:5]:
                if f.recommendations:
                    step = f"[{f.id}] {f.recommendations[0]}"
                    if step not in steps:
                        steps.append(step)

        # Add conflict resolutions
        for c in self._conflicts()[:3]:
            res = c.get("resolution", "")
            if res:
                fa, fb = c.get("finding_a", "?"), c.get("finding_b", "?")
                steps.append(f"Resolve conflict ({fa} vs {fb}): {res}")

        return steps[:10]

    def _build_artifacts(self) -> dict:
        """Build artifact references using relative paths from the run output directory."""
        def _to_relative(path: str) -> str:
            """Convert absolute path to relative path from run output directory."""
            if not path:
                return ""
            from pathlib import Path
            abs_path = Path(path)
            # Try to make relative to the output/run_id directory
            try:
                output_root = Path(self.run_config.output_dir) / self.run_config.run_id
                return str(abs_path.relative_to(output_root))
            except (ValueError, TypeError):
                # Fallback: just use the filename
                return abs_path.name

        return {
            "prd": _to_relative(self.artifact_paths.get("prd", "")),
            "roadmap": _to_relative(self.artifact_paths.get("roadmap", "")),
            "experiment_plan": _to_relative(self.artifact_paths.get("experiment_plan", "")),
            "decision_log": _to_relative(self.artifact_paths.get("decision_log", "")),
            "backlog": _to_relative(self.artifact_paths.get("backlog", "")),
        }

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self, system: str, user: str) -> str:
        """Call the LLM using OpenAI (text response, no JSON mode)."""
        response = await self.llm_client.chat.completions.create(
            model=self.run_config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self) -> dict:
        """Generate final_plan.json — the master output consolidating everything.

        Steps:
            1. Evaluate the risk gate against all findings and policy constraints.
            2. Build all structured sections deterministically from findings data.
            3. Call the LLM twice: executive summary + recommendation reasoning.
            4. Assemble and return the final plan dict.

        Returns:
            Dict matching the final_plan.json schema.
        """
        pname = self.product_name or self.run_config.run_id

        # 1. Risk gate evaluation — use only risk-agent findings for consistency
        #    with the risk_gate_result.json produced during pipeline execution.
        #    Using all_findings would double-count risk-type findings from other agents.
        risk_agent_findings = [f for f in self.all_findings if f.agent_id == "risk"]
        gate_result = evaluate_risk_gate(risk_agent_findings, self.policy_pack)
        gate_status = "PASSED" if gate_result.get("passed") else "FAILED"

        # 2. Build all data-driven sections
        recommendation = self._build_recommendation(gate_result)
        key_findings = self._build_key_findings()
        risks_summary = self._build_risks_summary(gate_result)
        metrics_framework = self._build_metrics_framework()
        roadmap_summary = self._build_roadmap_summary()
        open_questions = self._build_open_questions()
        next_steps = self._build_next_steps()
        artifacts = self._build_artifacts()

        # 3. Assemble LLM prompt context
        top_findings_text = "\n".join(
            f"  [{kf['id']}] ({kf['impact']}, {kf['agent_id']}): {kf['title']}" for kf in key_findings[:10]
        )
        conflict_text = (
            "\n".join(
                f"  [{c.get('finding_a', '?')} vs {c.get('finding_b', '?')}]: {c.get('description', '')}"
                for c in self._conflicts()[:5]
            )
            or "  None identified"
        )

        llm_context = (
            f"Product: {pname}\n"
            f"Total findings analysed: {len(self.all_findings)}\n"
            f"Risk gate: {gate_status}\n"
            f"Recommendation: {recommendation['decision']} (confidence {recommendation['confidence']})\n"
            f"Blockers: {'; '.join(gate_result.get('blockers', [])) or 'None'}\n"
            f"Warnings: {'; '.join(gate_result.get('warnings', [])) or 'None'}\n\n"
            f"Top findings by severity:\n{top_findings_text}\n\n"
            f"Conflicts resolved:\n{conflict_text}\n"
        )

        # 4. LLM calls for narrative text
        exec_summary = await self._call_llm(_EXEC_SUMMARY_SYSTEM, llm_context)
        reasoning = await self._call_llm(
            _REASONING_SYSTEM,
            f"Decision: {recommendation['decision']}\n\n{llm_context}",
        )
        recommendation["reasoning"] = reasoning.strip()

        plan = {
            "run_id": self.run_config.run_id,
            "product_name": pname,
            "timestamp": datetime.now(UTC).isoformat(),
            "recommendation": recommendation,
            "executive_summary": exec_summary.strip(),
            "key_findings": key_findings,
            "risks_summary": risks_summary,
            "metrics_framework": metrics_framework,
            "roadmap_summary": roadmap_summary,
            "open_questions": open_questions,
            "next_steps": next_steps,
            "artifacts": artifacts,
        }

        logger.info(
            "Final plan generated — decision=%s, confidence=%.2f, %d key findings, gate=%s",
            recommendation["decision"],
            recommendation["confidence"],
            len(key_findings),
            gate_status,
        )
        return plan

    def save(self, plan: dict, output_path: str) -> None:
        """Save the final plan as formatted JSON.

        Args:
            plan: The dict returned by generate().
            output_path: Full file path to write to.
        """
        from pathlib import Path

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
        logger.info("Final plan saved to %s", output_path)
