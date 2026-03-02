"""Shared pytest fixtures for AIPM tests."""

import pytest
from pathlib import Path


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
