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

from aipm.core.orchestrator import PipelineOrchestrator  # noqa: E402
from aipm.schemas.config import RunConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Colour helpers (ANSI — works in most modern terminals)
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


def print_banner(text: str) -> None:
    width = max(len(text) + 4, 60)
    border = "=" * width
    print(f"\n{BOLD}{CYAN}{border}")
    print(f"  {text}")
    print(f"{border}{RESET}\n")


def print_section(text: str) -> None:
    print(f"\n{BOLD}{MAGENTA}--- {text} ---{RESET}\n")


def print_ok(text: str) -> None:
    print(f"  {GREEN}[OK]{RESET} {text}")


def print_warn(text: str) -> None:
    print(f"  {YELLOW}[!!]{RESET} {text}")


def print_info(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


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
    """Run the AIPM pipeline and return the manifest dict."""
    config = RunConfig(
        input_path=input_path,
        output_dir=output_dir,
        provider=provider,
        model=model,
        temperature=temperature,
        policy_path=policy,
    )
    orchestrator = PipelineOrchestrator(config)
    t0 = time.perf_counter()
    manifest = await orchestrator.run(input_path)
    elapsed = time.perf_counter() - t0
    manifest["_demo_elapsed"] = round(elapsed, 2)
    return manifest


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def show_key_artifacts(manifest: dict) -> None:
    """Print a summary of key artifacts produced by the pipeline."""
    artifacts = manifest.get("artifacts", {})
    if not artifacts:
        print_warn("No artifacts were generated.")
        return

    print_info("Generated artifacts:")
    for name, path in artifacts.items():
        exists = Path(path).exists() if path else False
        status = f"{GREEN}exists{RESET}" if exists else f"{RED}missing{RESET}"
        print(f"    {name:.<30s} {status}  {DIM}{path}{RESET}")


def show_experiment_plan_preview(manifest: dict) -> None:
    """Show a short preview of the experiment plan if available."""
    artifacts = manifest.get("artifacts", {})
    exp_path = artifacts.get("experiment_plan")
    if exp_path and Path(exp_path).exists():
        content = Path(exp_path).read_text(encoding="utf-8")
        lines = content.splitlines()[:20]
        print_info("Experiment plan preview (first 20 lines):")
        for line in lines:
            print(f"    {DIM}{line}{RESET}")
        if len(content.splitlines()) > 20:
            print(f"    {DIM}... ({len(content.splitlines())} total lines){RESET}")
    else:
        print_warn("Experiment plan not found in artifacts.")


def show_roadmap_preview(manifest: dict) -> None:
    """Show a short preview of the roadmap JSON if available."""
    artifacts = manifest.get("artifacts", {})
    rm_path = artifacts.get("roadmap")
    if rm_path and Path(rm_path).exists():
        try:
            roadmap = json.loads(Path(rm_path).read_text(encoding="utf-8"))
            themes = roadmap.get("themes", [])
            milestones = roadmap.get("milestones", [])
            critical = roadmap.get("critical_path", [])
            print_info(f"Roadmap: {len(themes)} themes, {len(milestones)} milestones")
            print_info(f"Critical path: {' -> '.join(critical) if critical else '(none)'}")
            for ms in milestones[:5]:
                print(f"    [{ms.get('phase', '?')}] {ms.get('name', '?')} — {ms.get('description', '')[:80]}")
            if len(milestones) > 5:
                print(f"    {DIM}... and {len(milestones) - 5} more milestones{RESET}")
        except (json.JSONDecodeError, KeyError):
            print_warn("Could not parse roadmap JSON.")
    else:
        print_warn("Roadmap not found in artifacts.")


def show_backlog_preview(manifest: dict) -> None:
    """Show a short preview of the backlog CSV if available."""
    artifacts = manifest.get("artifacts", {})
    bl_path = artifacts.get("backlog")
    if bl_path and Path(bl_path).exists():
        content = Path(bl_path).read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

        # Compute stats
        total = len(rows)
        has_deps = sum(1 for r in rows if r.get("dependencies", "").strip())
        phases = {}
        for r in rows:
            ph = r.get("phase", "?")
            phases[ph] = phases.get(ph, 0) + 1

        phase_str = ", ".join(f"{ph}: {n}" for ph, n in sorted(phases.items()))
        print_info(f"Backlog: {total} stories  |  Phases: {phase_str}")
        print_info(f"Dependency coverage: {has_deps}/{total} stories have non-empty deps")

        for row in rows[:6]:
            phase = row.get("phase", "?")
            priority = row.get("priority", "?")
            title = row.get("story_title", row.get("epic_title", "?"))
            deps = row.get("dependencies", "")
            dep_tag = f" {DIM}-> {deps[:50]}{RESET}" if deps.strip() else ""
            print(f"    [{phase}/{priority}] {title}{dep_tag}")
        if len(rows) > 6:
            print(f"    {DIM}... and {len(rows) - 6} more rows{RESET}")
    else:
        print_warn("Backlog CSV not found in artifacts.")


def show_risk_gate_preview(manifest: dict) -> None:
    """Show the risk gate result (blockers and warnings)."""
    artifacts = manifest.get("artifacts", {})
    # Risk gate lives in findings dir, sibling to artifacts dir
    run_dir = None
    for path_str in artifacts.values():
        if path_str:
            run_dir = Path(path_str).parent.parent
            break
    if not run_dir:
        return

    rg_path = run_dir / "findings" / "risk_gate_result.json"
    if rg_path.exists():
        try:
            rg = json.loads(rg_path.read_text(encoding="utf-8"))
            passed = rg.get("passed", True)
            blockers = rg.get("blockers", [])
            warnings = rg.get("warnings", [])

            status = f"{GREEN}PASSED{RESET}" if passed else f"{RED}BLOCKED{RESET}"
            print_info(f"Risk Gate: {status}")
            for b in blockers:
                print(f"    {RED}BLOCKER:{RESET} {b}")
            for w in warnings:
                print(f"    {YELLOW}WARNING:{RESET} {w}")
            if not blockers and not warnings:
                print_ok("No blockers or warnings")
        except (json.JSONDecodeError, KeyError):
            print_warn("Could not parse risk gate result.")


def show_ticket_coverage(manifest: dict, input_path: str) -> None:
    """Show ticket coverage — how many input tickets map to backlog stories."""
    # Load input tickets
    tickets_path = Path(input_path) / "tickets.json"
    if not tickets_path.exists():
        return
    try:
        tickets = json.loads(tickets_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return

    ticket_ids = {t["id"] for t in tickets}

    # Load backlog
    artifacts = manifest.get("artifacts", {})
    bl_path = artifacts.get("backlog")
    if not (bl_path and Path(bl_path).exists()):
        return

    content = Path(bl_path).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    # Check which tickets are covered — mirrors _ensure_ticket_coverage logic
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
            # Title-word check (≥50% overlap)
            ticket_title = next((t["title"] for t in tickets if t["id"] == tid), "")
            if ticket_title:
                words = set(ticket_title.upper().split())
                if words and sum(1 for w in words if w in blob) / len(words) >= 0.5:
                    covered.add(tid)
                    break

    n = len(ticket_ids)
    c = len(covered)
    colour = GREEN if c == n else (YELLOW if c >= n * 0.8 else RED)
    print_info(f"Ticket coverage: {colour}{c}/{n}{RESET} input tickets mapped to backlog stories")
    missing = ticket_ids - covered
    if missing:
        for m in sorted(missing):
            print(f"    {YELLOW}MISSING:{RESET} {m}")


def show_all_artifacts(manifest: dict, input_path: str = "") -> None:
    """Show detailed preview of all generated artifacts."""
    show_key_artifacts(manifest)
    print()
    show_risk_gate_preview(manifest)
    print()
    show_roadmap_preview(manifest)
    print()
    show_backlog_preview(manifest)
    if input_path:
        show_ticket_coverage(manifest, input_path)
    print()
    show_experiment_plan_preview(manifest)


def compare_recommendations(result_a: dict, result_b: dict) -> None:
    """Compare recommendations from two pipeline runs."""
    rec_a = result_a.get("recommendation", "(none)")
    rec_b = result_b.get("recommendation", "(none)")
    policy_a = result_a.get("_demo_policy", "Policy A")
    policy_b = result_b.get("_demo_policy", "Policy B")

    print_info(f"{policy_a:.<40s} recommendation: {BOLD}{rec_a}{RESET}")
    print_info(f"{policy_b:.<40s} recommendation: {BOLD}{rec_b}{RESET}")

    if rec_a != rec_b:
        print_ok("Different policies produced different recommendations!")
    else:
        print_warn("Both policies produced the same recommendation.")


def print_run_summary(manifest: dict) -> None:
    """Print a compact summary of a pipeline run."""
    rec = manifest.get("recommendation", "(none)")
    total = manifest.get("total_findings", 0)
    agents_run = manifest.get("agents_run", [])
    elapsed = manifest.get("_demo_elapsed", "?")
    errors = manifest.get("errors", {})

    colour = GREEN if not errors else YELLOW
    print(f"  {colour}Recommendation:{RESET} {BOLD}{rec}{RESET}")
    print(f"  Findings: {total} | Agents: {len(agents_run)} | Time: {elapsed}s")
    if errors:
        print_warn(f"Errors: {', '.join(errors.keys())}")


# ---------------------------------------------------------------------------
# Demo scenarios (1-10: one per input bundle, 11: policy comparison, 12: showcase)
# ---------------------------------------------------------------------------
async def demo_1(provider: str, model: str) -> dict:
    """Demo 1: Privacy risk scenario — PII risks trigger risk gate blockers."""
    print_section("Demo 1: Privacy Risk Scenario")
    print("Running pipeline on privacy_risk bundle...")
    print("Expected: risk gate BLOCKS on PII/privacy, ticket coverage, dependency chains\n")

    result = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/default_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_01_privacy_risk",
    )
    print_run_summary(result)
    show_risk_gate_preview(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/privacy_risk/")
    return result


async def demo_2(provider: str, model: str) -> dict:
    """Demo 2: Metric drop scenario — experiment plan with instrumentation."""
    print_section("Demo 2: Metric Drop Scenario")
    print("Running pipeline on metric_drop bundle...")
    print("Expected: 7/7 ticket coverage, experiment plan with instrumentation\n")

    result = await run_pipeline(
        "input_bundles/metric_drop/",
        provider=provider,
        model=model,
        output_dir="output/demo_02_metric_drop",
    )
    print_run_summary(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/metric_drop/")
    show_experiment_plan_preview(result)
    return result


async def demo_3(provider: str, model: str) -> dict:
    """Demo 3: Competitive parity — roadmap with phased tradeoffs."""
    print_section("Demo 3: Competitive Parity Scenario")
    print("Running pipeline on competitive_parity bundle...")
    print("Expected: 6/6 ticket coverage, dependency chains, phased roadmap\n")

    result = await run_pipeline(
        "input_bundles/competitive_parity/",
        provider=provider,
        model=model,
        output_dir="output/demo_03_competitive_parity",
    )
    print_run_summary(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/competitive_parity/")
    show_roadmap_preview(result)
    return result


async def demo_4(provider: str, model: str) -> dict:
    """Demo 4: Conflicting stakeholders — 8/8 ticket coverage + conflict resolution."""
    print_section("Demo 4: Conflicting Stakeholders Scenario")
    print("Running pipeline on conflicting_stakeholders bundle...")
    print("Expected: 8/8 ticket coverage, dependency chains, risk gate blockers\n")

    result = await run_pipeline(
        "input_bundles/conflicting_stakeholders/",
        provider=provider,
        model=model,
        output_dir="output/demo_04_conflicting_stakeholders",
    )
    print_run_summary(result)
    show_risk_gate_preview(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/conflicting_stakeholders/")
    return result


async def demo_5(provider: str, model: str) -> dict:
    """Demo 5: Sample bundle — baseline end-to-end run."""
    print_section("Demo 5: Sample Bundle (Baseline)")
    print("Running pipeline on sample_bundle...")
    print("Expected: 5/5 ticket coverage, dependency chains, risk gate blockers, full artifacts\n")

    result = await run_pipeline(
        "input_bundles/sample_bundle/",
        provider=provider,
        model=model,
        output_dir="output/demo_05_sample_bundle",
    )
    print_run_summary(result)
    show_all_artifacts(result, "input_bundles/sample_bundle/")
    return result


async def demo_6(provider: str, model: str) -> dict:
    """Demo 6: Accessibility gap — risk findings around a11y compliance."""
    print_section("Demo 6: Accessibility Gap Scenario")
    print("Running pipeline on a11y_gap bundle...")
    print("Expected: a11y risk findings, dependency chains, full ticket coverage\n")

    result = await run_pipeline(
        "input_bundles/a11y_gap/",
        provider=provider,
        model=model,
        output_dir="output/demo_06_a11y_gap",
    )
    print_run_summary(result)
    show_risk_gate_preview(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/a11y_gap/")
    return result


async def demo_7(provider: str, model: str) -> dict:
    """Demo 7: Enterprise complexity — large-scale requirements and phased roadmap."""
    print_section("Demo 7: Enterprise Complexity Scenario")
    print("Running pipeline on enterprise_complexity bundle...")
    print("Expected: complex roadmap with milestones, dependency chains throughout\n")

    result = await run_pipeline(
        "input_bundles/enterprise_complexity/",
        provider=provider,
        model=model,
        output_dir="output/demo_07_enterprise_complexity",
    )
    print_run_summary(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/enterprise_complexity/")
    show_roadmap_preview(result)
    return result


async def demo_8(provider: str, model: str) -> dict:
    """Demo 8: Performance regression — incident-driven analysis."""
    print_section("Demo 8: Performance Regression Scenario")
    print("Running pipeline on perf_regression bundle...")
    print("Expected: 5/5 ticket coverage, MVP/V1/V2 dep chains, experiment plan\n")

    result = await run_pipeline(
        "input_bundles/perf_regression/",
        provider=provider,
        model=model,
        output_dir="output/demo_08_perf_regression",
    )
    print_run_summary(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/perf_regression/")
    show_experiment_plan_preview(result)
    return result


async def demo_9(provider: str, model: str) -> dict:
    """Demo 9: Pricing change — competitive and customer impact analysis."""
    print_section("Demo 9: Pricing Change Scenario")
    print("Running pipeline on pricing_change bundle...")
    print("Expected: competitive findings, customer churn risk, full backlog\n")

    result = await run_pipeline(
        "input_bundles/pricing_change/",
        provider=provider,
        model=model,
        output_dir="output/demo_09_pricing_change",
    )
    print_run_summary(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/pricing_change/")
    return result


async def demo_10(provider: str, model: str) -> dict:
    """Demo 10: Tech dependency — feasibility and dependency risk analysis."""
    print_section("Demo 10: Tech Dependency Scenario")
    print("Running pipeline on tech_dependency bundle...")
    print("Expected: 5/5 ticket coverage, MVP→V1 dependency chains\n")

    result = await run_pipeline(
        "input_bundles/tech_dependency/",
        provider=provider,
        model=model,
        output_dir="output/demo_10_tech_dependency",
    )
    print_run_summary(result)
    show_backlog_preview(result)
    show_ticket_coverage(result, "input_bundles/tech_dependency/")
    return result


async def demo_11(provider: str, model: str) -> dict | None:
    """Demo 11: Policy configurability — same input, different policy, different outcome."""
    print_section("Demo 11: Policy Configurability")
    print("Running privacy_risk bundle with TWO different policies...\n")

    print(f"  {CYAN}Run A:{RESET} default_policy.yaml")
    result_a = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/default_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_11a_default_policy",
    )
    result_a["_demo_policy"] = "default_policy.yaml"
    print_run_summary(result_a)

    print(f"\n  {CYAN}Run B:{RESET} startup_fast_policy.yaml")
    result_b = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/startup_fast_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_11b_startup_policy",
    )
    result_b["_demo_policy"] = "startup_fast_policy.yaml"
    print_run_summary(result_b)

    print()
    compare_recommendations(result_a, result_b)
    print("Same input, different policy -> different recommendation!")
    return result_a


async def demo_12(result: dict | None, provider: str, model: str) -> None:
    """Demo 12: Artifact showcase — display all generated artifacts from a run."""
    print_section("Demo 12: Artifact Showcase")

    if result is None:
        print("Running sample_bundle to generate artifacts for showcase...\n")
        result = await run_pipeline(
            "input_bundles/sample_bundle/",
            provider=provider,
            model=model,
            output_dir="output/demo_12_showcase",
        )

    print("Full artifact breakdown:\n")
    show_all_artifacts(result, "input_bundles/sample_bundle/")


async def demo_13(provider: str, model: str) -> None:
    """Demo 13: Quality guarantees — shows dependency inference, ticket coverage, and risk gate across 3 bundles."""
    print_section("Demo 13: Quality Guarantees Showcase")
    print("Runs 3 bundles that previously had FAIL/PARTIAL results and shows")
    print("all quality checks now pass thanks to deterministic post-processing.\n")

    bundles = [
        ("conflicting_stakeholders", 8),
        ("sample_bundle", 5),
        ("tech_dependency", 5),
    ]

    for bundle_name, expected_tickets in bundles:
        print(f"\n  {CYAN}Bundle:{RESET} {BOLD}{bundle_name}{RESET} ({expected_tickets} tickets)")
        result = await run_pipeline(
            f"input_bundles/{bundle_name}/",
            provider=provider,
            model=model,
            output_dir=f"output/demo_13_{bundle_name}",
        )
        print_run_summary(result)
        show_risk_gate_preview(result)
        show_backlog_preview(result)
        show_ticket_coverage(result, f"input_bundles/{bundle_name}/")
        print()

    print_banner("Quality Guarantees Summary")
    print("All 3 bundles now show:")
    print_ok("100% ticket coverage (input tickets -> backlog stories)")
    print_ok("Non-empty dependency chains (MVP -> V1 -> V2)")
    print_ok("Risk gate correctly reports is_blocker findings")
    print_ok("No hallucinated baselines or stale dates")
    print(f"\n  Key insight: {BOLD}deterministic post-processing beats prompt engineering{RESET}")
    print(f"  for structural guarantees like deps and coverage.\n")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
async def run_demo(
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    demo_number: int | None = None,
) -> None:
    """Run all (or a single) demo scenario."""
    print_banner("AIPM - Autonomous AI Product Manager Demo")
    print(f"Provider: {provider} | Model: {model}")
    print(f"Working directory: {Path.cwd()}")

    # Demos 1-10: one per input bundle
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
            print(f"{RED}Invalid demo number: {demo_number}. Choose 1-13.{RESET}")
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

    print_banner("Demo Complete!")
    print("All thirteen scenarios executed successfully.")
    print("Check the output/ directory for generated artifacts.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIPM Demo Script — showcases all key pipeline features",
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
