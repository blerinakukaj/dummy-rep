"""Policy pack loader and risk gate evaluator."""

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from aipm.schemas.findings import Finding

logger = logging.getLogger(__name__)


class DataHandlingPolicy(BaseModel):
    """Rules for data collection, consent, and retention."""

    model_config = ConfigDict(extra="allow")

    require_collection_justification: bool = True
    require_consent_mechanism: bool = True
    retention_limit_days: int = 90
    minimize_pii: bool = True


class ExperimentationPolicy(BaseModel):
    """Constraints for A/B testing and experimentation."""

    model_config = ConfigDict(extra="allow")

    require_guardrail_metrics: bool = True
    min_sample_size: int = 1000
    max_experiment_duration_days: int = 30
    success_criteria_required: bool = True


class AccessibilityPolicy(BaseModel):
    """Accessibility compliance requirements."""

    model_config = ConfigDict(extra="allow")

    wcag_level: str = "AA"
    require_screen_reader_support: bool = True
    require_keyboard_navigation: bool = True


class RiskGatingPolicy(BaseModel):
    """Rules that determine whether the pipeline gates (blocks) a recommendation."""

    model_config = ConfigDict(extra="allow")

    block_on_critical_privacy: bool = True
    block_on_critical_security: bool = True
    require_legal_review_for_pii: bool = True
    max_unmitigated_high_risks: int = 2


class PolicyPack(BaseModel):
    """Complete policy pack matching the YAML structure."""

    model_config = ConfigDict(extra="allow")

    product_principles: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    data_handling: DataHandlingPolicy = Field(default_factory=DataHandlingPolicy)
    experimentation: ExperimentationPolicy = Field(default_factory=ExperimentationPolicy)
    accessibility: AccessibilityPolicy = Field(default_factory=AccessibilityPolicy)
    risk_gating: RiskGatingPolicy = Field(default_factory=RiskGatingPolicy)


