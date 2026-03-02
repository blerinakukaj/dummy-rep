"""Shared findings schema used by ALL agents in the AIPM pipeline."""

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """A piece of evidence linking a finding back to a source document or ticket."""

    source_id: str = Field(..., description="ID of the source ticket or document")
    source_type: Literal["ticket", "doc", "note", "metric", "interview"] = Field(
        ..., description="Type of the source material"
    )
    excerpt: str = Field(..., description="Relevant excerpt from the source")
    url: Optional[str] = Field(default=None, description="Optional URL to the source")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source_id": "TICKET-042",
                    "source_type": "ticket",
                    "excerpt": "Users report notification fatigue with 20+ alerts daily",
                    "url": None,
                }
            ]
        }
    }


class Finding(BaseModel):
    """A single structured finding produced by an agent."""

    id: str = Field(..., description="Unique ID in format '{agent_id}-{number}', e.g. 'customer-001'")
    agent_id: str = Field(..., description="ID of the agent that produced this finding")
    type: Literal["insight", "risk", "requirement", "metric", "gap", "recommendation", "dependency"] = Field(
        ..., description="Category of the finding"
    )
    title: str = Field(..., description="Short descriptive title")
    description: str = Field(..., description="Detailed explanation of the finding")
    impact: Literal["critical", "high", "medium", "low"] = Field(
        ..., description="Expected impact level"
    )
    confidence: Literal["validated", "directional", "speculative"] = Field(
        ..., description="Confidence level based on evidence strength"
    )
    assumptions: list[str] = Field(default_factory=list, description="Assumptions underlying this finding")
    evidence: list[EvidenceItem] = Field(default_factory=list, description="Evidence supporting this finding")
    recommendations: list[str] = Field(default_factory=list, description="Suggested actions")
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization, e.g. 'privacy', 'auth', 'pricing', 'platform', 'accessibility'",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Agent-specific extra data")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "customer-001",
                    "agent_id": "customer",
                    "type": "insight",
                    "title": "Notification fatigue is the top user pain point",
                    "description": "Multiple customer interviews and support tickets indicate users are overwhelmed by notification volume, leading to muting and eventual disengagement.",
                    "impact": "high",
                    "confidence": "validated",
                    "assumptions": ["Users who mute notifications are less likely to return"],
                    "evidence": [
                        {
                            "source_id": "TICKET-042",
                            "source_type": "ticket",
                            "excerpt": "Users report notification fatigue with 20+ alerts daily",
                            "url": None,
                        }
                    ],
                    "recommendations": ["Implement ML-based notification prioritization"],
                    "tags": ["ux", "engagement"],
                    "metadata": {"segment": "power_users", "jtbd": "Stay informed without being overwhelmed"},
                }
            ]
        }
    }


class AgentOutput(BaseModel):
    """Standard output produced by every agent in the pipeline."""

    agent_id: str = Field(..., description="ID of the agent that produced this output")
    agent_name: str = Field(..., description="Human-readable name of the agent")
    run_id: str = Field(..., description="ID of the pipeline run")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this output was generated",
    )
    findings: list[Finding] = Field(default_factory=list, description="List of structured findings")
    summary: str = Field(default="", description="Brief summary of the agent's analysis")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered during analysis")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "agent_id": "customer",
                    "agent_name": "Customer Insights Agent",
                    "run_id": "run-abc123",
                    "timestamp": "2026-03-02T12:00:00Z",
                    "findings": [],
                    "summary": "Identified 5 key user pain points across 3 segments.",
                    "errors": [],
                }
            ]
        }
    }
