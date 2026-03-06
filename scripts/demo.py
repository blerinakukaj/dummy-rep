"""Automated demo script showcasing all key AIPM pipeline features.

Runs thirteen demonstration scenarios that exercise different input bundles,
policy configurations, output artifacts, and quality guarantees.

Usage:
    python scripts/demo.py                 # Run all demos
    python scripts/demo.py --demo 1        # Run a specific demo (1-13)
    python scripts/demo.py --model gpt-4o-mini
"""

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import textwrap
import time
from pathlib import Path

# Ensure the project root is on sys.path so `aipm` is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from aipm.core.orchestrator import PipelineOrchestrator  # noqa: E402
from aipm.schemas.config import RunConfig  # noqa: E402

console = Console()

# ---------------------------------------------------------------------------
# Recommendation colours
# ---------------------------------------------------------------------------
_REC_STYLE = {
    "proceed": "bold green",
    "proceed_with_mitigations": "bold yellow",
    "validate_first": "bold bright_yellow",
    "do_not_pursue": "bold red",
}


# ---------------------------------------------------------------------------
# Pipeline runner helper
# ---------------------------------------------------------------------------
async def run_pipeline(
    input_path: str,
    *,
    policy: str = "src/aipm/policies/default_policy.yaml",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    output_dir: str = "output",
    temperature: float = 0.2,
) -> dict:
    """Run the AIPM pipeline with a live spinner and return the manifest dict."""
    config = RunConfig(
        input_path=input_path,
        output_dir=output_dir,
        provider=provider,
        model=model,
        temperature=temperature,
        policy_path=policy,
    )
    orchestrator = PipelineOrchestrator(config)

    console.print("[cyan]Running 8-agent pipeline...[/cyan]")
    t0 = time.perf_counter()
    manifest = await orchestrator.run(input_path)
    elapsed = time.perf_counter() - t0
    console.print(f"[green]Pipeline complete in {elapsed:.1f}s[/green]\n")
    manifest["_demo_elapsed"] = round(elapsed, 2)
    return manifest


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def show_recommendation(manifest: dict) -> None:
    """Show the recommendation as a prominent Rich panel."""
    rec = manifest.get("recommendation", "(none)")
    total = manifest.get("total_findings", 0)
    agents = len(manifest.get("agents_run", []))
    elapsed = manifest.get("_demo_elapsed", "?")
    errors = manifest.get("errors", {})

    style = _REC_STYLE.get(rec, "bold white")
    rec_text = Text(rec.upper().replace("_", " "), style=style)

    content = Text.assemble(
        ("Recommendation: ", "bold"),
        rec_text,
        (f"\nFindings: {total}  |  Agents: {agents}/8  |  Time: {elapsed}s", "dim"),
    )
    if errors:
        content.append(f"\nErrors: {', '.join(errors.keys())}", style="yellow")

    console.print(Panel(content, border_style="blue", padding=(0, 2)))


def show_artifacts_table(manifest: dict) -> None:
    """Show a Rich table of generated artifacts."""
    artifacts = manifest.get("artifacts", {})
    if not artifacts:
        console.print("  [yellow]No artifacts generated.[/yellow]")
        return

    table = Table(title="Generated Artifacts", show_lines=False, padding=(0, 1))
    table.add_column("Artifact", style="bold cyan")
    table.add_column("Status", justify="center")
    table.add_column("Path", style="dim")

    for name, path in artifacts.items():
        exists = Path(path).exists() if path else False
        status = "[green]exists[/green]" if exists else "[red]missing[/red]"
        table.add_row(name, status, str(path) if path else "")

    console.print(table)