def load_policy(path: str) -> PolicyPack:
    """Load a YAML policy pack from disk.

    Args:
        path: Path to the YAML policy file.

    Returns:
        A validated PolicyPack instance.

    Raises:
        FileNotFoundError: If the policy file does not exist.
    """
    policy_path = Path(path)
    if not policy_path.exists():
        raise FileNotFoundError(f"Policy file not found: {path}")

    with open(policy_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    policy = PolicyPack.model_validate(raw)
    logger.info("Loaded policy pack from %s", path)
    return policy


def _flatten_policy(policy: PolicyPack) -> dict[str, Any]:
    """Return a flat dot-notation dict of all policy field values."""
    flat: dict[str, Any] = {}
    top = policy.model_dump()
    for section, value in top.items():
        if isinstance(value, dict):
            for key, val in value.items():
                flat[f"{section}.{key}"] = val
        else:
            flat[section] = value
    return flat


def compare_policies(policy_a: PolicyPack, policy_b: PolicyPack) -> dict[str, Any]:
    """Compare two policy packs and return their differences.

    Args:
        policy_a: The baseline policy.
        policy_b: The policy to compare against the baseline.

    Returns:
        Dict with keys:
            - differences: list of dicts {field, policy_a, policy_b} for changed fields
            - only_in_a: list of field names present only in policy_a
            - only_in_b: list of field names present only in policy_b
            - identical: bool — True if the two policies are functionally equal
    """
    flat_a = _flatten_policy(policy_a)
    flat_b = _flatten_policy(policy_b)

    all_keys = set(flat_a) | set(flat_b)
    differences: list[dict[str, Any]] = []
    only_in_a: list[str] = []
    only_in_b: list[str] = []

    for key in sorted(all_keys):
        if key not in flat_a:
            only_in_b.append(key)
        elif key not in flat_b:
            only_in_a.append(key)
        elif flat_a[key] != flat_b[key]:
            differences.append({"field": key, "policy_a": flat_a[key], "policy_b": flat_b[key]})

    return {
        "differences": differences,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "identical": not differences and not only_in_a and not only_in_b,
    }


def format_policy_summary(policy: PolicyPack) -> str:
    """Return a human-readable summary of the policy pack.

    Args:
        policy: The policy pack to summarise.

    Returns:
        A multi-line string suitable for CLI or log output.
    """
    lines: list[str] = []

    lines.append("=== Policy Summary ===")

    lines.append("\nProduct Principles:")
    for p in policy.product_principles:
        lines.append(f"  • {p}")

    lines.append("\nNon-Goals:")
    for g in policy.non_goals:
        lines.append(f"  • {g}")

    dh = policy.data_handling
    lines.append("\nData Handling:")
    lines.append(f"  Retention limit:           {dh.retention_limit_days} days")
    lines.append(f"  Require collection justif: {dh.require_collection_justification}")
    lines.append(f"  Require consent mechanism: {dh.require_consent_mechanism}")
    lines.append(f"  Minimize PII:              {dh.minimize_pii}")
    for field, val in (dh.model_extra or {}).items():
        lines.append(f"  {field}: {val}")

    exp = policy.experimentation
    lines.append("\nExperimentation:")
    lines.append(f"  Min sample size:           {exp.min_sample_size}")
    lines.append(f"  Max duration (days):       {exp.max_experiment_duration_days}")
    lines.append(f"  Require guardrail metrics: {exp.require_guardrail_metrics}")
    lines.append(f"  Success criteria required: {exp.success_criteria_required}")
    for field, val in (exp.model_extra or {}).items():
        lines.append(f"  {field}: {val}")

    acc = policy.accessibility
    lines.append("\nAccessibility:")
    lines.append(f"  WCAG level:                {acc.wcag_level}")
    lines.append(f"  Screen reader support:     {acc.require_screen_reader_support}")
    lines.append(f"  Keyboard navigation:       {acc.require_keyboard_navigation}")
    for field, val in (acc.model_extra or {}).items():
        lines.append(f"  {field}: {val}")

    rg = policy.risk_gating
    lines.append("\nRisk Gating:")
    lines.append(f"  Block on critical privacy: {rg.block_on_critical_privacy}")
    lines.append(f"  Block on critical security:{rg.block_on_critical_security}")
    lines.append(f"  Legal review for PII:      {rg.require_legal_review_for_pii}")
    lines.append(f"  Max unmitigated high risks:{rg.max_unmitigated_high_risks}")
    for field, val in (rg.model_extra or {}).items():
        lines.append(f"  {field}: {val}")

    lines.append("\n" + "=" * 22)
    return "\n".join(lines)


def evaluate_risk_gate(findings: list[Finding], policy: PolicyPack) -> dict:
    """Evaluate whether findings pass the risk gate defined by the policy.

    Checks:
        - Critical privacy findings block if block_on_critical_privacy is true.
        - Critical security findings block if block_on_critical_security is true.
        - PII-related findings require legal review if require_legal_review_for_pii is true.
        - High-severity unmitigated risks are counted against max_unmitigated_high_risks.

    Args:
        findings: List of findings to evaluate (typically from the Risk agent).
        policy: The policy pack to evaluate against.

    Returns:
        Dict with keys: passed (bool), blockers (list[str]), warnings (list[str]).
    """
    blockers: list[str] = []
    warnings: list[str] = []
    gating = policy.risk_gating

    risk_findings = [f for f in findings if f.type == "risk"]
    high_risk_count = 0

    for finding in risk_findings:
        tags = [t.lower() for t in finding.tags]
        is_critical = finding.impact == "critical"
        is_high = finding.impact == "high"

        # Critical privacy gate
        if is_critical and "privacy" in tags and gating.block_on_critical_privacy:
            blockers.append(f"BLOCKED: Critical privacy risk — {finding.title} [{finding.id}]")

        # Critical security gate
        if is_critical and "security" in tags and gating.block_on_critical_security:
            blockers.append(f"BLOCKED: Critical security risk — {finding.title} [{finding.id}]")

        # PII legal review gate
        if "pii" in tags or "privacy" in tags:
            if gating.require_legal_review_for_pii:
                warnings.append(f"Legal review required for PII/privacy — {finding.title} [{finding.id}]")

        # Count high-severity unmitigated risks
        if is_high:
            high_risk_count += 1

    if high_risk_count > gating.max_unmitigated_high_risks:
        blockers.append(
            f"BLOCKED: {high_risk_count} unmitigated high risks exceed maximum of {gating.max_unmitigated_high_risks}"
        )

    passed = len(blockers) == 0

    if passed:
        logger.info("Risk gate PASSED (%d warnings)", len(warnings))
    else:
        logger.warning("Risk gate FAILED with %d blockers", len(blockers))

    return {
        "passed": passed,
        "blockers": blockers,
        "warnings": warnings,
    }
