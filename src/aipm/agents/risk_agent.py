"""Agent G — Risk/Privacy/Compliance Guardrails Agent.

Scans all upstream findings for privacy, security, compliance, and accessibility
risks. Applies policy-driven gating rules and flags blockers.
"""

import json
import logging
import re
from pathlib import Path

from aipm.agents.base import BaseAgent
from aipm.core.policy import evaluate_risk_gate
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert security engineer, privacy officer, and compliance auditor. \
Your job is to scan all product findings for risks across privacy, security, \
compliance, and accessibility — and flag blockers based on policy rules.

Analyze ALL the findings below against the provided policy pack.

You MUST scan for risks in these categories:

1. **Privacy Risks**:
   - PII handling: Is personal data collected, stored, or transmitted? Is it necessary?
   - Data collection: Are there collection justification gaps?
   - Consent: Are there consent mechanism gaps (opt-in, opt-out, GDPR consent)?
   - Data retention: Does retention exceed policy limits ({retention_limit_days} days)?
   - Data minimization: Is PII minimized per policy?

2. **Security Risks**:
   - Authentication weaknesses (missing MFA, weak session management)
   - Injection vectors (SQL, XSS, command injection)
   - Data exposure (unencrypted storage, insecure transmission, verbose errors)
   - Authorization gaps (missing RBAC, privilege escalation paths)

3. **Compliance Risks**:
   - GDPR: Right to erasure, data portability, processing lawful basis
   - CCPA: Consumer rights, data sale opt-out
   - Industry-specific regulations relevant to the product

4. **Accessibility Risks**:
   - WCAG {wcag_level} compliance gaps
   - Screen reader support: {require_screen_reader}
   - Keyboard navigation: {require_keyboard_nav}
   - Color contrast, alt text, ARIA labels, focus management

For EACH risk found, provide:
- **severity**: critical / high / medium / low
- **category**: privacy / security / compliance / accessibility
- **description**: Clear explanation of the risk
- **mitigation**: Specific recommendation to address the risk
- **is_blocker**: Whether this risk should BLOCK the pipeline based on these rules:
  - Block on critical privacy risk: {block_privacy}
  - Block on critical security risk: {block_security}
  - Require legal review for PII: {require_legal_review}
  - Max unmitigated high risks allowed: {max_high_risks}

You MUST produce findings of type "risk" with metadata:
{{
  "category": "privacy" | "security" | "compliance" | "accessibility",
  "is_blocker": true | false,
  "mitigation": "<specific mitigation recommendation>",
  "policy_rule": "<which policy rule triggered this, if any>"
}}

Also set the finding's "tags" to include the category (e.g., ["privacy", "pii"]) \
so the risk gate evaluator can match them.

IMPORTANT:
- Every finding must reference at least one source_id from the upstream findings.
- Use the exact source IDs given (finding IDs like "customer-001", "requirements-003").
- Return ONLY valid JSON matching the schema below. No markdown fences, no extra text.

{schema}
"""


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
        findings, errors = self._parse_response(response)

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
        policy = self.policy_pack
        return SYSTEM_PROMPT.format(
            retention_limit_days=policy.data_handling.retention_limit_days,
            wcag_level=policy.accessibility.wcag_level,
            require_screen_reader=policy.accessibility.require_screen_reader_support,
            require_keyboard_nav=policy.accessibility.require_keyboard_navigation,
            block_privacy=policy.risk_gating.block_on_critical_privacy,
            block_security=policy.risk_gating.block_on_critical_security,
            require_legal_review=policy.risk_gating.require_legal_review_for_pii,
            max_high_risks=policy.risk_gating.max_unmitigated_high_risks,
            schema=self._build_findings_prompt_section(),
        )

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

                # Ensure type is "risk"
                raw["type"] = "risk"

                # Ensure category tag is present for gate evaluation
                metadata = raw.get("metadata", {})
                category = metadata.get("category", "")
                tags = raw.get("tags", [])
                if category and category not in tags:
                    tags.append(category)
                raw["tags"] = tags

                # Parse evidence items
                evidence = []
                for ev in raw.get("evidence", []):
                    evidence.append(
                        EvidenceItem(
                            source_id=ev.get("source_id", "UNKNOWN"),
                            source_type=ev.get("source_type", "doc"),
                            excerpt=ev.get("excerpt", ""),
                            url=ev.get("url"),
                        )
                    )
                raw["evidence"] = evidence

                finding = Finding.model_validate(raw)
                findings.append(finding)
            except Exception as exc:
                errors.append(f"Failed to parse finding {i + 1}: {exc}")

        self.logger.info("Parsed %d risk findings (%d errors)", len(findings), len(errors))
        return findings, errors

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
