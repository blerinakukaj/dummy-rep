"""Roadmap JSON generator for the AIPM pipeline.

Produces a structured roadmap with themes, milestones, sequencing,
critical path analysis, and phased delivery plan derived from
requirements and feasibility findings.
"""

import json
import logging
import re

from aipm.schemas.config import RunConfig
from aipm.schemas.findings import Finding

logger = logging.getLogger(__name__)

ROADMAP_SYSTEM = """\
You are a senior technical program manager building a product roadmap.

Given a set of requirement findings (with priorities, phases, and complexity)
and feasibility findings (with dependencies, blocking flags, and phasing
recommendations), produce a structured roadmap JSON object.

Rules:
- Group related features into 3-5 strategic themes.
- Create milestones for each phase (MVP, V1, V2).
- Each milestone must list specific requirement finding IDs as items.
- Dependencies between milestones must be explicit.
- Success criteria must be specific and measurable.
- The critical path is the longest chain of dependent milestones.
- Sequencing entries explain WHY one milestone must precede another.

Return ONLY a valid JSON object with this exact structure:
{
  "product_name": "<string>",
  "themes": [
    {"id": "theme-N", "title": "<string>", "description": "<string>", "finding_ids": ["<finding_id>", ...]}
  ],
  "milestones": [
    {
      "id": "ms-N",
      "name": "<string>",
      "phase": "mvp" | "v1" | "v2",
      "description": "<string>",
      "items": ["<requirement_finding_id>", ...],
      "dependencies": ["<milestone_id>", ...],
      "success_criteria": "<string>"
    }
  ],
  "sequencing": [
    {"from_milestone": "<milestone_id>", "to_milestone": "<milestone_id>", "reason": "<string>"}
  ],
  "critical_path": ["<milestone_id>", ...],
  "phases": {
    "mvp": {"goal": "<string>", "milestones": ["<milestone_id>", ...]},
    "v1":  {"goal": "<string>", "milestones": ["<milestone_id>", ...]},
    "v2":  {"goal": "<string>", "milestones": ["<milestone_id>", ...]}
  }
}

Do NOT wrap the JSON in markdown fences. Return raw JSON only."""


