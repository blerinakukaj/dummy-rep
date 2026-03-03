"""Shared pytest fixtures for AIPM tests."""

from pathlib import Path

import pytest

from aipm.schemas.config import RunConfig
from aipm.schemas.context import DocumentItem, TicketItem
from aipm.schemas.findings import Finding


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def sample_bundle_path(project_root: Path) -> Path:
    """Return the path to the sample input bundle."""
    return project_root / "input_bundles" / "sample_bundle"


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Provide a temporary output directory for test runs."""
    out = tmp_path / "output"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# Shared schema fixtures — reusable across test modules
# ---------------------------------------------------------------------------


@pytest.fixture
def make_ticket():
    """Factory fixture for creating TicketItem instances."""

    def _make(
        id: str = "TICKET-001",
        title: str = "Sample ticket",
        description: str = "A sample ticket description.",
        status: str = "open",
        priority: str = "medium",
        labels: list[str] | None = None,
        source: str = "jira",
    ) -> TicketItem:
        return TicketItem(
            id=id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            labels=labels or [],
            source=source,
        )

    return _make


@pytest.fixture
def make_document():
    """Factory fixture for creating DocumentItem instances."""

    def _make(
        id: str = "DOC-001",
        title: str = "sample_doc.md",
        content: str = "Document content.",
        doc_type: str = "note",
        tags: list[str] | None = None,
    ) -> DocumentItem:
        return DocumentItem(
            id=id,
            title=title,
            content=content,
            doc_type=doc_type,
            tags=tags or [],
        )

    return _make


@pytest.fixture
def make_finding():
    """Factory fixture for creating Finding instances."""

    def _make(
        id: str = "test-001",
        agent_id: str = "test",
        type: str = "insight",
        title: str = "Test finding",
        description: str = "A test finding.",
        impact: str = "medium",
        confidence: str = "directional",
        **kwargs,
    ) -> Finding:
        return Finding(
            id=id,
            agent_id=agent_id,
            type=type,
            title=title,
            description=description,
            impact=impact,
            confidence=confidence,
            **kwargs,
        )

    return _make


@pytest.fixture
def make_run_config():
    """Factory fixture for creating RunConfig instances."""

    def _make(**overrides) -> RunConfig:
        defaults = {"input_path": "input_bundles/sample_bundle"}
        defaults.update(overrides)
        return RunConfig(**defaults)

    return _make
