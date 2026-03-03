"""Run configuration schema for the AIPM pipeline."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class RunConfig(BaseModel):
    """Configuration for a single pipeline run."""

    run_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique run identifier, auto-generated UUID",
    )
    input_path: str = Field(..., description="Path to input bundle directory or prompt file")
    output_dir: str = Field(default="output", description="Base directory for pipeline outputs")
    provider: Literal["anthropic", "openai"] = Field(default="openai", description="LLM provider to use")
    model: str = Field(default="gpt-4o", description="Model identifier to use for LLM calls")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="LLM sampling temperature")
    policy_path: str = Field(
        default="src/aipm/policies/default_policy.yaml",
        description="Path to the YAML policy pack",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "run_id": "550e8400-e29b-41d4-a716-446655440000",
                    "input_path": "input_bundles/sample_bundle",
                    "output_dir": "output",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "temperature": 0.2,
                    "policy_path": "src/aipm/policies/default_policy.yaml",
                }
            ]
        }
    }
