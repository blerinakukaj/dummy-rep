"""Tests for the BacklogGenerator."""

import csv
import io
import os
import tempfile

import pytest

from aipm.core.backlog_generator import BacklogGenerator
from aipm.schemas.findings import EvidenceItem, Finding


def _make_finding(**overrides) -> Finding:
    """Helper to create a Finding with sensible defaults."""
    defaults = {
        "id": "req-001",
        "agent_id": "requirements",
        "type": "requirement",
        "title": "User login",
        "description": "Users can log in with email and password.",
        "impact": "high",
        "confidence": "validated",
        "evidence": [EvidenceItem(source_id="DOC-1", source_type="doc", excerpt="login spec")],
        "tags": ["auth"],
        "metadata": {
            "epic_id": "EPIC-1",
            "epic_title": "Authentication",
            "story_id": "STORY-1",
            "story_title": "User login",
            "priority": "P0",
            "complexity": "medium",
            "phase": "MVP",
            "acceptance_criteria": ["GIVEN a user WHEN they submit credentials THEN they are logged in"],
        },
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_feasibility_finding(**overrides) -> Finding:
    """Helper to create a feasibility Finding."""
    defaults = {
        "id": "feasibility-001",
        "agent_id": "feasibility",
        "type": "dependency",
        "title": "OAuth integration",
        "description": "Requires OAuth provider setup.",
        "impact": "medium",
        "confidence": "directional",
        "evidence": [EvidenceItem(source_id="DOC-2", source_type="doc", excerpt="oauth docs")],
        "tags": ["auth"],
        "metadata": {
            "story_id": "STORY-1",
            "complexity": "complex",
            "phase": "MVP",
            "dependencies": ["OAuth provider", "Session store"],
        },
    }
    defaults.update(overrides)
    return Finding(**defaults)


class TestBacklogGenerator:
    """Tests for BacklogGenerator.generate()."""

    def setup_method(self) -> None:
        self.gen = BacklogGenerator()

    def test_generate_basic(self) -> None:
        """Generate CSV from a single requirement finding."""
        req = _make_finding()
        csv_content = self.gen.generate([req], [])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["epic_id"] == "EPIC-1"
        assert rows[0]["story_id"] == "STORY-1"
        assert rows[0]["priority"] == "P0"
        assert rows[0]["phase"] == "MVP"

    def test_generate_cross_references_feasibility(self) -> None:
        """Feasibility findings override complexity and add dependencies."""
        req = _make_finding()
        feas = _make_feasibility_finding()
        csv_content = self.gen.generate([req], [feas])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert rows[0]["complexity"] == "complex"
        assert "OAuth provider" in rows[0]["dependencies"]
        assert "Session store" in rows[0]["dependencies"]

    def test_generate_sorts_by_phase_priority_complexity(self) -> None:
        """Rows are sorted by phase → priority → complexity."""
        findings = [
            _make_finding(id="req-001", metadata={
                "epic_id": "E1", "story_id": "S1", "priority": "P2", "phase": "V1", "complexity": "simple",
            }),
            _make_finding(id="req-002", metadata={
                "epic_id": "E2", "story_id": "S2", "priority": "P0", "phase": "MVP", "complexity": "medium",
            }),
            _make_finding(id="req-003", metadata={
                "epic_id": "E3", "story_id": "S3", "priority": "P0", "phase": "MVP", "complexity": "simple",
            }),
            _make_finding(id="req-004", metadata={
                "epic_id": "E4", "story_id": "S4", "priority": "P1", "phase": "V2", "complexity": "epic",
            }),
        ]
        csv_content = self.gen.generate(findings, [])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        # MVP P0 simple → MVP P0 medium → V1 P2 simple → V2 P1 epic
        assert rows[0]["story_id"] == "S3"
        assert rows[1]["story_id"] == "S2"
        assert rows[2]["story_id"] == "S1"
        assert rows[3]["story_id"] == "S4"

    def test_generate_skips_findings_without_metadata(self) -> None:
        """Findings without epic_id or story_id are excluded."""
        req_with = _make_finding()
        req_without = _make_finding(id="req-002", metadata={})
        csv_content = self.gen.generate([req_with, req_without], [])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert len(rows) == 1

    def test_generate_acceptance_criteria_list_joined(self) -> None:
        """List acceptance criteria are joined with semicolons."""
        req = _make_finding(metadata={
            "epic_id": "E1", "story_id": "S1", "priority": "P0", "phase": "MVP",
            "acceptance_criteria": ["GIVEN A WHEN B THEN C", "GIVEN D WHEN E THEN F"],
        })
        csv_content = self.gen.generate([req], [])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert "GIVEN A WHEN B THEN C; GIVEN D WHEN E THEN F" == rows[0]["acceptance_criteria"]

    def test_generate_empty_input(self) -> None:
        """Empty input produces header-only CSV."""
        csv_content = self.gen.generate([], [])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        assert len(rows) == 0
        assert "epic_id" in csv_content


class TestSaveCsv:
    """Tests for BacklogGenerator.save_csv()."""

    def test_save_csv_writes_file(self) -> None:
        gen = BacklogGenerator()
        content = "col1,col2\nval1,val2\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name

        try:
            gen.save_csv(content, path)
            with open(path, encoding="utf-8") as f:
                assert f.read() == content
        finally:
            os.unlink(path)


class TestGetStats:
    """Tests for BacklogGenerator.get_stats()."""

    def setup_method(self) -> None:
        self.gen = BacklogGenerator()

    def test_get_stats_counts(self) -> None:
        findings = [
            _make_finding(id="req-001", metadata={
                "epic_id": "E1", "story_id": "S1", "priority": "P0", "phase": "MVP",
            }),
            _make_finding(id="req-002", metadata={
                "epic_id": "E1", "story_id": "S2", "priority": "P1", "phase": "MVP",
            }),
            _make_finding(id="req-003", metadata={
                "epic_id": "E2", "story_id": "S3", "priority": "P0", "phase": "V1",
            }),
        ]
        csv_content = self.gen.generate(findings, [])
        stats = self.gen.get_stats(csv_content)

        assert stats["total_epics"] == 2
        assert stats["total_stories"] == 3
        assert stats["stories_per_phase"] == {"MVP": 2, "V1": 1}
        assert stats["stories_per_priority"] == {"P0": 2, "P1": 1}

    def test_get_stats_empty(self) -> None:
        csv_content = self.gen.generate([], [])
        stats = self.gen.get_stats(csv_content)

        assert stats["total_epics"] == 0
        assert stats["total_stories"] == 0
