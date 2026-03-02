"""Product Context Packet schema — produced by Agent A, consumed by all agents."""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TicketItem(BaseModel):
    """A normalized ticket or work item from Jira, ADO, or manual input."""

    id: str = Field(..., description="Unique ticket identifier, e.g. 'TICKET-001'")
    title: str = Field(..., description="Ticket title")
    description: str = Field(..., description="Ticket description or body")
    status: str = Field(..., description="Current status, e.g. 'open', 'in_progress', 'closed'")
    priority: Optional[str] = Field(default=None, description="Priority level, e.g. 'high', 'medium', 'low'")
    labels: list[str] = Field(default_factory=list, description="Tags or labels attached to the ticket")
    created_at: Optional[str] = Field(default=None, description="Creation date as ISO string")
    source: Literal["jira", "ado", "manual"] = Field(..., description="Origin system of the ticket")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "TICKET-001",
                    "title": "Add notification preferences page",
                    "description": "Users need a way to configure which notifications they receive.",
                    "status": "open",
                    "priority": "high",
                    "labels": ["feature", "ux"],
                    "created_at": "2025-11-15",
                    "source": "jira",
                }
            ]
        }
    }


class DocumentItem(BaseModel):
    """A supporting document included in the product bundle."""

    id: str = Field(..., description="Unique document identifier")
    title: str = Field(..., description="Document title or filename")
    content: str = Field(..., description="Full text content of the document")
    doc_type: Literal["prd", "spec", "note", "interview", "metrics_snapshot", "competitor_brief"] = Field(
        ..., description="Type of the document"
    )
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "DOC-001",
                    "title": "customer_notes.md",
                    "content": "Interview with power users revealed...",
                    "doc_type": "note",
                    "tags": ["customer", "interview"],
                }
            ]
        }
    }


class RiskHotspot(BaseModel):
    """A risk area detected during intake by scanning content for sensitive topics."""

    category: Literal["privacy", "auth", "pricing", "platform", "accessibility", "security", "compliance"] = Field(
        ..., description="Risk category"
    )
    description: str = Field(..., description="Description of the identified risk area")
    severity: Literal["critical", "high", "medium", "low"] = Field(..., description="Severity level")
    source_ids: list[str] = Field(default_factory=list, description="IDs of tickets/docs that triggered this hotspot")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "category": "privacy",
                    "description": "Ticket TICKET-003 mentions collecting user browsing history",
                    "severity": "high",
                    "source_ids": ["TICKET-003"],
                }
            ]
        }
    }


class ContextPacket(BaseModel):
    """The Product Context Packet — central data structure consumed by all downstream agents."""

    run_id: str = Field(..., description="Unique pipeline run identifier")
    product_name: str = Field(..., description="Name of the product or feature")
    product_description: str = Field(..., description="Brief description of the product or feature request")
    tickets: list[TicketItem] = Field(default_factory=list, description="Normalized tickets from the input bundle")
    documents: list[DocumentItem] = Field(default_factory=list, description="Supporting documents from the bundle")
    risk_hotspots: list[RiskHotspot] = Field(
        default_factory=list, description="Risk areas detected during intake"
    )
    missing_info: list[str] = Field(
        default_factory=list, description="Information gaps detected, e.g. 'No customer notes provided'"
    )
    dedup_log: list[str] = Field(
        default_factory=list, description="Log of deduplication actions taken during intake"
    )
    raw_input_type: Literal["prompt", "bundle"] = Field(..., description="Whether input was a text prompt or a bundle")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the context packet was created",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "run_id": "run-abc123",
                    "product_name": "SmartNotify",
                    "product_description": "Intelligent notification prioritization system",
                    "tickets": [],
                    "documents": [],
                    "risk_hotspots": [],
                    "missing_info": ["No metrics snapshot provided"],
                    "dedup_log": [],
                    "raw_input_type": "bundle",
                    "created_at": "2026-03-02T12:00:00Z",
                }
            ]
        }
    }
