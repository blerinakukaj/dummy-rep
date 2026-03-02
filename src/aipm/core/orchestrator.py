"""Pipeline orchestrator — runs all agents in sequence/parallel and collects outputs."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aipm.agents.competitive_agent import CompetitiveAgent
from aipm.agents.customer_agent import CustomerInsightsAgent
from aipm.agents.intake_agent import IntakeAgent
from aipm.agents.metrics_agent import MetricsAgent
from aipm.agents.requirements_agent import RequirementsAgent
from aipm.core.config import ensure_output_dirs, get_llm_client
from aipm.core.loader import load_bundle, load_prompt, validate_bundle
from aipm.core.policy import PolicyPack, load_policy
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import AgentOutput, Finding

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Main pipeline runner that executes all agents in sequence/parallel."""

    def __init__(self, run_config: RunConfig) -> None:
        self.run_config = run_config
        self.llm_client = get_llm_client(run_config.provider)
        self.policy_pack = load_policy(run_config.policy_path)
        self.run_dir = ensure_output_dirs(run_config)
        self.outputs: list[AgentOutput] = []
        self.errors: dict[str, str] = {}

        logger.info(
            "Orchestrator initialized — run_id=%s, provider=%s, model=%s",
            run_config.run_id, run_config.provider, run_config.model,
        )

    async def run(self, input_path: str) -> dict:
        """Execute the full AIPM pipeline.

        Args:
            input_path: Path to input bundle directory or a plain text prompt.

        Returns:
            Dict with run_id, output file paths, errors, and summary.
        """
        start_time = datetime.now(timezone.utc)
        logger.info("Pipeline started — run_id=%s", self.run_config.run_id)

        # Step 1: Load input bundle or prompt
        bundle = self._load_input(input_path)
        warnings = validate_bundle(bundle)
        if warnings:
            logger.warning("Bundle has %d validation warnings", len(warnings))

        # Create an initial empty context packet for the intake agent
        empty_context = ContextPacket(
            run_id=self.run_config.run_id,
            product_name=bundle.get("product_name", ""),
            product_description=bundle.get("description", ""),
        )

        # Step 2: Run IntakeAgent → get ContextPacket
        context_packet = await self._run_intake(bundle, empty_context)

        # Step 3: Run parallel — CustomerInsights, Competitive, Metrics
        step3_outputs = await self._run_parallel_step3(context_packet)

        # Step 4: Run parallel — Requirements, Feasibility (depend on Step 3)
        step4_outputs = await self._run_parallel_step4(context_packet)

        # Step 5: Run RiskAgent
        step5_output = await self._run_risk_agent(context_packet)

        # Step 6: Run LeadPMAgent (collects all findings)
        step6_output = await self._run_lead_pm_agent(context_packet)

        # Step 7: Collect results and save manifest
        all_findings = self._collect_all_findings(self.outputs)
        end_time = datetime.now(timezone.utc)
        duration_seconds = (end_time - start_time).total_seconds()

        manifest = self._build_manifest(all_findings, duration_seconds, warnings)
        manifest_path = self._save_manifest(manifest)

        logger.info(
            "Pipeline completed — %d agents ran, %d findings, %d errors, %.1fs",
            len(self.outputs), len(all_findings), len(self.errors), duration_seconds,
        )

        return manifest

    def _load_input(self, input_path: str) -> dict:
        """Load input as a bundle directory or plain text prompt."""
        path = Path(input_path)
        if path.is_dir():
            logger.info("Loading input bundle from: %s", input_path)
            return load_bundle(input_path)
        elif path.is_file():
            logger.info("Loading input prompt from: %s", input_path)
            text = path.read_text(encoding="utf-8")
            return load_prompt(text)
        else:
            logger.info("Treating input as inline prompt text")
            return load_prompt(input_path)

    async def _run_intake(self, bundle: dict, empty_context: ContextPacket) -> ContextPacket:
        """Run the Intake Agent and return the ContextPacket."""
        logger.info("Step 2: Running IntakeAgent...")
        try:
            agent = IntakeAgent(
                llm_client=self.llm_client,
                run_config=self.run_config,
                policy_pack=self.policy_pack,
                context_packet=empty_context,
                raw_bundle=bundle,
            )
            output = await agent.analyze()
            self.outputs.append(output)
            context_packet = agent.get_context_packet()
            logger.info("IntakeAgent completed — %d findings", len(output.findings))
            return context_packet
        except Exception as exc:
            logger.error("IntakeAgent failed: %s", exc)
            self.errors["intake"] = str(exc)
            # Return a minimal context packet so downstream agents can still run
            return empty_context

    async def _run_parallel_step3(self, context_packet: ContextPacket) -> list[AgentOutput]:
        """Run Customer, Competitive, and Metrics agents in parallel."""
        logger.info("Step 3: Running CustomerInsights, Competitive, Metrics in parallel...")

        tasks = [
            self._run_agent_safe("customer", CustomerInsightsAgent, context_packet),
            self._run_agent_safe("competitive", CompetitiveAgent, context_packet),
            self._run_agent_safe("metrics", MetricsAgent, context_packet),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        outputs: list[AgentOutput] = []
        for result in results:
            if isinstance(result, AgentOutput):
                outputs.append(result)
            elif isinstance(result, Exception):
                logger.error("Step 3 agent error: %s", result)

        return outputs

    async def _run_parallel_step4(self, context_packet: ContextPacket) -> list[AgentOutput]:
        """Run Requirements and Feasibility agents in parallel."""
        logger.info("Step 4: Running Requirements, Feasibility in parallel...")

        tasks = [
            self._run_agent_safe("requirements", RequirementsAgent, context_packet),
            self._run_placeholder_agent("feasibility", "Feasibility Agent"),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        outputs: list[AgentOutput] = []
        for result in results:
            if isinstance(result, AgentOutput):
                outputs.append(result)
            elif isinstance(result, Exception):
                logger.error("Step 4 agent error: %s", result)

        return outputs

    async def _run_risk_agent(self, context_packet: ContextPacket) -> AgentOutput | None:
        """Run the Risk Agent."""
        logger.info("Step 5: Running RiskAgent...")
        return await self._run_placeholder_agent("risk", "Risk Agent")

    async def _run_lead_pm_agent(self, context_packet: ContextPacket) -> AgentOutput | None:
        """Run the Lead PM Agent to synthesize all findings."""
        logger.info("Step 6: Running LeadPMAgent...")
        return await self._run_placeholder_agent("lead_pm", "Lead PM Agent")

    async def _run_agent_safe(
        self,
        agent_id: str,
        agent_class: type,
        context_packet: ContextPacket,
        **kwargs: object,
    ) -> AgentOutput | None:
        """Run a concrete agent with error handling.

        Args:
            agent_id: Agent identifier for logging.
            agent_class: The agent class to instantiate.
            context_packet: The shared context packet.
            **kwargs: Additional keyword arguments for the agent constructor.

        Returns:
            The agent output, or None if the agent failed.
        """
        try:
            logger.info("Starting %s...", agent_id)
            agent = agent_class(
                llm_client=self.llm_client,
                run_config=self.run_config,
                policy_pack=self.policy_pack,
                context_packet=context_packet,
                **kwargs,
            )
            output = await agent.analyze()
            self.outputs.append(output)
            logger.info("%s completed — %d findings", agent_id, len(output.findings))
            return output
        except NotImplementedError:
            logger.warning("Agent %s not yet implemented, skipping.", agent_id)
            self.errors[agent_id] = "Not yet implemented"
            return None
        except Exception as exc:
            logger.error("Agent %s failed: %s", agent_id, exc)
            self.errors[agent_id] = str(exc)
            return None

    async def _run_placeholder_agent(self, agent_id: str, agent_name: str) -> AgentOutput | None:
        """Run a placeholder agent that is not yet implemented.

        Catches NotImplementedError gracefully and logs a skip message.

        Args:
            agent_id: Agent identifier.
            agent_name: Human-readable agent name.

        Returns:
            None (placeholder agents always skip).
        """
        logger.warning("Agent %s (%s) not yet implemented, skipping.", agent_id, agent_name)
        self.errors[agent_id] = "Not yet implemented"
        return None

    def _collect_all_findings(self, outputs: list[AgentOutput]) -> list[Finding]:
        """Merge all findings from all agent outputs into a single list.

        Args:
            outputs: List of agent outputs.

        Returns:
            Flat list of all findings across all agents.
        """
        all_findings: list[Finding] = []
        for output in outputs:
            all_findings.extend(output.findings)
        logger.info("Collected %d total findings from %d agents", len(all_findings), len(outputs))
        return all_findings

    def _build_manifest(
        self,
        all_findings: list[Finding],
        duration_seconds: float,
        bundle_warnings: list[str],
    ) -> dict:
        """Build the run manifest summarizing all produced artifacts."""
        findings_dir = self.run_dir / "findings"
        artifacts_dir = self.run_dir / "artifacts"

        # Discover saved files
        finding_files = sorted(str(p) for p in findings_dir.glob("*.json")) if findings_dir.exists() else []
        artifact_files = sorted(str(p) for p in artifacts_dir.glob("*")) if artifacts_dir.exists() else []

        # Context packet
        context_file = self.run_dir / "context_packet.json"
        context_path = str(context_file) if context_file.exists() else None

        return {
            "run_id": self.run_config.run_id,
            "provider": self.run_config.provider,
            "model": self.run_config.model,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration_seconds, 2),
            "agents_completed": [o.agent_id for o in self.outputs],
            "agents_skipped": list(self.errors.keys()),
            "total_findings": len(all_findings),
            "findings_by_type": self._count_findings_by_type(all_findings),
            "bundle_warnings": bundle_warnings,
            "output_files": {
                "context_packet": context_path,
                "findings": finding_files,
                "artifacts": artifact_files,
            },
            "errors": self.errors,
        }

    def _count_findings_by_type(self, findings: list[Finding]) -> dict[str, int]:
        """Count findings grouped by type."""
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.type] = counts.get(f.type, 0) + 1
        return counts

    def _save_manifest(self, manifest: dict) -> str:
        """Save the run manifest to the output directory.

        Args:
            manifest: The manifest dict to save.

        Returns:
            Path to the saved manifest file.
        """
        manifest_path = self.run_dir / "run_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Saved run_manifest.json to %s", manifest_path)
        return str(manifest_path)
