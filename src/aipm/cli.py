"""Command-line interface for the AIPM pipeline."""

import asyncio
import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from aipm.core.orchestrator import PipelineOrchestrator
from aipm.core.validators import (
    generate_evidence_index,
    validate_agent_output,
    validate_context_packet,
    validate_findings_consistency,
)
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import AgentOutput

app = typer.Typer(name="aipm", help="Autonomous AI Product Manager (AIPM)")
console = Console()


def _setup_logging(verbose: bool) -> None:
    """Configure logging level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def run(
    input_path: str = typer.Argument(..., help="Path to input bundle directory or prompt file"),
    output_dir: str = typer.Option("output", help="Output directory"),
    provider: str = typer.Option("openai", help="LLM provider"),
    model: str = typer.Option("gpt-4o", help="Model to use"),
    temperature: float = typer.Option(0.2, help="LLM temperature"),
    policy: str = typer.Option("src/aipm/policies/default_policy.yaml", help="Policy YAML path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Run the full AIPM pipeline on an input bundle."""
    _setup_logging(verbose)

    console.print(
        Panel(
            f"[bold blue]AIPM Pipeline[/bold blue]\n"
            f"Input: {input_path}\n"
            f"Provider: {provider} / {model}\n"
            f"Output: {output_dir}",
            title="Starting Pipeline",
        )
    )

    config = RunConfig(
        input_path=input_path,
        output_dir=output_dir,
        provider=provider,
        model=model,
        temperature=temperature,
        policy_path=policy,
    )

    orchestrator = PipelineOrchestrator(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running AIPM pipeline...", total=None)
        manifest = asyncio.run(orchestrator.run(input_path))
        progress.update(task, description="Pipeline complete!")

    _display_manifest(manifest)


@app.command()
def validate(
    output_path: str = typer.Argument(..., help="Path to pipeline run output directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Validate a pipeline run's outputs."""
    _setup_logging(verbose)

    run_dir = Path(output_path)
    if not run_dir.exists():
        console.print(f"[red]Output path not found: {output_path}[/red]")
        raise typer.Exit(1)

    findings_dir = run_dir / "findings"
    if not findings_dir.exists():
        console.print(f"[red]No findings directory in: {output_path}[/red]")
        raise typer.Exit(1)

    # Load context packet if available
    context_packet = None
    context_path = run_dir / "context_packet.json"
    if context_path.exists():
        try:
            data = json.loads(context_path.read_text(encoding="utf-8"))
            context_packet = ContextPacket.model_validate(data)
        except Exception as exc:
            console.print(f"[yellow]Warning: Could not load context packet: {exc}[/yellow]")

    # Validate context packet
    if context_packet:
        console.print("\n[bold]Context Packet Validation[/bold]")
        cp_warnings = validate_context_packet(context_packet)
        if cp_warnings:
            for w in cp_warnings:
                console.print(f"  [yellow]⚠ {w}[/yellow]")
        else:
            console.print("  [green]✓ Context packet is valid[/green]")

    # Validate each agent output
    all_findings = []
    console.print("\n[bold]Agent Output Validation[/bold]")

    for json_file in sorted(findings_dir.glob("*.json")):
        if json_file.name in ("risk_gate_result.json", "requirements_backlog.json"):
            continue

        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            agent_output = AgentOutput.model_validate(data)
        except Exception as exc:
            console.print(f"  [red]✗ {json_file.name}: Failed to parse — {exc}[/red]")
            continue

        warnings = validate_agent_output(agent_output, context_packet)
        all_findings.extend(agent_output.findings)

        if warnings:
            console.print(f"  [yellow]⚠ {json_file.name}: {len(warnings)} warnings[/yellow]")
            for w in warnings:
                console.print(f"    - {w}")
        else:
            console.print(f"  [green]✓ {json_file.name}: {len(agent_output.findings)} findings, valid[/green]")

    # Cross-agent consistency
    if all_findings:
        console.print("\n[bold]Cross-Agent Consistency[/bold]")
        consistency = validate_findings_consistency(all_findings)

        table = Table(title="Findings Summary")
        table.add_column("Metric", style="bold")
        table.add_column("Value")

        table.add_row("Total Findings", str(consistency["total_findings"]))
        table.add_row("By Type", ", ".join(f"{k}: {v}" for k, v in consistency["by_type"].items()))
        table.add_row("By Agent", ", ".join(f"{k}: {v}" for k, v in consistency["by_agent"].items()))
        table.add_row("Potential Duplicates", str(len(consistency["potential_duplicates"])))
        console.print(table)

        if consistency["potential_duplicates"]:
            console.print("\n[yellow]Potential Duplicates:[/yellow]")
            for dup in consistency["potential_duplicates"]:
                console.print(f"  - {dup['finding_a']} ↔ {dup['finding_b']} (similarity: {dup['similarity']:.1%})")

        # Evidence index
        evidence_index = generate_evidence_index(all_findings)
        console.print(f"\n[bold]Evidence Index:[/bold] {len(evidence_index)} sources referenced")

    # Risk gate result
    gate_path = findings_dir / "risk_gate_result.json"
    if gate_path.exists():
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        status = "[green]PASSED[/green]" if gate["passed"] else "[red]FAILED[/red]"
        console.print(f"\n[bold]Risk Gate:[/bold] {status}")
        for b in gate.get("blockers", []):
            console.print(f"  [red]✗ {b}[/red]")
        for w in gate.get("warnings", []):
            console.print(f"  [yellow]⚠ {w}[/yellow]")


@app.command()
def prompt(
    prompt_text: str = typer.Argument(..., help="Product idea as text"),
    output_dir: str = typer.Option("output", help="Output directory"),
    provider: str = typer.Option("openai", help="LLM provider"),
    model: str = typer.Option("gpt-4o", help="Model to use"),
    policy: str = typer.Option("src/aipm/policies/default_policy.yaml", help="Policy YAML path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Run AIPM from a simple text prompt instead of a bundle."""
    _setup_logging(verbose)

    console.print(
        Panel(
            f"[bold blue]AIPM Pipeline (Prompt Mode)[/bold blue]\n"
            f"Prompt: {prompt_text[:80]}{'...' if len(prompt_text) > 80 else ''}\n"
            f"Provider: {provider} / {model}",
            title="Starting Pipeline",
        )
    )

    config = RunConfig(
        input_path=prompt_text,
        output_dir=output_dir,
        provider=provider,
        model=model,
        policy_path=policy,
    )

    orchestrator = PipelineOrchestrator(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running AIPM pipeline...", total=None)
        manifest = asyncio.run(orchestrator.run(prompt_text))
        progress.update(task, description="Pipeline complete!")

    _display_manifest(manifest)


def _display_manifest(manifest: dict) -> None:
    """Display the pipeline run manifest as a Rich summary."""
    # Summary panel
    console.print(
        Panel(
            f"[bold green]Pipeline Complete[/bold green]\n"
            f"Run ID: {manifest['run_id']}\n"
            f"Duration: {manifest['duration_seconds']}s\n"
            f"Total Findings: {manifest['total_findings']}",
            title="Results",
        )
    )

    # Agents table
    table = Table(title="Agent Results")
    table.add_column("Agent", style="bold")
    table.add_column("Status")

    for agent_id in manifest.get("agents_completed", []):
        table.add_row(agent_id, "[green]completed[/green]")
    for agent_id in manifest.get("agents_skipped", []):
        reason = manifest.get("errors", {}).get(agent_id, "skipped")
        table.add_row(agent_id, f"[yellow]{reason}[/yellow]")

    console.print(table)

    # Findings by type
    if manifest.get("findings_by_type"):
        findings_table = Table(title="Findings by Type")
        findings_table.add_column("Type", style="bold")
        findings_table.add_column("Count")

        for ftype, count in sorted(manifest["findings_by_type"].items()):
            findings_table.add_row(ftype, str(count))
        console.print(findings_table)

    # Output files
    output_files = manifest.get("output_files", {})
    if output_files.get("findings"):
        console.print(f"\n[bold]Finding files:[/bold] {len(output_files['findings'])}")
    if output_files.get("artifacts"):
        console.print(f"[bold]Artifact files:[/bold] {len(output_files['artifacts'])}")

    # Warnings
    if manifest.get("bundle_warnings"):
        console.print("\n[yellow]Bundle Warnings:[/yellow]")
        for w in manifest["bundle_warnings"]:
            console.print(f"  ⚠ {w}")

    # Errors
    if manifest.get("errors"):
        console.print("\n[yellow]Errors:[/yellow]")
        for agent_id, err in manifest["errors"].items():
            console.print(f"  {agent_id}: {err}")


if __name__ == "__main__":
    app()
