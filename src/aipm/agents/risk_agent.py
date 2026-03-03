"""Agent G — Risk/Privacy/Compliance Guardrails Agent.

Scans all upstream findings for privacy, security, compliance, and accessibility
risks. Applies policy-driven gating rules and flags blockers.
"""

import json
import logging
from pathlib import Path

from aipm.agents.base import BaseAgent
from aipm.core.policy import evaluate_risk_gate
from aipm.core.prompts import SYSTEM_PROMPTS, parse_llm_findings
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)


class RiskAgent(BaseAgent):
    """Scans all findings for privacy, security, compliance, and accessibility risks."""

    agent_id = "risk"
    agent_name = "Risk/Privacy/Compliance Guardrails Agent"

    async def analyze(self) -> AgentOutput:
        """Scan upstream findings for risks and apply policy gating."""
        # Load all upstream findings
        upstream_data = self._load_all_upstream_findings()

        if not upstream_data.strip():
            self.logger.warning("No upstream findings found for risk analysis")
            output = AgentOutput(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                run_id=self.run_config.run_id,
                findings=[],
                summary="No upstream findings available for risk analysis.",
                errors=["No agent findings found in findings directory"],
            )
            self.save_output(output)
            return output

        # Build prompts with policy context
        system = self._build_system_prompt()
        user_prompt = self._build_user_prompt(upstream_data)

        # Call LLM
        response = await self.call_llm(system, user_prompt, response_format={"type": "json_object"})

        # Parse findings
        findings = parse_llm_findings(response, self.agent_id)
        errors: list[str] = []

        # Post-process: ensure all findings are type "risk" and have category tags
        for f in findings:
            f.type = "risk"
            metadata = f.metadata or {}
            category = metadata.get("category", "")
            if f.tags is None:
                f.tags = []
            if category and category not in f.tags:
                f.tags.append(category)

        # Run the policy risk gate evaluator
        gate_result = evaluate_risk_gate(findings, self.policy_pack)

        summary = self._build_summary(findings, gate_result)

        output = AgentOutput(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            run_id=self.run_config.run_id,
            findings=findings,
            summary=summary,
            errors=errors,
        )
        self.save_output(output)

        # Save gate result separately
        self._save_gate_result(gate_result)

        return output

    def _load_all_upstream_findings(self) -> str:
        """Load findings from all previous agents."""
        findings_dir = Path(self.run_config.output_dir) / self.run_config.run_id / "findings"
        sections: list[str] = []

        agent_files = [
            "intake.json",
            "customer.json",
            "competitive.json",
            "metrics.json",
            "requirements.json",
            "feasibility.json",
        ]

        for agent_file in agent_files:
            file_path = findings_dir / agent_file
            if not file_path.exists():
                continue

            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                agent_name = data.get("agent_name", agent_file)
                findings = data.get("findings", [])

                if not findings:
                    continue

                sections.append(f"## Findings from {agent_name}")
                for f in findings:
                    fid = f.get("id", "?")
                    ftype = f.get("type", "?")
                    title = f.get("title", "Untitled")
                    desc = f.get("description", "")
                    impact = f.get("impact", "?")
                    confidence = f.get("confidence", "?")
                    tags = f.get("tags", [])
                    evidence_refs = [ev.get("source_id", "?") for ev in f.get("evidence", [])]

                    sections.append(
                        f"- [{fid}] ({ftype}, impact={impact}, confidence={confidence}): "
                        f"{title}\n  {desc}"
                        + (f"\n  Tags: {', '.join(tags)}" if tags else "")
                        + (f"\n  Evidence: {', '.join(evidence_refs)}" if evidence_refs else "")
                    )
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warning("Failed to load %s: %s", file_path, exc)

        # Include risk hotspots from context packet
        packet = self.context_packet
        if packet.risk_hotspots:
            sections.append("## Risk Hotspots from Intake")
            for h in packet.risk_hotspots:
                sections.append(
                    f"- [{h.category}] (severity={h.severity}): {h.description}"
                    + (f"\n  Sources: {', '.join(h.source_ids)}" if h.source_ids else "")
                )

        return "\n\n".join(sections)

    def _build_system_prompt(self) -> str:
        """Build system prompt with policy pack values injected."""
        return SYSTEM_PROMPTS[self.agent_id]

    def _build_user_prompt(self, upstream_data: str) -> str:
        """Build user prompt with product context, policy summary, and upstream findings."""
        packet = self.context_packet
        policy = self.policy_pack

        policy_summary = (
            "# Policy Pack Summary\n\n"
            "## Product Principles\n"
            + ("\n".join(f"- {p}" for p in policy.product_principles) or "None specified.")
            + "\n\n## Non-Goals\n"
            + ("\n".join(f"- {ng}" for ng in policy.non_goals) or "None specified.")
            + "\n\n## Data Handling\n"
            f"- Require collection justification: {policy.data_handling.require_collection_justification}\n"
            f"- Require consent mechanism: {policy.data_handling.require_consent_mechanism}\n"
            f"- Retention limit: {policy.data_handling.retention_limit_days} days\n"
            f"- Minimize PII: {policy.data_handling.minimize_pii}\n"
            "\n## Accessibility\n"
            f"- WCAG level: {policy.accessibility.wcag_level}\n"
            f"- Screen reader support: {policy.accessibility.require_screen_reader_support}\n"
            f"- Keyboard navigation: {policy.accessibility.require_keyboard_navigation}\n"
            "\n## Risk Gating\n"
            f"- Block on critical privacy: {policy.risk_gating.block_on_critical_privacy}\n"
            f"- Block on critical security: {policy.risk_gating.block_on_critical_security}\n"
            f"- Legal review for PII: {policy.risk_gating.require_legal_review_for_pii}\n"
            f"- Max unmitigated high risks: {policy.risk_gating.max_unmitigated_high_risks}\n"
        )

        return (
            f"# Product: {packet.product_name}\n"
            f"{packet.product_description}\n\n"
            f"{policy_summary}\n\n"
            f"# All Upstream Findings\n\n"
            f"{upstream_data}\n\n"
            "Scan ALL findings above for privacy, security, compliance, and accessibility risks. "
            "Apply the policy rules to determine blockers. Flag each risk with its category, "
            "severity, mitigation, and whether it blocks the pipeline."
        )

    def _build_summary(self, findings: list[Finding], gate_result: dict) -> str:
        """Build summary including gate result."""
        by_category: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        blocker_count = 0

        for f in findings:
            meta = f.metadata or {}
            cat = meta.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[f.impact] = by_severity.get(f.impact, 0) + 1
            if meta.get("is_blocker"):
                blocker_count += 1

        category_str = ", ".join(f"{v} {k}" for k, v in sorted(by_category.items()))
        gate_status = "PASSED" if gate_result["passed"] else "FAILED"
        gate_blockers = len(gate_result["blockers"])
        gate_warnings = len(gate_result["warnings"])

        return (
            f"Identified {len(findings)} risks ({category_str}). "
            f"{blocker_count} flagged as blockers. "
            f"Risk gate: {gate_status} ({gate_blockers} blockers, {gate_warnings} warnings)."
        )

    def _save_gate_result(self, gate_result: dict) -> None:
        """Save the risk gate evaluation result."""
        findings_dir = Path(self.run_config.output_dir) / self.run_config.run_id / "findings"
        findings_dir.mkdir(parents=True, exist_ok=True)

        gate_path = findings_dir / "risk_gate_result.json"
        gate_path.write_text(
            json.dumps(gate_result, indent=2),
            encoding="utf-8",
        )
        self.logger.info("Saved risk gate result to %s (passed=%s)", gate_path, gate_result["passed"])
