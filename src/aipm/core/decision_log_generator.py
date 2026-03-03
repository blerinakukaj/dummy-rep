"""Decision log generator for the AIPM pipeline.

Builds a fully-auditable decision_log.md from structured deduplication
decisions, conflict resolutions, risk-gate evaluations, and policy pack
metadata — with no LLM call required.
"""

import logging
from datetime import UTC, datetime

from aipm.core.policy import PolicyPack
from aipm.core.template_engine import load_template, render_template

logger = logging.getLogger(__name__)

_TODAY = lambda: datetime.now(UTC).strftime("%Y-%m-%d")  # noqa: E731


class DecisionLogGenerator:
    """Generates decision_log.md from pipeline decision data."""

    def __init__(
        self,
        dedup_decisions: list[dict],
        conflict_resolutions: list[dict],
        risk_gate_results: dict | list[dict],
        policy_pack: PolicyPack,
        product_name: str = "",
        run_id: str = "",
    ) -> None:
        self.dedup_decisions = dedup_decisions
        self.conflict_resolutions = conflict_resolutions
        # Normalise: accept a single gate-result dict or a list of them
        if isinstance(risk_gate_results, dict):
            self.risk_gate_results: list[dict] = [risk_gate_results]
        else:
            self.risk_gate_results = list(risk_gate_results)
        self.policy_pack = policy_pack
        self.product_name = product_name
        self.run_id = run_id

    # ------------------------------------------------------------------
    # Summary table
    # ------------------------------------------------------------------

    def _build_decision_rows(self) -> str:
        """Build the markdown table rows that appear at the top of the log."""
        rows: list[str] = []
        idx = 1
        today = _TODAY()

        for d in self.dedup_decisions:
            kept = d.get("kept_id", "—")
            merged = ", ".join(d.get("merged_ids", [])) or "—"
            rows.append(
                f"| {idx} | Merge {merged} → {kept} "
                f"| {d.get('reason', '—')} "
                f"| Retain all duplicates; discard lower-confidence copy "
                f"| {d.get('confidence', '—')} | Accepted | {today} |"
            )
            idx += 1

        for c in self.conflict_resolutions:
            rows.append(
                f"| {idx} | Conflict: {c.get('what_conflicted', '—')} "
                f"| {c.get('resolution', '—')} "
                f"| {c.get('alternatives', 'Accept either finding')} "
                f"| {c.get('confidence', '—')} | Accepted | {today} |"
            )
            idx += 1

        for rg in self.risk_gate_results:
            label = rg.get("label", "Risk Gate Evaluation")
            passed = rg.get("passed", False)
            blockers = len(rg.get("blockers", []))
            warnings = len(rg.get("warnings", []))
            rows.append(
                f"| {idx} | {label} "
                f"| {blockers} blocker(s), {warnings} warning(s) "
                f"| Proceed with mitigations; halt pipeline entirely "
                f"| validated | {'Passed' if passed else 'Blocked'} | {today} |"
            )
            idx += 1

        if not rows:
            return "| — | No decisions recorded | — | — | — | — | — |"
        return "\n".join(rows)

    # ------------------------------------------------------------------
    # Detailed sections
    # ------------------------------------------------------------------

    def _section_dedup(self) -> str:
        lines = ["## 1. Deduplication Decisions\n"]
        if not self.dedup_decisions:
            lines.append("_No deduplication decisions were made during this run._\n")
            return "\n".join(lines)

        for d in self.dedup_decisions:
            kept = d.get("kept_id", "—")
            title = d.get("finding_title", kept)
            merged = ", ".join(d.get("merged_ids", [])) or "—"
            lines.append(f"### [{kept}] kept — {title}\n")
            lines.append(f"- **Merged / removed IDs:** {merged}")
            lines.append(f"- **Reason:** {d.get('reason', '—')}")
            lines.append(f"- **Version kept rationale:** {d.get('kept_rationale', 'Highest confidence score')}")
            lines.append(f"- **Confidence:** {d.get('confidence', '—')}")
            if d.get("notes"):
                lines.append(f"- **Notes:** {d['notes']}")
            lines.append("")

        return "\n".join(lines)

    def _section_conflicts(self) -> str:
        lines = ["## 2. Conflict Resolutions\n"]
        if not self.conflict_resolutions:
            lines.append("_No inter-finding conflicts required resolution._\n")
            return "\n".join(lines)

        for c in self.conflict_resolutions:
            cid = c.get("id", "conflict")
            lines.append(f"### {cid}: {c.get('what_conflicted', '—')}\n")
            lines.append(f"- **Finding A:** {c.get('finding_a', '—')}")
            lines.append(f"- **Finding B:** {c.get('finding_b', '—')}")
            lines.append(f"- **Nature of conflict:** {c.get('what_conflicted', '—')}")
            lines.append(f"- **Resolution:** {c.get('resolution', '—')}")
            if c.get("resolution_rule"):
                lines.append(f"- **Policy / rule applied:** `{c['resolution_rule']}`")
            if c.get("evidence_weight"):
                lines.append(f"- **Evidence weight:** {c['evidence_weight']}")
            if c.get("tradeoffs"):
                lines.append(f"- **Tradeoffs accepted:** {c['tradeoffs']}")
            lines.append("")

        return "\n".join(lines)

    def _section_risk_gate(self) -> str:
        lines = ["## 3. Risk Gate Decisions\n"]

        for rg in self.risk_gate_results:
            label = rg.get("label", "Risk Gate")
            passed = rg.get("passed", False)
            lines.append(f"### {label}: {'PASSED' if passed else 'FAILED'}\n")

            blockers = rg.get("blockers", [])
            if blockers:
                lines.append("**Blockers triggered:**")
                for b in blockers:
                    lines.append(f"  - {b}")
                lines.append("")

            warnings = rg.get("warnings", [])
            if warnings:
                lines.append("**Warnings issued:**")
                for w in warnings:
                    lines.append(f"  - {w}")
                lines.append("")

            if not blockers and not warnings:
                lines.append("_No blockers or warnings — gate cleared cleanly._\n")

        rg_policy = self.policy_pack.risk_gating
        lines.append("**Policy rules consulted:**\n")
        lines.append(f"  - `block_on_critical_privacy`: {rg_policy.block_on_critical_privacy}")
        lines.append(f"  - `block_on_critical_security`: {rg_policy.block_on_critical_security}")
        lines.append(f"  - `require_legal_review_for_pii`: {rg_policy.require_legal_review_for_pii}")
        lines.append(f"  - `max_unmitigated_high_risks`: {rg_policy.max_unmitigated_high_risks}")
        for field, val in (rg_policy.model_extra or {}).items():
            lines.append(f"  - `{field}`: {val}")
        lines.append("")

        return "\n".join(lines)

    def _section_prioritization(self) -> str:
        lines = ["## 4. Prioritization Decisions\n"]

        # Top priorities: derive from what was kept in dedup and why
        kept = [
            {
                "id": d.get("kept_id", "—"),
                "reason": d.get("reason", "—"),
                "confidence": d.get("confidence", "—"),
            }
            for d in self.dedup_decisions
        ]

        if not kept and not self.conflict_resolutions:
            lines.append("_Insufficient decision data to derive prioritization ranking._\n")
            return "\n".join(lines)

        if kept:
            lines.append("### Top-Ranked Findings (from deduplication outcomes)\n")
            lines.append("| Rank | Finding ID | Rationale | Confidence |")
            lines.append("|------|------------|-----------|------------|")
            for rank, p in enumerate(kept[:5], 1):
                lines.append(f"| {rank} | {p['id']} | {p['reason']} | {p['confidence']} |")
            lines.append("")

        deprioritized = [
            f"[{mid}] — superseded by [{d.get('kept_id', '—')}]: {d.get('reason', '—')}"
            for d in self.dedup_decisions
            for mid in d.get("merged_ids", [])
        ]
        if deprioritized:
            lines.append("### Deprioritized / Removed Findings\n")
            for item in deprioritized:
                lines.append(f"- {item}")
            lines.append("")

        return "\n".join(lines)

    def _section_assumptions(self) -> str:
        lines = ["## 5. Assumption Register\n"]
        assumptions: list[dict] = []

        for d in self.dedup_decisions:
            for assumption in d.get("assumptions", []):
                conf = d.get("confidence", "speculative")
                assumptions.append(
                    {
                        "source": d.get("kept_id", "dedup"),
                        "assumption": assumption,
                        "confidence": conf,
                        "needs_validation": conf in ("speculative", "directional"),
                    }
                )

        for c in self.conflict_resolutions:
            for assumption in c.get("assumptions", []):
                conf = c.get("confidence", "speculative")
                assumptions.append(
                    {
                        "source": c.get("id", "conflict"),
                        "assumption": assumption,
                        "confidence": conf,
                        "needs_validation": True,
                    }
                )

        if not assumptions:
            lines.append("_No explicit assumptions were recorded in the decision data._")
            lines.append("Review individual finding `assumptions` fields in the full findings output.\n")
            return "\n".join(lines)

        lines.append("| Source | Assumption | Confidence | Needs Validation? |")
        lines.append("|--------|------------|------------|------------------|")
        for a in assumptions:
            needs = "Yes" if a["needs_validation"] else "No"
            lines.append(f"| {a['source']} | {a['assumption']} | {a['confidence']} | {needs} |")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        product_name: str = "",
        run_id: str = "",
    ) -> str:
        """Generate decision_log.md documenting all decisions made during the pipeline run.

        Steps:
            1. Build the summary table from dedup, conflict, and risk-gate decisions.
            2. Render each detailed section (dedup, conflicts, risk gate,
               prioritization, assumption register).
            3. Inject into decision_log_template.md.

        Args:
            product_name: Optional override for the product name header.
            run_id: Optional override for the run ID header.

        Returns:
            Rendered markdown string of the decision log.
        """
        pname = product_name or self.product_name
        rid = run_id or self.run_id

        decision_rows = self._build_decision_rows()
        decision_details = "\n\n".join(
            [
                self._section_dedup(),
                self._section_conflicts(),
                self._section_risk_gate(),
                self._section_prioritization(),
                self._section_assumptions(),
            ]
        )

        template = load_template("decision_log_template.md")
        context = {
            "product_name": pname or rid or "AIPM Run",
            "run_id": rid,
            "date": _TODAY(),
            "decision_rows": decision_rows,
            "decision_details": decision_details,
        }
        rendered = render_template(template, context)

        logger.info(
            "Decision log generated — %d dedup, %d conflict, %d risk-gate decision(s)",
            len(self.dedup_decisions),
            len(self.conflict_resolutions),
            len(self.risk_gate_results),
        )
        return rendered

    def save(self, content: str, output_path: str) -> None:
        """Write the rendered decision log to disk.

        Args:
            content: The rendered markdown string from generate().
            output_path: Full file path to write to.
        """
        from pathlib import Path

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(content, encoding="utf-8")
        logger.info("Decision log saved to %s", output_path)
