"""Base agent abstract class — all AIPM agents inherit from this."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from aipm.core.policy import PolicyPack
from aipm.core.resilience import AgentError, retry_with_backoff
from aipm.core.token_tracker import TokenTracker
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import AgentOutput


class BaseAgent(ABC):
    """Abstract base class for all AIPM pipeline agents."""

    agent_id: str = ""
    agent_name: str = ""

    def __init__(
        self,
        llm_client: object,
        run_config: RunConfig,
        policy_pack: PolicyPack,
        context_packet: ContextPacket,
        token_tracker: TokenTracker | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.run_config = run_config
        self.policy_pack = policy_pack
        self.context_packet = context_packet
        self.token_tracker = token_tracker
        self.logger = logging.getLogger(f"aipm.agents.{self.agent_id}")

        # Detect provider from client type
        self._provider = "openai"

        self.logger.info("Initialized %s (provider=%s, model=%s)", self.agent_name, self._provider, run_config.model)

    @abstractmethod
    async def analyze(self) -> AgentOutput:
        """Run the agent's analysis and return structured output.

        Each concrete agent must implement this method.
        """

    async def call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict | None = None,
    ) -> str:
        """Call the LLM with retry logic and return the response content.

        Automatically dispatches to the correct provider API format.
        Uses ``@retry_with_backoff`` for transient error handling and
        wraps unexpected failures in ``AgentError``.

        Args:
            system_prompt: The system-level instruction for the LLM.
            user_prompt: The user-level message with data and questions.
            response_format: Optional dict to request JSON mode (OpenAI).

        Returns:
            The LLM response content as a string.

        Raises:
            AgentError: If the call fails after all retries or an
                        unexpected error occurs.
        """
        try:
            return await self._call_llm_with_retry(system_prompt, user_prompt, response_format)
        except Exception as exc:
            raise AgentError(
                agent_id=self.agent_id,
                message=f"LLM call failed: {exc}",
                recoverable=True,
            ) from exc

    @retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=30.0)
    async def _call_llm_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict | None = None,
    ) -> str:
        """Inner LLM call wrapped by the retry decorator."""
        return await self._call_openai(system_prompt, user_prompt, response_format)

    async def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict | None,
    ) -> str:
        """Dispatch an LLM call via the OpenAI SDK."""
        kwargs: dict = {
            "model": self.run_config.model,
            "temperature": self.run_config.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.llm_client.chat.completions.create(**kwargs)

        usage = response.usage
        if usage:
            self.logger.info(
                "Token usage — prompt: %d, completion: %d, total: %d",
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
            )
            if self.token_tracker:
                self.token_tracker.record(self.agent_id, usage.prompt_tokens, usage.completion_tokens)

        return response.choices[0].message.content

    def save_output(self, output: AgentOutput) -> str:
        """Serialize AgentOutput to JSON and save to the findings directory.

        Args:
            output: The agent's structured output.

        Returns:
            The file path where the output was saved.
        """
        findings_dir = Path(self.run_config.output_dir) / self.run_config.run_id / "findings"
        findings_dir.mkdir(parents=True, exist_ok=True)

        file_path = findings_dir / f"{self.agent_id}.json"
        file_path.write_text(
            output.model_dump_json(indent=2),
            encoding="utf-8",
        )

        self.logger.info("Saved output to %s (%d findings)", file_path, len(output.findings))
        return str(file_path)

    def _build_findings_prompt_section(self) -> str:
        """Return a string describing the expected JSON output format.

        Injected into agent prompts so the LLM returns structured findings
        matching the Finding schema.
        """
        return """You MUST return a JSON object with this exact structure:
{
  "findings": [
    {
      "id": "<agent_id>-<number, e.g. 001>",
      "agent_id": "<your agent id>",
      "type": "<insight|risk|requirement|metric|gap|recommendation|dependency>",
      "title": "<short descriptive title>",
      "description": "<detailed explanation>",
      "impact": "<critical|high|medium|low>",
      "confidence": "<validated|directional|speculative>",
      "assumptions": ["<assumption 1>", "..."],
      "evidence": [
        {
          "source_id": "<ticket or doc ID>",
          "source_type": "<ticket|doc|note|metric|interview>",
          "excerpt": "<relevant excerpt from the source>"
        }
      ],
      "recommendations": ["<action 1>", "..."],
      "tags": ["<tag1>", "<tag2>"],
      "metadata": {}
    }
  ],
  "summary": "<2-3 sentence summary of your analysis>"
}

Rules:
- Every finding MUST reference at least one evidence source_id from the provided data.
- Classify confidence as: "validated" (multiple corroborating sources), "directional" (single strong source), "speculative" (inferred, needs validation).
- Use sequential IDs starting from 001.
- Return ONLY valid JSON. No markdown code fences, no extra text."""
