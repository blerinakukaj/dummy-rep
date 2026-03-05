"""Configuration loader — environment, LLM clients, run config, and output directories."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from aipm.schemas.config import RunConfig

logger = logging.getLogger(__name__)

# Model ID mappings per provider
MODELS: dict[str, dict[str, str]] = {
    "openai": {
        "default": "gpt-4o-mini",
        "fast": "gpt-4o-mini",
    },
}


def load_env() -> None:
    """Load environment variables from .env file."""
    load_dotenv()
    logger.debug("Loaded environment variables from .env")


def get_llm_client(provider: str = "openai") -> Any:
    """Return an initialized async OpenAI LLM client.

    Args:
        provider: Must be "openai".

    Returns:
        An AsyncOpenAI client instance.

    Raises:
        ValueError: If the provider is not supported.
        OSError: If the required API key is not set.
    """
    import os

    if provider == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise OSError("OPENAI_API_KEY is not set. Add it to your .env file.")
        logger.info("Initializing async OpenAI client")
        return openai.AsyncOpenAI(api_key=api_key)

    else:
        raise ValueError(f"Unsupported provider: '{provider}'. Use 'openai'.")


def load_run_config(input_path: str, output_dir: str = "output", **overrides: object) -> RunConfig:
    """Create a RunConfig with auto-generated run_id.

    Args:
        input_path: Path to the input bundle or prompt file.
        output_dir: Base output directory.
        **overrides: Additional fields to override on RunConfig (provider, model, temperature, policy_path).

    Returns:
        A fully populated RunConfig instance.
    """
    config = RunConfig(input_path=input_path, output_dir=output_dir, **overrides)
    logger.info("Created run config: run_id=%s, provider=%s, model=%s", config.run_id, config.provider, config.model)
    return config


def ensure_output_dirs(run_config: RunConfig) -> Path:
    """Create the output directory structure for a pipeline run.

    Creates:
        output/{run_id}/
        output/{run_id}/findings/
        output/{run_id}/artifacts/

    Args:
        run_config: The run configuration.

    Returns:
        The run output root directory as a Path.
    """
    run_dir = Path(run_config.output_dir) / run_config.run_id
    findings_dir = run_dir / "findings"
    artifacts_dir = run_dir / "artifacts"

    run_dir.mkdir(parents=True, exist_ok=True)
    findings_dir.mkdir(exist_ok=True)
    artifacts_dir.mkdir(exist_ok=True)

    logger.info("Created output directories at %s", run_dir)
    return run_dir
