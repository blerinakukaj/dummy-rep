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
        """Return (decision, confidence) derived from gate + confidence distribution."""
        blockers = gate_result.get("blockers", [])
        warnings = gate_result.get("warnings", [])
        total = len(self.all_findings) or 1

        if blockers:
            return (
                "do_not_pursue" if len(blockers) >= 3 else "proceed_with_mitigations",
                0.85 if len(blockers) >= 3 else 0.70,
            )

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
        return {
            "decision": decision,
            "reasoning": "",  # filled by LLM in generate()
            "confidence": confidence,
            "key_evidence": self._top_priority_ids()[:5],
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

        return {
            "critical": [{"id": f.id, "title": f.title, "agent_id": f.agent_id} for f in critical],
            "high": [{"id": f.id, "title": f.title, "agent_id": f.agent_id} for f in high],
            "mitigations_required": mitigations,
            "gate_status": "passed" if gate_result.get("passed", True) else "blocked",
        }

    def _build_metrics_framework(self) -> dict:
        metric_findings = [f for f in self.all_findings if f.agent_id == "metrics"]

        north_star = next(
            (f for f in metric_findings if "north-star" in f.tags or "north_star" in f.tags or f.type == "metric"),
            metric_findings[0] if metric_findings else None,
        )
        input_metrics = [
            f for f in metric_findings if "input-metric" in f.tags or "input_metric" in f.tags or "leading" in f.tags
        ]
        guardrails = [f for f in metric_findings if "guardrail" in f.tags or "guardrail-metric" in f.tags]

        def _stub(f: Finding) -> dict:
            return {
                "id": f.id,
                "title": f.title,
                "description": f.description[:200],
                "impact": f.impact,
            }

        return {
            "north_star": _stub(north_star) if north_star else {},
            "input_metrics": [_stub(f) for f in input_metrics],
            "guardrails": [_stub(f) for f in guardrails],
        }

    def _build_roadmap_summary(self) -> dict:
        feasibility = [f for f in self.all_findings if f.agent_id == "feasibility"]
        requirements = [f for f in self.all_findings if f.agent_id == "requirements"]

        phase_map: dict[str, list[str]] = {"MVP": [], "V1": [], "V2": []}
        for f in feasibility + requirements:
            phase = (f.metadata or {}).get("phase", "V1")
            if phase in phase_map:
                phase_map[phase].append(f.title)

        phases = [{"phase": phase, "items": items} for phase, items in phase_map.items() if items]

        # Critical path: items with declared dependencies
        critical_path = [f.title for f in feasibility + requirements if (f.metadata or {}).get("dependencies")][:10]

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
            item = f"[{f.id}] {f.title} — {f.description[:150]}"
            if item not in seen:
                seen.add(item)
                questions.append(item)
        return questions[:10]

    def _build_next_steps(self) -> list[str]:
        steps: list[str] = []
        for fid in self._top_priority_ids():
            f = next((x for x in self.all_findings if x.id == fid), None)
            if f and f.recommendations:
                steps.append(f"[{f.id}] {f.recommendations[0]}")
        for c in self._conflicts()[:3]:
            res = c.get("resolution", "")
            if res:
                fa, fb = c.get("finding_a", "?"), c.get("finding_b", "?")
                steps.append(f"Resolve conflict ({fa} vs {fb}): {res}")
        return steps[:10]

    def _build_artifacts(self) -> dict:
        return {
            "prd": self.artifact_paths.get("prd", ""),
            "roadmap": self.artifact_paths.get("roadmap", ""),
            "experiment_plan": self.artifact_paths.get("experiment_plan", ""),
            "decision_log": self.artifact_paths.get("decision_log", ""),
            "backlog": self.artifact_paths.get("backlog", ""),
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

        # 1. Risk gate evaluation
        gate_result = evaluate_risk_gate(self.all_findings, self.policy_pack)
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
