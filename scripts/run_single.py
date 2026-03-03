"""Run the AIPM pipeline on a single input bundle with formatted output.

Usage:
    python scripts/run_single.py input_bundles/sample_bundle/
    python scripts/run_single.py input_bundles/privacy_risk/ --policy src/aipm/policies/strict_privacy_policy.yaml
    python scripts/run_single.py input_bundles/metric_drop/ --model gpt-4o-mini
    python scripts/run_single.py --prompt "A mobile app for tracking daily water intake"
"""

import argparse
import asyncio
import os
import sys
import textwrap
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from aipm.core.orchestrator import PipelineOrchestrator  # noqa: E402
from aipm.schemas.config import RunConfig  # noqa: E402

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def _print_header(config: RunConfig, input_path: str) -> None:
    border = "=" * 60
    print(f"\n{BOLD}{CYAN}{border}")
    print("  AIPM Pipeline — Single Run")
    print(f"{border}{RESET}")
    print(f"  Input:    {input_path}")
    print(f"  Provider: {config.provider} / {config.model}")
    print(f"  Policy:   {config.policy_path}")
    print(f"  Output:   {config.output_dir}")
    print(f"{CYAN}{border}{RESET}\n")


def _print_results(manifest: dict, elapsed: float) -> None:
    rec = manifest.get("recommendation", "(none)")
    total = manifest.get("total_findings", 0)
    agents = manifest.get("agents_run", [])
    errors = manifest.get("errors", {})
    findings_by_type = manifest.get("findings_by_type", {})

    border = "-" * 60
    print(f"\n{BOLD}{GREEN}{border}")
    print("  Pipeline Complete")
    print(f"{border}{RESET}")
    print(f"  Run ID:         {manifest.get('run_id', '?')}")
    print(f"  Duration:       {elapsed:.1f}s")
    print(f"  Recommendation: {BOLD}{rec}{RESET}")
    print(f"  Total Findings: {total}")
    print(f"  Agents Run:     {', '.join(agents)}")

    if findings_by_type:
        print(f"\n  {BOLD}Findings by type:{RESET}")
        for ftype, count in sorted(findings_by_type.items()):
            print(f"    {ftype:.<25s} {count}")

    # Artifacts
    artifacts = manifest.get("artifacts", {})
    if artifacts:
        print(f"\n  {BOLD}Artifacts:{RESET}")
        for name, path in artifacts.items():
            exists = Path(path).exists() if path else False
            marker = f"{GREEN}OK{RESET}" if exists else f"{RED}MISSING{RESET}"
            print(f"    [{marker}] {name}: {DIM}{path}{RESET}")

    # Output files
    output_files = manifest.get("output_files", {})
    n_findings = len(output_files.get("findings", []))
    n_artifacts = len(output_files.get("artifacts", []))
    print(f"\n  Output files: {n_findings} findings, {n_artifacts} artifacts")
    if output_files.get("context_packet"):
        print(f"  Context packet: {DIM}{output_files['context_packet']}{RESET}")

    # Errors
    if errors:
        print(f"\n  {YELLOW}Errors:{RESET}")
        for agent_id, err in errors.items():
            print(f"    {RED}{agent_id}:{RESET} {err}")

    # Warnings
    warnings = manifest.get("bundle_warnings", [])
    if warnings:
        print(f"\n  {YELLOW}Bundle Warnings:{RESET}")
        for w in warnings:
            print(f"    {w}")

    print()


async def run_single(
    input_path: str,
    provider: str = "openai",
    model: str = "gpt-4o",
    policy: str = "src/aipm/policies/default_policy.yaml",
    output_dir: str = "output",
    temperature: float = 0.2,
    verbose: bool = False,
) -> dict:
    """Run a single pipeline invocation and display results."""
    import logging

    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = RunConfig(
        input_path=input_path,
        output_dir=output_dir,
        provider=provider,
        model=model,
        temperature=temperature,
        policy_path=policy,
    )

    _print_header(config, input_path)
    print("Running pipeline...")

    t0 = time.perf_counter()
    orchestrator = PipelineOrchestrator(config)
    manifest = await orchestrator.run(input_path)
    elapsed = time.perf_counter() - t0

    _print_results(manifest, elapsed)

    # Save a copy of the manifest for easy inspection
    manifest_out = Path(config.output_dir) / config.run_id / "run_manifest.json"
    if manifest_out.exists():
        print(f"Manifest saved: {DIM}{manifest_out}{RESET}")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run AIPM pipeline on a single input bundle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python scripts/run_single.py input_bundles/sample_bundle/
              python scripts/run_single.py input_bundles/privacy_risk/ \\
                  --policy src/aipm/policies/strict_privacy_policy.yaml
              python scripts/run_single.py --prompt "An AI-powered code reviewer"
        """),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "input_path",
        nargs="?",
        default=None,
        help="Path to input bundle directory or prompt file",
    )
    group.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Run from a plain-text product idea instead of a bundle",
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
        default="gpt-4o",
        help="Model name (default: gpt-4o)",
    )
    parser.add_argument(
        "--policy",
        type=str,
        default="src/aipm/policies/default_policy.yaml",
        help="Path to policy YAML file",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="LLM temperature (default: 0.2)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    # Change to project root so relative paths work
    os.chdir(PROJECT_ROOT)

    input_path = args.prompt if args.prompt else args.input_path

    asyncio.run(
        run_single(
            input_path=input_path,
            provider=args.provider,
            model=args.model,
            policy=args.policy,
            output_dir=args.output_dir,
            temperature=args.temperature,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    main()
