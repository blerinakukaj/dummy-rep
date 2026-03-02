"""Policy pack loader and risk gate evaluator."""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from aipm.schemas.findings import Finding

logger = logging.getLogger(__name__)


class DataHandlingPolicy(BaseModel):
    """Rules for data collection, consent, and retention."""

    require_collection_justification: bool = True
    require_consent_mechanism: bool = True
    retention_limit_days: int = 90
    minimize_pii: bool = True


class ExperimentationPolicy(BaseModel):
    """Constraints for A/B testing and experimentation."""

    require_guardrail_metrics: bool = True
    min_sample_size: int = 1000
    max_experiment_duration_days: int = 30
    success_criteria_required: bool = True


class AccessibilityPolicy(BaseModel):
    """Accessibility compliance requirements."""

    wcag_level: str = "AA"
    require_screen_reader_support: bool = True
    require_keyboard_navigation: bool = True


class RiskGatingPolicy(BaseModel):
    """Rules that determine whether the pipeline gates (blocks) a recommendation."""

    block_on_critical_privacy: bool = True
    block_on_critical_security: bool = True
    require_legal_review_for_pii: bool = True
    max_unmitigated_high_risks: int = 2


class PolicyPack(BaseModel):
    """Complete policy pack matching the YAML structure."""

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
