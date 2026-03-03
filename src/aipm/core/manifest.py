"""Run manifest tracking and output summary for AIPM pipeline runs."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from aipm.core.token_tracker import TokenTracker
from aipm.schemas.config import RunConfig

logger = logging.getLogger(__name__)


class RunManifest:
    """Tracks agent results, artifacts, and recommendation for a pipeline run."""

    def __init__(self, run_config: RunConfig) -> None:
        self.run_config = run_config
        self.started_at = datetime.now(UTC)
        self.agents: list[dict] = []
        self.artifacts: dict[str, str] = {}
        self.recommendation: dict[str, str] = {"decision": "", "reasoning": ""}
        self._finalized: dict | None = None

    def record_agent_result(
        self,
        agent_id: str,
        status: str,
        output_path: str,
        duration_seconds: float,
        error: str | None = None,
    ) -> None:
        """Track an agent's execution result.

        Args:
            agent_id: The agent identifier.
            status: One of 'success', 'failed', 'skipped'.
            output_path: Path to the agent's output file.
            duration_seconds: How long the agent took to run.
            error: Error message if the agent failed.
        """
        self.agents.append(
            {
                "agent_id": agent_id,
                "status": status,
                "output_path": output_path,
                "duration_seconds": round(duration_seconds, 2),
                "error": error,
            }
        )

    def record_artifact(self, artifact_name: str, artifact_path: str) -> None:
        """Track a generated artifact.

        Args:
            artifact_name: Name/key of the artifact (e.g. 'prd', 'roadmap').
            artifact_path: File path where the artifact was saved.
        """
        self.artifacts[artifact_name] = artifact_path

    def set_recommendation(self, recommendation: str, reasoning: str) -> None:
        """Store the final product recommendation.

        Args:
            recommendation: The decision (proceed, proceed_with_mitigations, etc.).
            reasoning: Explanation for the recommendation.
        """
        self.recommendation = {"decision": recommendation, "reasoning": reasoning}

    def finalize(self, token_tracker: TokenTracker) -> dict:
        """Build and return the complete manifest dict.

        Args:
            token_tracker: The token tracker with usage data for cost estimation.

        Returns:
            Complete manifest dictionary.
        """
        end_time = datetime.now(UTC)
        total_duration = (end_time - self.started_at).total_seconds()

        self._finalized = {
            "run_id": self.run_config.run_id,
            "timestamp": end_time.isoformat(),
            "input_path": self.run_config.input_path,
            "model": self.run_config.model,
            "temperature": self.run_config.temperature,
            "policy_path": self.run_config.policy_path,
            "agents": self.agents,
            "artifacts": self.artifacts,
            "recommendation": self.recommendation,
            "token_usage": token_tracker.get_summary(),
            "estimated_cost": token_tracker.estimate_cost(
                self.run_config.provider,
                self.run_config.model,
            ),
            "total_duration_seconds": round(total_duration, 2),
        }
        return self._finalized

    def save(self, output_dir: str) -> str:
        """Save the manifest to output/{run_id}/run_manifest.json.

        Args:
            output_dir: Base output directory.

        Returns:
            Path to the saved manifest file.
        """
        if self._finalized is None:
            raise RuntimeError("Call finalize() before save()")

        manifest_dir = Path(output_dir) / self.run_config.run_id
        manifest_dir.mkdir(parents=True, exist_ok=True)

        path = manifest_dir / "run_manifest.json"
        path.write_text(
            json.dumps(self._finalized, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Saved run manifest to %s", path)
        return str(path)

    def pretty_summary(self) -> str:
        """Return a CLI-friendly summary of the run.

        Returns:
            Multi-line formatted string suitable for terminal output.
        """
        data = self._finalized or {}
        lines = [
            "",
            "=" * 60,
            "  AIPM Pipeline Run Summary",
            "=" * 60,
            f"  Run ID:          {data.get('run_id', 'N/A')}",
            f"  Model:           {data.get('model', 'N/A')}",
            f"  Duration:        {data.get('total_duration_seconds', 0):.1f}s",
            f"  Recommendation:  {self.recommendation.get('decision', 'N/A')}",
            "",
            "  Agents:",
        ]

        for agent in self.agents:
            status_icon = "+" if agent["status"] == "success" else "x"
            line = f"    [{status_icon}] {agent['agent_id']:<20} {agent['duration_seconds']:>6.1f}s"
            if agent.get("error"):
                line += f"  ERROR: {agent['error'][:50]}"
            lines.append(line)

        lines.append("")
        lines.append("  Artifacts:")
        for name, path in self.artifacts.items():
            lines.append(f"    - {name}: {path}")

        token_usage = data.get("token_usage", {}).get("total", {})
        cost = data.get("estimated_cost", 0)
        lines.extend(
            [
                "",
                "  Token Usage:",
                f"    Prompt:     {token_usage.get('prompt_tokens', 0):,}",
                f"    Completion: {token_usage.get('completion_tokens', 0):,}",
                f"    Total:      {token_usage.get('total_tokens', 0):,}",
                f"    Est. Cost:  ${cost:.4f}",
                "",
                "=" * 60,
                "",
            ]
        )

        return "\n".join(lines)
