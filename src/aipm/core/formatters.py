"""Output formatting utilities for the AIPM pipeline CLI.

Provides four public helpers:
    format_cli_summary   — Unicode-box run summary for terminal output.
    format_findings_table — ASCII table of findings sorted by impact.
    format_risk_report   — Risk assessment with pass/fail gate indicator.
    colorize             — ANSI colour wrapper.
"""

import os
from pathlib import Path

from aipm.schemas.findings import Finding

# ------------------------------------------------------------------
# ANSI colour support
# ------------------------------------------------------------------

_ANSI: dict[str, str] = {
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "cyan": "\033[96m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}

_IMPACT_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_IMPACT_COLOR: dict[str, str] = {"critical": "red", "high": "yellow", "medium": "cyan", "low": ""}
_IMPACT_BADGE: dict[str, str] = {
    "critical": "[CRIT]",
    "high": "[HIGH]",
    "medium": "[MED] ",
    "low": "[LOW] ",
}

# Cost estimation — USD per 1 M tokens
_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def colorize(text: str, color: str) -> str:
    """Wrap *text* with ANSI colour codes for terminal output.

    Args:
        text:  Text to colourize.
        color: Colour name — one of: red, green, yellow, blue, cyan, bold.

    Returns:
        ANSI-escaped string. Returns *text* unchanged when the colour is
        unrecognised, ``NO_COLOR`` is set, or ``TERM=dumb``.
    """
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return text
    code = _ANSI.get(color.lower())
    return f"{code}{text}{_ANSI['reset']}" if code else text


# ------------------------------------------------------------------
# Box-drawing helpers (internal)
# ------------------------------------------------------------------

_BOX_W = 38  # inner content width (chars between "║ " and " ║")


def _row(text: str, width: int = _BOX_W) -> str:
    if len(text) > width:
        text = text[: width - 1] + "…"
    return f"║ {text:<{width}} ║"


def _sep(width: int = _BOX_W) -> str:
    return f"╠{'═' * (width + 2)}╣"


def _top(width: int = _BOX_W) -> str:
    return f"╔{'═' * (width + 2)}╗"


def _bot(width: int = _BOX_W) -> str:
    return f"╚{'═' * (width + 2)}╝"


# ------------------------------------------------------------------
# Cost helper (internal)
# ------------------------------------------------------------------


def _estimate_cost(manifest: dict) -> float:
    """Estimate USD cost from manifest token_usage and model fields."""
    usage = (manifest.get("token_usage") or {}).get("total", {})
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)

    model = manifest.get("model", "")
    provider = manifest.get("provider", "")

    if model in _PRICING:
        rates = _PRICING[model]
    else:
        rates = _PRICING["gpt-4o"]

    return round(
        (prompt / 1_000_000) * rates["input"] + (completion / 1_000_000) * rates["output"],
        4,
    )


# ------------------------------------------------------------------
# 1. CLI summary box
# ------------------------------------------------------------------

_EXPECTED_ARTIFACTS = [
    ("prd", "prd.md"),
    ("roadmap", "roadmap.json"),
    ("experiment_plan", "experiment_plan.md"),
    ("decision_log", "decision_log.md"),
    ("backlog", "backlog.csv"),
]


def format_cli_summary(manifest: dict) -> str:
    """Pretty-print a CLI-friendly run summary in a Unicode box.

    Reads the manifest produced by ``PipelineOrchestrator.run()`` and renders
    key metrics, agent status, and artifact checklist into a bordered panel.

    Args:
        manifest: Run manifest dict from the orchestrator.

    Returns:
        Multi-line string with Unicode box-drawing characters.
    """
    run_id = manifest.get("run_id", "—")
    product = manifest.get("product_name", "—")
    rec = str(manifest.get("recommendation", "—")).upper()

    agents_run = manifest.get("agents_run", [])
    agents_failed = manifest.get("agents_failed", [])
    total_agents = len(agents_run) + len(agents_failed)

    total_findings = manifest.get("total_findings", 0)
    findings_by_type = manifest.get("findings_by_type", {})
    risk_count = findings_by_type.get("risk", 0)

    usage = (manifest.get("token_usage") or {}).get("total", {})
    total_tokens = usage.get("total_tokens", 0)
    est_cost = _estimate_cost(manifest)
    duration = manifest.get("duration_seconds", 0)

    artifacts = manifest.get("artifacts", {})

    lines = [
        _top(),
        _row("  AIPM Pipeline Run Complete"),
        _sep(),
        _row(f"Run ID:          {run_id}"),
        _row(f"Product:         {product}"),
        _row(f"Recommendation:  {rec}"),
        _row(f"Agents Run:      {len(agents_run)}/{total_agents} successful"),
        _row(f"Total Findings:  {total_findings}"),
        _row(f"Risk Findings:   {risk_count}"),
        _row(f"Token Usage:     {total_tokens:,} tokens"),
        _row(f"Est. Cost:       ${est_cost:.4f}"),
        _row(f"Duration:        {duration:.1f}s"),
        _sep(),
        _row("Artifacts:"),
    ]

    for key, display_name in _EXPECTED_ARTIFACTS:
        path = artifacts.get(key, "")
        exists = bool(path) and Path(path).exists()
        mark = "✓" if exists else "✗"
        lines.append(_row(f"  {mark} {display_name}"))

    lines.append(_bot())

    # Post-box warnings / errors
    errors = manifest.get("errors", {})
    if errors:
        lines.append("")
        lines.append(colorize(f"  ⚠  Agents with errors: {', '.join(errors.keys())}", "yellow"))

    for w in manifest.get("bundle_warnings", []):
        lines.append(colorize(f"  ⚠  {w}", "yellow"))

    return "\n".join(lines)