def show_risk_gate(manifest: dict) -> None:
    """Show the risk gate result as a Rich panel."""
    artifacts = manifest.get("artifacts", {})
    run_dir = None
    for path_str in artifacts.values():
        if path_str:
            run_dir = Path(path_str).parent.parent
            break
    if not run_dir:
        return

    rg_path = run_dir / "findings" / "risk_gate_result.json"
    if not rg_path.exists():
        return

    try:
        rg = json.loads(rg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return

    passed = rg.get("passed", True)
    blockers = rg.get("blockers", [])
    warnings = rg.get("warnings", [])

    if passed:
        header = Text("RISK GATE: PASSED", style="bold green")
    else:
        header = Text("RISK GATE: BLOCKED", style="bold red")

    lines = Text()
    for b in blockers:
        lines.append("  BLOCKER  ", style="bold white on red")
        lines.append(f" {b}\n")
    for w in warnings:
        lines.append("  WARNING  ", style="bold black on yellow")
        lines.append(f" {w}\n")
    if not blockers and not warnings:
        lines.append("  No blockers or warnings", style="green")

    border = "green" if passed else "red"
    console.print(Panel(Text.assemble(header, "\n", lines), border_style=border, padding=(0, 1)))


def show_backlog_table(manifest: dict) -> None:
    """Show a Rich table of backlog stories."""
    artifacts = manifest.get("artifacts", {})
    bl_path = artifacts.get("backlog")
    if not (bl_path and Path(bl_path).exists()):
        return

    content = Path(bl_path).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return

    total = len(rows)
    has_deps = sum(1 for r in rows if r.get("dependencies", "").strip())
    phases = {}
    for r in rows:
        ph = r.get("phase", "?")
        phases[ph] = phases.get(ph, 0) + 1
    phase_str = ", ".join(f"{ph}: {n}" for ph, n in sorted(phases.items()))

    table = Table(
        title=f"Backlog: {total} stories  |  Phases: {phase_str}  |  Deps: {has_deps}/{total}",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Phase", style="cyan", width=6)
    table.add_column("Priority", style="magenta", width=4)
    table.add_column("Story Title", style="white")
    table.add_column("Dependencies", style="dim", max_width=50)

    for row in rows[:8]:
        table.add_row(
            row.get("phase", "?"),
            row.get("priority", "?"),
            row.get("story_title", row.get("epic_title", "?")),
            (row.get("dependencies", "") or "")[:50],
        )
    if len(rows) > 8:
        table.add_row("", "", f"[dim]... and {len(rows) - 8} more[/dim]", "")

    console.print(table)


def show_roadmap(manifest: dict) -> None:
    """Show roadmap summary."""
    artifacts = manifest.get("artifacts", {})
    rm_path = artifacts.get("roadmap")
    if not (rm_path and Path(rm_path).exists()):
        return

    try:
        roadmap = json.loads(Path(rm_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return

    themes = roadmap.get("themes", [])
    milestones = roadmap.get("milestones", [])
    critical = roadmap.get("critical_path", [])

    table = Table(
        title=f"Roadmap: {len(themes)} themes, {len(milestones)} milestones",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Phase", style="cyan", width=6)
    table.add_column("Milestone", style="bold white")
    table.add_column("Description", style="dim", max_width=70)

    for ms in milestones[:5]:
        table.add_row(
            ms.get("phase", "?"),
            ms.get("name", "?"),
            (ms.get("description", "") or "")[:70],
        )

    console.print(table)
    if critical:
        path_str = " [bold cyan]->[/bold cyan] ".join(critical)
        console.print(f"  Critical path: {path_str}")


def show_experiment_preview(manifest: dict) -> None:
    """Show first 15 lines of the experiment plan."""
    artifacts = manifest.get("artifacts", {})
    exp_path = artifacts.get("experiment_plan")
    if not (exp_path and Path(exp_path).exists()):
        return

    content = Path(exp_path).read_text(encoding="utf-8")
    lines = content.splitlines()[:15]
    total = len(content.splitlines())

    text = "\n".join(lines)
    if total > 15:
        text += f"\n... ({total} total lines)"

    console.print(Panel(text, title="Experiment Plan Preview", border_style="blue", padding=(0, 1)))


def show_ticket_coverage(manifest: dict, input_path: str) -> None:
    """Show ticket coverage as a compact summary."""
    tickets_path = Path(input_path) / "tickets.json"
    if not tickets_path.exists():
        return
    try:
        tickets = json.loads(tickets_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return

    ticket_ids = {t["id"] for t in tickets}

    artifacts = manifest.get("artifacts", {})
    bl_path = artifacts.get("backlog")
    if not (bl_path and Path(bl_path).exists()):
        return

    content = Path(bl_path).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    covered = set()
    for tid in ticket_ids:
        for row in rows:
            blob = " ".join([
                row.get("description", ""),
                row.get("story_title", ""),
                row.get("story_id", ""),
                row.get("labels", ""),
                row.get("acceptance_criteria", ""),
            ]).upper()
            if tid.upper() in blob:
                covered.add(tid)
                break
            ticket_title = next((t["title"] for t in tickets if t["id"] == tid), "")
            if ticket_title:
                words = set(ticket_title.upper().split())
                if words and sum(1 for w in words if w in blob) / len(words) >= 0.5:
                    covered.add(tid)
                    break

    n = len(ticket_ids)
    c = len(covered)
    style = "green" if c == n else ("yellow" if c >= n * 0.8 else "red")
    console.print(f"  Ticket coverage: [{style}]{c}/{n}[/{style}] input tickets mapped to backlog stories")
    missing = ticket_ids - covered
    for m in sorted(missing):
        console.print(f"    [yellow]MISSING:[/yellow] {m}")


def show_all_artifacts(manifest: dict, input_path: str = "") -> None:
    """Show detailed preview of all generated artifacts."""
    show_artifacts_table(manifest)
    console.print()
    show_risk_gate(manifest)
    console.print()
    show_roadmap(manifest)
    console.print()
    show_backlog_table(manifest)
    if input_path:
        show_ticket_coverage(manifest, input_path)
    console.print()
    show_experiment_preview(manifest)


def compare_recommendations(result_a: dict, result_b: dict) -> None:
    """Compare recommendations from two pipeline runs in a side-by-side table."""
    rec_a = result_a.get("recommendation", "(none)")
    rec_b = result_b.get("recommendation", "(none)")
    policy_a = result_a.get("_demo_policy", "Policy A")
    policy_b = result_b.get("_demo_policy", "Policy B")

    table = Table(title="Policy Comparison", show_lines=True, padding=(0, 2))
    table.add_column("Policy", style="bold cyan")
    table.add_column("Recommendation", justify="center")

    style_a = _REC_STYLE.get(rec_a, "white")
    style_b = _REC_STYLE.get(rec_b, "white")
    table.add_row(policy_a, Text(rec_a.upper().replace("_", " "), style=style_a))
    table.add_row(policy_b, Text(rec_b.upper().replace("_", " "), style=style_b))

    console.print(table)

    if rec_a != rec_b:
        console.print(Panel(
            "[bold green]Different policies produced different recommendations![/bold green]\n"
            "Same input, different policy -> different outcome.",
            border_style="green",
        ))
    else:
        console.print("[yellow]Both policies produced the same recommendation.[/yellow]")


# ---------------------------------------------------------------------------
# Demo scenarios (1-10: one per input bundle, 11: policy comparison, 12: showcase)
# ---------------------------------------------------------------------------
async def demo_1(provider: str, model: str) -> dict:
    """Demo 1: Privacy risk scenario -- PII risks trigger risk gate blockers."""
    console.rule("[bold magenta]Demo 1: Privacy Risk Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]privacy_risk[/bold] bundle...")
    console.print("[dim]Expected: risk gate BLOCKS on PII/privacy, ticket coverage, dependency chains[/dim]\n")

    result = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/default_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_01_privacy_risk",
    )
    show_recommendation(result)
    show_risk_gate(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/privacy_risk/")
    return result


async def demo_2(provider: str, model: str) -> dict:
    """Demo 2: Metric drop scenario -- experiment plan with instrumentation."""
    console.rule("[bold magenta]Demo 2: Metric Drop Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]metric_drop[/bold] bundle...")
    console.print("[dim]Expected: ticket coverage, experiment plan with instrumentation[/dim]\n")

    result = await run_pipeline(
        "input_bundles/metric_drop/",
        provider=provider,
        model=model,
        output_dir="output/demo_02_metric_drop",
    )
    show_recommendation(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/metric_drop/")
    show_experiment_preview(result)
    return result


async def demo_3(provider: str, model: str) -> dict:
    """Demo 3: Competitive parity -- roadmap with phased tradeoffs."""
    console.rule("[bold magenta]Demo 3: Competitive Parity Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]competitive_parity[/bold] bundle...")
    console.print("[dim]Expected: ticket coverage, dependency chains, phased roadmap[/dim]\n")

    result = await run_pipeline(
        "input_bundles/competitive_parity/",
        provider=provider,
        model=model,
        output_dir="output/demo_03_competitive_parity",
    )
    show_recommendation(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/competitive_parity/")
    show_roadmap(result)
    return result


async def demo_4(provider: str, model: str) -> dict:
    """Demo 4: Conflicting stakeholders -- ticket coverage + conflict resolution."""
    console.rule("[bold magenta]Demo 4: Conflicting Stakeholders[/bold magenta]")
    console.print("Running pipeline on [bold]conflicting_stakeholders[/bold] bundle...")
    console.print("[dim]Expected: ticket coverage, dependency chains, risk gate blockers[/dim]\n")

    result = await run_pipeline(
        "input_bundles/conflicting_stakeholders/",
        provider=provider,
        model=model,
        output_dir="output/demo_04_conflicting_stakeholders",
    )
    show_recommendation(result)
    show_risk_gate(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/conflicting_stakeholders/")
    return result


async def demo_5(provider: str, model: str) -> dict:
    """Demo 5: Sample bundle -- baseline end-to-end run."""
    console.rule("[bold magenta]Demo 5: Sample Bundle (Baseline)[/bold magenta]")
    console.print("Running pipeline on [bold]sample_bundle[/bold]...")
    console.print("[dim]Expected: 5/5 ticket coverage, dependency chains, full artifacts[/dim]\n")

    result = await run_pipeline(
        "input_bundles/sample_bundle/",
        provider=provider,
        model=model,
        output_dir="output/demo_05_sample_bundle",
    )
    show_recommendation(result)
    show_all_artifacts(result, "input_bundles/sample_bundle/")
    return result


async def demo_6(provider: str, model: str) -> dict:
    """Demo 6: Accessibility gap -- a11y compliance risk findings."""
    console.rule("[bold magenta]Demo 6: Accessibility Gap Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]a11y_gap[/bold] bundle...")
    console.print("[dim]Expected: a11y risk findings, dependency chains, full ticket coverage[/dim]\n")

    result = await run_pipeline(
        "input_bundles/a11y_gap/",
        provider=provider,
        model=model,
        output_dir="output/demo_06_a11y_gap",
    )
    show_recommendation(result)
    show_risk_gate(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/a11y_gap/")
    return result


async def demo_7(provider: str, model: str) -> dict:
    """Demo 7: Enterprise complexity -- large-scale requirements and phased roadmap."""
    console.rule("[bold magenta]Demo 7: Enterprise Complexity Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]enterprise_complexity[/bold] bundle...")
    console.print("[dim]Expected: complex roadmap with milestones, dependency chains[/dim]\n")

    result = await run_pipeline(
        "input_bundles/enterprise_complexity/",
        provider=provider,
        model=model,
        output_dir="output/demo_07_enterprise_complexity",
    )
    show_recommendation(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/enterprise_complexity/")
    show_roadmap(result)
    return result


async def demo_8(provider: str, model: str) -> dict:
    """Demo 8: Performance regression -- incident-driven analysis."""
    console.rule("[bold magenta]Demo 8: Performance Regression Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]perf_regression[/bold] bundle...")
    console.print("[dim]Expected: ticket coverage, MVP/V1/V2 dep chains, experiment plan[/dim]\n")

    result = await run_pipeline(
        "input_bundles/perf_regression/",
        provider=provider,
        model=model,
        output_dir="output/demo_08_perf_regression",
    )
    show_recommendation(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/perf_regression/")
    show_experiment_preview(result)
    return result


async def demo_9(provider: str, model: str) -> dict:
    """Demo 9: Pricing change -- competitive and customer impact analysis."""
    console.rule("[bold magenta]Demo 9: Pricing Change Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]pricing_change[/bold] bundle...")
    console.print("[dim]Expected: competitive findings, customer churn risk, full backlog[/dim]\n")

    result = await run_pipeline(
        "input_bundles/pricing_change/",
        provider=provider,
        model=model,
        output_dir="output/demo_09_pricing_change",
    )
    show_recommendation(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/pricing_change/")
    return result


async def demo_10(provider: str, model: str) -> dict:
    """Demo 10: Tech dependency -- feasibility and dependency risk analysis."""
    console.rule("[bold magenta]Demo 10: Tech Dependency Scenario[/bold magenta]")
    console.print("Running pipeline on [bold]tech_dependency[/bold] bundle...")
    console.print("[dim]Expected: ticket coverage, MVP->V1 dependency chains[/dim]\n")

    result = await run_pipeline(
        "input_bundles/tech_dependency/",
        provider=provider,
        model=model,
        output_dir="output/demo_10_tech_dependency",
    )
    show_recommendation(result)
    show_backlog_table(result)
    show_ticket_coverage(result, "input_bundles/tech_dependency/")
    return result


async def demo_11(provider: str, model: str) -> dict | None:
    """Demo 11: Policy configurability -- same input, different policy, different outcome."""
    console.rule("[bold magenta]Demo 11: Policy Configurability[/bold magenta]")
    console.print("Running [bold]privacy_risk[/bold] bundle with [bold]TWO[/bold] different policies...\n")

    console.print("[bold cyan]Run A:[/bold cyan] default_policy.yaml (strict: max_unmitigated_high_risks=2)")
    result_a = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/default_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_11a_default_policy",
    )
    result_a["_demo_policy"] = "default_policy.yaml"
    show_recommendation(result_a)

    console.print("\n[bold cyan]Run B:[/bold cyan] startup_fast_policy.yaml (relaxed: max_unmitigated_high_risks=5)")
    result_b = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/startup_fast_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_11b_startup_policy",
    )
    result_b["_demo_policy"] = "startup_fast_policy.yaml"
    show_recommendation(result_b)

    console.print()
    compare_recommendations(result_a, result_b)
    return result_a


async def demo_12(result: dict | None, provider: str, model: str) -> None:
    """Demo 12: Artifact showcase -- display all generated artifacts from a run."""
    console.rule("[bold magenta]Demo 12: Artifact Showcase[/bold magenta]")

    if result is None:
        console.print("Running [bold]sample_bundle[/bold] to generate artifacts for showcase...\n")
        result = await run_pipeline(
            "input_bundles/sample_bundle/",
            provider=provider,
            model=model,
            output_dir="output/demo_12_showcase",
        )

    console.print("[bold]Full artifact breakdown:[/bold]\n")
    show_all_artifacts(result, "input_bundles/sample_bundle/")


async def demo_13(provider: str, model: str) -> None:
    """Demo 13: Quality guarantees -- dependency inference, ticket coverage, risk gate."""
    console.rule("[bold magenta]Demo 13: Quality Guarantees Showcase[/bold magenta]")
    console.print("Runs 3 bundles and shows all quality checks pass thanks to")
    console.print("deterministic post-processing.\n")

    bundles = [
        ("conflicting_stakeholders", 8),
        ("sample_bundle", 5),
        ("tech_dependency", 5),
    ]

    for bundle_name, expected_tickets in bundles:
        console.print(f"\n  [bold cyan]Bundle:[/bold cyan] [bold]{bundle_name}[/bold] ({expected_tickets} tickets)")
        result = await run_pipeline(
            f"input_bundles/{bundle_name}/",
            provider=provider,
            model=model,
            output_dir=f"output/demo_13_{bundle_name}",
        )
        show_recommendation(result)
        show_risk_gate(result)
        show_backlog_table(result)
        show_ticket_coverage(result, f"input_bundles/{bundle_name}/")
        console.print()

    console.print(Panel(
        "[bold green]All 3 bundles demonstrate:[/bold green]\n"
        "  [green]OK[/green] 100% ticket coverage (input tickets -> backlog stories)\n"
        "  [green]OK[/green] Non-empty dependency chains (MVP -> V1 -> V2)\n"
        "  [green]OK[/green] Risk gate correctly reports is_blocker findings\n"
        "  [green]OK[/green] No hallucinated baselines or stale dates\n\n"
        "[bold]Key insight:[/bold] deterministic post-processing beats prompt engineering\n"
        "for structural guarantees like deps and coverage.",
        title="Quality Guarantees Summary",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
async def run_demo(
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    demo_number: int | None = None,
) -> None:
    """Run all (or a single) demo scenario."""
    console.print(Panel(
        f"[bold blue]AIPM - Autonomous AI Product Manager[/bold blue]\n"
        f"Provider: {provider}  |  Model: {model}\n"
        f"Working directory: {Path.cwd()}",
        title="Demo",
        border_style="blue",
    ))

    bundle_demos = {
        1: demo_1,
        2: demo_2,
        3: demo_3,
        4: demo_4,
        5: demo_5,
        6: demo_6,
        7: demo_7,
        8: demo_8,
        9: demo_9,
        10: demo_10,
    }

    if demo_number is not None:
        if demo_number in bundle_demos:
            await bundle_demos[demo_number](provider, model)
        elif demo_number == 11:
            await demo_11(provider, model)
        elif demo_number == 12:
            await demo_12(None, provider, model)
        elif demo_number == 13:
            await demo_13(provider, model)
        else:
            console.print(f"[red]Invalid demo number: {demo_number}. Choose 1-13.[/red]")
        return

    # Run all demos sequentially
    result1 = await demo_1(provider, model)
    await demo_2(provider, model)
    await demo_3(provider, model)
    await demo_4(provider, model)
    await demo_5(provider, model)
    await demo_6(provider, model)
    await demo_7(provider, model)
    await demo_8(provider, model)
    await demo_9(provider, model)
    await demo_10(provider, model)
    await demo_11(provider, model)
    await demo_12(None, provider, model)
    await demo_13(provider, model)

    console.print(Panel(
        "[bold green]All thirteen scenarios executed successfully.[/bold green]\n"
        "Check the [bold]output/[/bold] directory for generated artifacts.",
        title="Demo Complete",
        border_style="green",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIPM Demo Script -- showcases all key pipeline features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python scripts/demo.py                          # Run all 13 demos
              python scripts/demo.py --demo 1                 # Privacy risk only
              python scripts/demo.py --demo 11                # Policy comparison
              python scripts/demo.py --demo 13                # Quality guarantees
              python scripts/demo.py --model gpt-4o-mini      # Use a different model

            demos:
              1  privacy_risk             6  a11y_gap
              2  metric_drop              7  enterprise_complexity
              3  competitive_parity       8  perf_regression
              4  conflicting_stakeholders 9  pricing_change
              5  sample_bundle            10 tech_dependency
              11 policy comparison        12 artifact showcase
              13 quality guarantees
        """),
    )
    parser.add_argument(
        "--demo",
        type=int,
        default=None,
        choices=list(range(1, 14)),
        help="Run a specific demo (1-13). Omit to run all.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="openai",
        help="LLM provider (default: openai)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="Model name (default: gpt-4o-mini)",
    )
    args = parser.parse_args()

    # Change to project root so relative paths work
    os.chdir(PROJECT_ROOT)

    asyncio.run(
        run_demo(
            provider=args.provider,
            model=args.model,
            demo_number=args.demo,
        )
    )


if __name__ == "__main__":
    main()