class RoadmapGenerator:
    """Generates a structured product roadmap from pipeline findings."""

    def __init__(
        self,
        llm_client: object,
        all_findings: list[Finding],
        run_config: RunConfig,
    ) -> None:
        self.llm_client = llm_client
        self.all_findings = all_findings
        self.run_config = run_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self) -> dict:
        """Generate the complete roadmap.json structure."""

        feasibility_findings = self._findings_by_agent("feasibility")
        requirement_findings = self._findings_by_agent("requirements")

        # Build context sections for the LLM
        phase_info = self._extract_phase_info(feasibility_findings)
        grouped_requirements = self._group_requirements_by_phase(requirement_findings, feasibility_findings)

        user_prompt = self._build_prompt(phase_info, grouped_requirements, feasibility_findings, requirement_findings)

        response = await self._call_llm(ROADMAP_SYSTEM, user_prompt)
        roadmap = self._parse_response(response)

        logger.info(
            "Roadmap generated — %d themes, %d milestones, critical path length %d",
            len(roadmap.get("themes", [])),
            len(roadmap.get("milestones", [])),
            len(roadmap.get("critical_path", [])),
        )
        return roadmap

    def save(self, roadmap: dict, output_path: str) -> str:
        """Save the roadmap as formatted JSON and return the file path."""
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(roadmap, fh, indent=2, ensure_ascii=False)
        logger.info("Roadmap saved to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _findings_by_agent(self, agent_id: str) -> list[Finding]:
        """Filter findings by originating agent."""
        return [f for f in self.all_findings if f.agent_id == agent_id]

    def _extract_phase_info(self, feasibility_findings: list[Finding]) -> str:
        """Extract phasing and delivery plan details from feasibility findings."""
        lines: list[str] = []
        for f in feasibility_findings:
            phase = f.metadata.get("phase", "unassigned")
            complexity = f.metadata.get("complexity", "unknown")
            blocking = f.metadata.get("blocking", False)
            deps = f.metadata.get("dependencies", [])
            lines.append(
                f"- [{f.id}] {f.title} | phase={phase}, complexity={complexity}, blocking={blocking}, deps={deps}"
            )
        return "\n".join(lines) if lines else "(No feasibility findings available)"

    def _group_requirements_by_phase(
        self,
        requirement_findings: list[Finding],
        feasibility_findings: list[Finding],
    ) -> dict[str, list[str]]:
        """Group requirement finding IDs by phase (MVP / V1 / V2).

        Phase is determined first from the requirement's own metadata, then
        cross-referenced with feasibility findings.
        """
        # Build a lookup: requirement_id → phase from feasibility
        feasibility_phase_map: dict[str, str] = {}
        for f in feasibility_findings:
            phase = f.metadata.get("phase", "").lower()
            # Feasibility findings may reference requirement IDs in their deps
            for dep_id in f.metadata.get("dependencies", []):
                if dep_id and phase:
                    feasibility_phase_map[dep_id] = phase

        groups: dict[str, list[str]] = {"mvp": [], "v1": [], "v2": [], "unassigned": []}
        for f in requirement_findings:
            phase = f.metadata.get("phase", "").lower() or feasibility_phase_map.get(f.id, "").lower()
            if phase in ("mvp", "v1", "v2"):
                groups[phase].append(f.id)
            else:
                groups["unassigned"].append(f.id)

        return groups

    def _build_prompt(
        self,
        phase_info: str,
        grouped_requirements: dict[str, list[str]],
        feasibility_findings: list[Finding],
        requirement_findings: list[Finding],
    ) -> str:
        """Construct the user-facing prompt with all relevant context."""

        # Summarise requirements
        req_lines: list[str] = []
        for f in requirement_findings:
            meta = f.metadata
            req_lines.append(
                f"- [{f.id}] {f.title} (type={f.type}, impact={f.impact}, "
                f"priority={meta.get('priority', 'N/A')}, "
                f"complexity={meta.get('complexity', 'N/A')}, "
                f"phase={meta.get('phase', 'N/A')})"
            )
        req_section = "\n".join(req_lines) if req_lines else "(none)"

        # Summarise groupings
        group_lines: list[str] = []
        for phase, ids in grouped_requirements.items():
            if ids:
                group_lines.append(f"  {phase.upper()}: {', '.join(ids)}")
        group_section = "\n".join(group_lines) if group_lines else "(no groupings)"

        # Product name from context (fallback)
        product_name = self.run_config.input_path.rstrip("/\\").split("/")[-1].split("\\")[-1]

        return (
            f"Product: {product_name}\n\n"
            f"--- REQUIREMENT FINDINGS ---\n{req_section}\n\n"
            f"--- PHASE GROUPINGS ---\n{group_section}\n\n"
            f"--- FEASIBILITY & DELIVERY DETAILS ---\n{phase_info}\n\n"
            "Generate the roadmap JSON with themes, milestones, sequencing, "
            "critical path, and phase goals.  Every milestone must reference "
            "actual requirement finding IDs from the list above."
        )

    def _parse_response(self, response: str) -> dict:
        """Parse the LLM response into a roadmap dict with fallback handling."""
        # Try direct parse
        try:
            roadmap = json.loads(response)
            if isinstance(roadmap, dict):
                return self._validate_structure(roadmap)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown fences
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if match:
            try:
                roadmap = json.loads(match.group(1))
                if isinstance(roadmap, dict):
                    return self._validate_structure(roadmap)
            except json.JSONDecodeError:
                pass

        # Last resort: find first { … last }
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                roadmap = json.loads(response[start : end + 1])
                if isinstance(roadmap, dict):
                    return self._validate_structure(roadmap)
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse LLM roadmap response; returning empty structure")
        return self._empty_roadmap()

    def _validate_structure(self, roadmap: dict) -> dict:
        """Ensure all top-level keys exist, filling defaults for any missing."""
        defaults = self._empty_roadmap()
        for key, default_value in defaults.items():
            if key not in roadmap:
                roadmap[key] = default_value
        return roadmap

    @staticmethod
    def _empty_roadmap() -> dict:
        """Return an empty but structurally valid roadmap."""
        return {
            "product_name": "",
            "themes": [],
            "milestones": [],
            "sequencing": [],
            "critical_path": [],
            "phases": {
                "mvp": {"goal": "", "milestones": []},
                "v1": {"goal": "", "milestones": []},
                "v2": {"goal": "", "milestones": []},
            },
        }

    # ------------------------------------------------------------------
    # LLM call (dual-provider)
    # ------------------------------------------------------------------

    async def _call_llm(self, system: str, user: str) -> str:
        """Call the LLM using the OpenAI provider API."""
        response = await self.llm_client.chat.completions.create(
            model=self.run_config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=self.run_config.temperature,
        )
        return response.choices[0].message.content or ""