# ------------------------------------------------------------------
# 2. Findings table
# ------------------------------------------------------------------

_FINDINGS_COLS: list[tuple[str, int]] = [
    ("ID", 20),
    ("Type", 14),
    ("Impact", 9),
    ("Confidence", 12),
    ("Title", 40),
]


def format_findings_table(findings: list[Finding]) -> str:
    """Format findings as an ASCII table sorted by impact severity.

    Args:
        findings: List of Finding objects to display.

    Returns:
        Multi-line ASCII table string.  Returns a short notice when the list
        is empty.
    """
    if not findings:
        return "(no findings to display)"

    sorted_findings = sorted(
        findings,
        key=lambda f: (_IMPACT_RANK.get(f.impact, 4), f.agent_id, f.id),
    )

    # Header
    header = "  ".join(f"{col:<{w}}" for col, w in _FINDINGS_COLS)
    divider = "  ".join("─" * w for _, w in _FINDINGS_COLS)

    lines = [
        f"Findings ({len(sorted_findings)} total, sorted by impact):",
        header,
        divider,
    ]

    for f in sorted_findings:
        badge = _IMPACT_BADGE.get(f.impact, f.impact)
        title = f.title if len(f.title) <= 40 else f.title[:39] + "…"
        cells = [
            f"{f.id:<20}",
            f"{f.type:<14}",
            f"{badge:<9}",
            f"{f.confidence:<12}",
            f"{title:<40}",
        ]
        line = "  ".join(cells)
        color = _IMPACT_COLOR.get(f.impact)
        lines.append(colorize(line, color) if color else line)

    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------
# 3. Risk report
# ------------------------------------------------------------------


def format_risk_report(risk_findings: list[Finding], gate_result: dict) -> str:
    """Formatted risk assessment with pass/fail gate indicator.

    Args:
        risk_findings: Findings with ``type='risk'`` from the Risk agent.
        gate_result:   Dict with keys ``passed`` (bool), ``blockers``
                       (list[str]), and ``warnings`` (list[str]).
                       Produced by ``policy.evaluate_risk_gate()``.

    Returns:
        Multi-line formatted risk report string.
    """
    passed = gate_result.get("passed", True)
    blockers = gate_result.get("blockers", [])
    warnings = gate_result.get("warnings", [])

    gate_label = colorize("✓ GATE PASSED", "green") if passed else colorize("✗ GATE FAILED", "red")

    lines = [
        "━" * 60,
        f"  Risk Gate Status: {gate_label}",
        "━" * 60,
        "",
    ]

    if blockers:
        lines.append(colorize("  Blockers:", "red"))
        for b in blockers:
            lines.append(colorize(f"    • {b}", "red"))
        lines.append("")

    if warnings:
        lines.append(colorize("  Warnings:", "yellow"))
        for w in warnings:
            lines.append(colorize(f"    • {w}", "yellow"))
        lines.append("")

    # Group findings by impact
    by_impact: dict[str, list[Finding]] = {}
    for f in risk_findings:
        by_impact.setdefault(f.impact, []).append(f)

    for impact in ("critical", "high", "medium", "low"):
        group = by_impact.get(impact, [])
        if not group:
            continue
        label = f"  {impact.upper()} ({len(group)}):"
        color = _IMPACT_COLOR.get(impact)
        lines.append(colorize(label, color) if color else label)
        for f in group:
            finding_line = f"    [{f.id}] {f.title}"
            lines.append(colorize(finding_line, color) if color else finding_line)
            if f.recommendations:
                lines.append(f"           → {f.recommendations[0]}")
        lines.append("")

    if not risk_findings:
        lines.append(colorize("  No risk findings recorded.", "green"))
        lines.append("")

    lines.append("━" * 60)
    return "\n".join(lines)
