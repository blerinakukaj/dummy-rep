"""Resilience utilities — retry logic, error hierarchy, and safe JSON parsing.

Provides the @retry_with_backoff decorator for LLM calls, custom exception
classes for structured error propagation, and helpers for parsing potentially
malformed LLM JSON responses.
"""

import asyncio
import functools
import json
import logging
import random
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class AgentError(Exception):
    """Raised when an agent encounters an error during execution.

    Attributes:
        agent_id: The identifier of the agent that failed.
        message: Human-readable description of the error.
        recoverable: ``True`` if the pipeline can continue without this agent.
    """

    def __init__(self, agent_id: str, message: str, recoverable: bool = True) -> None:
        self.agent_id = agent_id
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{agent_id}] {message}")


class PipelineError(Exception):
    """Raised when the pipeline itself cannot continue.

    Attributes:
        failed_agents: List of agent IDs that failed.
        successful_agents: List of agent IDs that completed successfully.
    """

    def __init__(
        self,
        failed_agents: list[str],
        successful_agents: list[str],
        message: str = "Pipeline encountered failures",
    ) -> None:
        self.failed_agents = failed_agents
        self.successful_agents = successful_agents
        super().__init__(
            f"{message} — failed: {failed_agents}, succeeded: {successful_agents}"
        )


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def _is_retryable(exc: Exception) -> bool:
    """Return ``True`` if the exception is a transient/rate-limit error
    that warrants a retry."""

    exc_type = type(exc).__name__
    exc_module = type(exc).__module__ or ""

    # OpenAI transient / rate-limit errors
    if "openai" in exc_module:
        if exc_type in ("RateLimitError", "APITimeoutError", "APIConnectionError"):
            return True

    # Anthropic transient / rate-limit errors
    if "anthropic" in exc_module:
        if exc_type in ("RateLimitError", "APIStatusError", "APITimeoutError", "APIConnectionError"):
            return True

    # Generic connection / timeout errors
    if exc_type in ("TimeoutError", "ConnectionError"):
        return True

    return False


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
):
    """Decorator that retries an async function on transient LLM errors.

    Uses exponential backoff with jitter::

        delay = min(base_delay * 2^(attempt-1), max_delay) + random(0, 1)

    Args:
        max_retries: Maximum number of attempts (including the first call).
        base_delay: Starting delay in seconds.
        max_delay: Ceiling for the computed delay.

    Returns:
        A decorator wrapping the target async function.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error: Exception | None = None

            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc

                    if not _is_retryable(exc):
                        logger.error(
                            "Non-retryable error on attempt %d/%d: %s",
                            attempt, max_retries, exc,
                        )
                        raise

                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                        jitter = random.uniform(0, 1)  # noqa: S311
                        total_delay = delay + jitter
                        logger.warning(
                            "Retryable error on attempt %d/%d: %s — retrying in %.1fs",
                            attempt, max_retries, exc, total_delay,
                        )
                        await asyncio.sleep(total_delay)
                    else:
                        logger.error(
                            "All %d retry attempts exhausted: %s",
                            max_retries, exc,
                        )

            raise RuntimeError(
                f"LLM call failed after {max_retries} retries: {last_error}"
            )

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Safe JSON parsing
# ---------------------------------------------------------------------------

def safe_json_parse(text: str) -> dict:
    """Parse a JSON string with multiple fallback strategies.

    1. Direct ``json.loads``
    2. Extract from markdown code fences (````` ```json ... ``` `````)
    3. Find the first ``{`` to last ``}`` substring

    Args:
        text: Raw text that should contain JSON.

    Returns:
        Parsed dictionary.

    Raises:
        ValueError: If none of the strategies produce valid JSON.
    """
    if not text or not text.strip():
        raise ValueError("Empty text — nothing to parse")

    # Strategy 1: direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract from markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 3: first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # All strategies failed
    preview = text[:200].replace("\n", " ")
    raise ValueError(
        f"Could not parse JSON from LLM response (first 200 chars): {preview}"
    )


def validate_llm_response(
    response: str,
    expected_keys: list[str],
    agent_id: str = "unknown",
) -> dict:
    """Parse an LLM response as JSON and verify required keys are present.

    Args:
        response: Raw LLM response string.
        expected_keys: List of top-level keys that must exist in the result.
        agent_id: Agent identifier used when raising ``AgentError``.

    Returns:
        The parsed dictionary.

    Raises:
        AgentError: If parsing fails or required keys are missing.
    """
    try:
        data = safe_json_parse(response)
    except ValueError as exc:
        raise AgentError(
            agent_id=agent_id,
            message=f"Failed to parse LLM JSON response: {exc}",
            recoverable=True,
        ) from exc

    missing = [k for k in expected_keys if k not in data]
    if missing:
        raise AgentError(
            agent_id=agent_id,
            message=f"LLM response missing required keys: {missing}",
            recoverable=True,
        )

    return data
