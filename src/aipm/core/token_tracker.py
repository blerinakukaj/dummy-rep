"""Token usage tracking and cost estimation for AIPM pipeline runs."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Approximate pricing per 1M tokens (USD)
PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


class TokenTracker:
    """Tracks prompt and completion token usage per agent across a pipeline run."""

    def __init__(self) -> None:
        self._usage: dict[str, dict[str, int]] = {}

    def record(self, agent_id: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage for an agent call.

        Args:
            agent_id: The agent that made the LLM call.
            prompt_tokens: Number of input/prompt tokens used.
            completion_tokens: Number of output/completion tokens used.
        """
        if agent_id not in self._usage:
            self._usage[agent_id] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        self._usage[agent_id]["prompt_tokens"] += prompt_tokens
        self._usage[agent_id]["completion_tokens"] += completion_tokens
        self._usage[agent_id]["total_tokens"] += prompt_tokens + completion_tokens

        logger.debug(
            "Recorded tokens for %s: prompt=%d, completion=%d",
            agent_id,
            prompt_tokens,
            completion_tokens,
        )

    def get_summary(self) -> dict:
        """Return per-agent and total token usage summary.

        Returns:
            Dict with 'per_agent' breakdown and 'total' aggregated counts.
        """
        total_prompt = sum(a["prompt_tokens"] for a in self._usage.values())
        total_completion = sum(a["completion_tokens"] for a in self._usage.values())

        return {
            "per_agent": dict(self._usage),
            "total": {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_prompt + total_completion,
            },
        }

    def estimate_cost(self, provider: str, model: str) -> float:
        """Estimate the total cost based on provider pricing.

        Uses approximate pricing tables. Falls back to gpt-4o pricing
        if the model is not recognized.

        Args:
            provider: LLM provider name.
            model: Model identifier.

        Returns:
            Estimated cost in USD.
        """
        # Match model to pricing key
        pricing_key = model
        if pricing_key not in PRICING:
            pricing_key = "gpt-4o-mini"

        rates = PRICING[pricing_key]
        summary = self.get_summary()
        total = summary["total"]

        input_cost = (total["prompt_tokens"] / 1_000_000) * rates["input"]
        output_cost = (total["completion_tokens"] / 1_000_000) * rates["output"]

        return round(input_cost + output_cost, 6)

    def save_report(self, output_dir: str, run_id: str = "", provider: str = "openai", model: str = "gpt-4o-mini") -> str:
        """Save token usage report as token_usage.json.

        Args:
            output_dir: Base output directory (report saved to output_dir/{run_id}/ or output_dir/).
            run_id: Optional run ID for subdirectory.
            provider: LLM provider for cost estimation.
            model: Model for cost estimation.

        Returns:
            Path to the saved report file.
        """
        if run_id:
            report_dir = Path(output_dir) / run_id
        else:
            report_dir = Path(output_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        report = self.get_summary()
        report["estimated_cost_usd"] = self.estimate_cost(provider, model)
        report["provider"] = provider
        report["model"] = model

        report_path = report_dir / "token_usage.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        logger.info("Saved token usage report to %s", report_path)
        return str(report_path)
