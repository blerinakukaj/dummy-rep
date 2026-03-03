"""Automated demo script showcasing all key AIPM pipeline features.

Runs five demonstration scenarios that exercise different input bundles,
policy configurations, and output artifacts.

Usage:
    python scripts/demo.py                 # Run all demos
    python scripts/demo.py --demo 1        # Run a specific demo (1-5)
    python scripts/demo.py --provider anthropic --model claude-3-5-sonnet-20241022
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
    model: str = "gpt-4o",
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
        print_info(f"Backlog: {len(rows)} stories")
        for row in rows[:5]:
            phase = row.get("phase", "?")
            priority = row.get("priority", "?")
            title = row.get("story_title", row.get("epic_title", "?"))
            print(f"    [{phase}/{priority}] {title}")
        if len(rows) > 5:
            print(f"    {DIM}... and {len(rows) - 5} more rows{RESET}")
    else:
        print_warn("Backlog CSV not found in artifacts.")


def show_all_artifacts(manifest: dict) -> None:
    """Show detailed preview of all generated artifacts."""
    show_key_artifacts(manifest)
    print()
    show_roadmap_preview(manifest)
    print()
    show_backlog_preview(manifest)
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
# Demo scenarios
# ---------------------------------------------------------------------------
async def demo_1(provider: str, model: str) -> dict:
    """Demo 1: Privacy risk scenario — expected: 'validate_first' due to PII risks."""
    print_section("Demo 1: Privacy Risk Scenario")
    print("Running pipeline on privacy_risk bundle...")
    print("Expected: 'validate_first' due to PII/privacy risks\n")

    result = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/default_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_1_privacy_risk",
    )
    print_run_summary(result)
    show_key_artifacts(result)
    return result


async def demo_2(provider: str, model: str) -> dict:
    """Demo 2: Metric drop scenario — experiment plan with instrumentation."""
    print_section("Demo 2: Metric Drop Scenario")
    print("Running pipeline on metric_drop bundle...")
    print("Expected: experiment plan with detailed instrumentation proposal\n")

    result = await run_pipeline(
        "input_bundles/metric_drop/",
        provider=provider,
        model=model,
        output_dir="output/demo_2_metric_drop",
    )
    print_run_summary(result)
    show_experiment_plan_preview(result)
    return result


async def demo_3(provider: str, model: str) -> dict:
    """Demo 3: Competitive parity — roadmap with phased tradeoffs."""
    print_section("Demo 3: Competitive Parity Scenario")
    print("Running pipeline on competitive_parity bundle...")
    print("Expected: roadmap with phased approach and competitive context\n")

    result = await run_pipeline(
        "input_bundles/competitive_parity/",
        provider=provider,
        model=model,
        output_dir="output/demo_3_competitive_parity",
    )
    print_run_summary(result)
    show_roadmap_preview(result)
    return result


async def demo_4(provider: str, model: str) -> dict | None:
    """Demo 4: Policy configurability — same input, different policy, different outcome."""
    print_section("Demo 4: Policy Configurability")
    print("Running privacy_risk bundle with TWO different policies...\n")

    print(f"  {CYAN}Run A:{RESET} default_policy.yaml")
    result_a = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/default_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_4a_default_policy",
    )
    result_a["_demo_policy"] = "default_policy.yaml"
    print_run_summary(result_a)

    print(f"\n  {CYAN}Run B:{RESET} startup_fast_policy.yaml")
    result_b = await run_pipeline(
        "input_bundles/privacy_risk/",
        policy="src/aipm/policies/startup_fast_policy.yaml",
        provider=provider,
        model=model,
        output_dir="output/demo_4b_startup_policy",
    )
    result_b["_demo_policy"] = "startup_fast_policy.yaml"
    print_run_summary(result_b)

    print()
    compare_recommendations(result_a, result_b)
    print("Same input, different policy -> different recommendation!")
    return result_a


async def demo_5(result: dict | None, provider: str, model: str) -> None:
    """Demo 5: Artifact showcase — display all generated artifacts from a run."""
    print_section("Demo 5: Artifact Showcase")

    if result is None:
        print("Running sample_bundle to generate artifacts for showcase...\n")
        result = await run_pipeline(
            "input_bundles/sample_bundle/",
            provider=provider,
            model=model,
            output_dir="output/demo_5_showcase",
        )

    print("Full artifact breakdown:\n")
    show_all_artifacts(result)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
async def run_demo(
    provider: str = "openai",
    model: str = "gpt-4o",
    demo_number: int | None = None,
) -> None:
    """Run all (or a single) demo scenario."""
    print_banner("AIPM - Autonomous AI Product Manager Demo")
    print(f"Provider: {provider} | Model: {model}")
    print(f"Working directory: {Path.cwd()}")

    demos = {
        1: demo_1,
        2: demo_2,
        3: demo_3,
    }

    if demo_number is not None:
        if demo_number in demos:
            await demos[demo_number](provider, model)
        elif demo_number == 4:
            await demo_4(provider, model)
        elif demo_number == 5:
            await demo_5(None, provider, model)
        else:
            print(f"{RED}Invalid demo number: {demo_number}. Choose 1-5.{RESET}")
        return

    # Run all demos sequentially
    result1 = await demo_1(provider, model)
    await demo_2(provider, model)
    await demo_3(provider, model)
    await demo_4(provider, model)
    await demo_5(result1, provider, model)

    print_banner("Demo Complete!")
    print("All five scenarios executed successfully.")
    print("Check the output/ directory for generated artifacts.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIPM Demo Script — showcases all key pipeline features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python scripts/demo.py                          # Run all demos
              python scripts/demo.py --demo 1                 # Privacy risk only
              python scripts/demo.py --demo 4                 # Policy comparison
              python scripts/demo.py --provider anthropic \\
                  --model claude-3-5-sonnet-20241022           # Use Anthropic
        """),
    )
    parser.add_argument(
        "--demo",
        type=int,
        default=None,
        choices=[1, 2, 3, 4, 5],
        help="Run a specific demo (1-5). Omit to run all.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="openai",
        help="LLM provider: openai or anthropic (default: openai)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o",
        help="Model name (default: gpt-4o)",
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
