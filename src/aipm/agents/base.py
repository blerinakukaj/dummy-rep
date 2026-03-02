"""Base agent abstract class — all AIPM agents inherit from this."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from aipm.core.policy import PolicyPack
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import AgentOutput

# Maximum retries for LLM calls
MAX_RETRIES = 3
BASE_DELAY = 1.0


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
    ) -> None:
        self.llm_client = llm_client
        self.run_config = run_config
        self.policy_pack = policy_pack
        self.context_packet = context_packet
        self.logger = logging.getLogger(f"aipm.agents.{self.agent_id}")

        # Detect provider from client type
        client_type = type(llm_client).__module__
        if "openai" in client_type:
            self._provider = "openai"
        elif "anthropic" in client_type:
            self._provider = "anthropic"
        else:
            self._provider = run_config.provider

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
        response_format: Optional[dict] = None,
    ) -> str:
        """Call the LLM with retry logic and return the response content.

        Automatically dispatches to the correct provider API format.

        Args:
            system_prompt: The system-level instruction for the LLM.
            user_prompt: The user-level message with data and questions.
            response_format: Optional dict to request JSON mode (OpenAI) or
                             append JSON instructions (Anthropic).

        Returns:
            The LLM response content as a string.

        Raises:
            RuntimeError: If all retries are exhausted.
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if self._provider == "openai":
                    result = await self._call_openai(system_prompt, user_prompt, response_format)
                else:
                    result = await self._call_anthropic(system_prompt, user_prompt, response_format)

                self.logger.debug("LLM call succeeded on attempt %d", attempt)
                return result

            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** (attempt - 1))
                    self.logger.warning(
                        "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt, MAX_RETRIES, exc, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    self.logger.error("LLM call failed after %d attempts: %s", MAX_RETRIES, exc)

        raise RuntimeError(f"LLM call failed after {MAX_RETRIES} retries: {last_error}")

    async def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[dict],
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
                usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            )

        return response.choices[0].message.content

    async def _call_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[dict],
    ) -> str:
        """Dispatch an LLM call via the Anthropic SDK."""
        effective_system = system_prompt
        if response_format:
            effective_system += "\n\nIMPORTANT: Respond with valid JSON only. No markdown, no explanation outside the JSON."

        response = self.llm_client.messages.create(
            model=self.run_config.model,
            max_tokens=4096,
            temperature=self.run_config.temperature,
            system=effective_system,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        usage = response.usage
        if usage:
            self.logger.info(
                "Token usage — input: %d, output: %d",
                usage.input_tokens, usage.output_tokens,
            )

        return response.content[0].text

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
        return '''You MUST return a JSON object with this exact structure:
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
- Return ONLY valid JSON. No markdown code fences, no extra text.'''
