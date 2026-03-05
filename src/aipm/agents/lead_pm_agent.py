"""Agent H — Lead PM Agent (Collection, Dedup, Ranking, Conflict Resolution & Artifacts).

Synthesizes all upstream agent findings into a consolidated, prioritized,
conflict-resolved set of product recommendations, then generates all pipeline artifacts.
"""

import json
import logging
import re
from collections import defaultdict
from datetime import UTC
from pathlib import Path

from aipm.agents.base import BaseAgent
from aipm.core.backlog_generator import BacklogGenerator
from aipm.core.decision_log_generator import DecisionLogGenerator
from aipm.core.experiment_generator import ExperimentPlanGenerator
from aipm.core.final_plan_generator import FinalPlanGenerator
from aipm.core.policy import PolicyPack
from aipm.core.prd_generator import PRDGenerator
from aipm.core.roadmap_generator import RoadmapGenerator
from aipm.core.template_engine import load_template, render_template
from aipm.core.token_tracker import TokenTracker
from aipm.schemas.config import RunConfig
from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import AgentOutput, EvidenceItem, Finding

logger = logging.getLogger(__name__)

# ── Confidence ordering for dedup (higher = keep) ──
CONFIDENCE_RANK = {"validated": 3, "directional": 2, "speculative": 1}

# ── LLM prompts ──
DEDUP_SYSTEM = """\
You are an expert data analyst. Given a list of product findings from multiple \
agents, identify clusters of duplicate or substantially overlapping findings. \
Two findings overlap if they describe the same issue, feature, risk, or insight \
even when phrased differently or from different perspectives.

Return a JSON object:
{
  "clusters": [
    {
      "finding_ids": ["id-1", "id-2"],
      "reason": "Both describe the same notification fatigue problem"
    }
  ]
}

Rules:
- Only group findings that are genuinely about the same topic.
- A finding can appear in at most one cluster.
- Return ONLY valid JSON. No markdown fences."""

RANKING_SYSTEM = """\
You are a senior product strategist. Score each finding on four dimensions \
(1-10 scale):
- user_impact: How much does this affect end users?
- business_value: How much business value does addressing this create?
- effort: How much effort is required to address? (higher = more effort)
- risk: How risky is it to ignore this? (higher = riskier to ignore)

Return a JSON object:
{
  "scores": [
    {
      "finding_id": "customer-001",
      "user_impact": 8,
      "business_value": 7,
      "effort": 4,
      "risk": 6
    }
  ]
}

Rules:
- Score every finding provided.
- DIFFERENTIATION IS MANDATORY: No two findings should have identical scores across \
all four dimensions. Use the full 1-10 range. A critical accessibility blocker affecting \
all users must score very differently from a nice-to-have instrumentation improvement. \
Vary scores by at least 1 point per dimension between different-severity findings.
- Critical/high impact findings should have user_impact >= 7. Medium findings: 4-6. Low: 1-3.
- Effort should reflect actual implementation complexity — a simple UI color fix (effort=2) \
is very different from a full VPAT audit (effort=7) or an architectural change (effort=9).
- Return ONLY valid JSON. No markdown fences."""

CONFLICT_SYSTEM = """\
You are an expert product strategist and conflict mediator. Identify \
contradictions or tensions between findings. A conflict exists when one \
finding's recommendation contradicts or undermines another (e.g., a growth \
feature vs a privacy risk that would block it).

Return a JSON object:
{
  "conflicts": [
    {
      "finding_a": "requirements-003",
      "finding_b": "risk-002",
      "description": "Feature requires extensive user data but risk agent flags PII collection as blocker",
      "resolution": "Implement data minimization: collect only essential fields with explicit consent",
      "reasoning": "Privacy compliance takes precedence per policy, but feature can proceed with reduced scope"
    }
  ]
}

Rules:
- Only flag genuine contradictions, not complementary findings.
- Provide a concrete resolution for each conflict.
- Return ONLY valid JSON. No markdown fences."""


class LeadPMAgent(BaseAgent):
    """Synthesizes all upstream findings into prioritized, consolidated recommendations."""

    agent_id = "lead_pm"
    agent_name = "Lead PM Agent"

    def __init__(
        self,
        llm_client: object,
        run_config: RunConfig,
        policy_pack: PolicyPack,
        context_packet: ContextPacket,
        all_agent_outputs: list[AgentOutput],
        token_tracker: TokenTracker | None = None,
    ) -> None:
        super().__init__(llm_client, run_config, policy_pack, context_packet, token_tracker)
        self.all_agent_outputs = all_agent_outputs

        # Intermediate results stored for artifact generation in Part 2
        self.evidence_index: dict[str, list[str]] = {}
        self.dedup_log: list[dict] = []
        self.ranked_findings: list[dict] = []
        self.conflicts: list[dict] = []
        self.consolidated_findings: list[Finding] = []

    async def analyze(self) -> AgentOutput:
        """Run all four phases and return meta-findings about the consolidation."""
        # Phase 1 — Collect & Merge
        all_findings = self._collect_all_findings()
        self.evidence_index = self._build_evidence_index(all_findings)
        self.logger.info(
            "Phase 1: Collected %d findings, %d evidence sources", len(all_findings), len(self.evidence_index)
        )

        # Phase 2 — Deduplicate
        deduped = await self._deduplicate(all_findings)
        self.logger.info(
            "Phase 2: %d findings after dedup (removed %d)", len(deduped), len(all_findings) - len(deduped)
        )

        # Phase 3 — Rank & Prioritize
        self.ranked_findings = await self._rank_findings(deduped)
        self.logger.info("Phase 3: Ranked %d findings", len(self.ranked_findings))

        # Phase 4 — Conflict Resolution
        self.conflicts = await self._resolve_conflicts(deduped)
        self.logger.info("Phase 4: Resolved %d conflicts", len(self.conflicts))

        # Store consolidated findings for Part 2 artifact generation
        self.consolidated_findings = deduped

        # Build meta-findings about the consolidation process
        meta_findings = self._build_meta_findings(all_findings, deduped)
        summary = self._build_summary(all_findings, deduped)

        output = AgentOutput(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            run_id=self.run_config.run_id,
            findings=meta_findings,
            summary=summary,
        )
        self.save_output(output)

        # Save intermediate results for Part 2
        self._save_intermediate_results()

        return output

    # ── Phase 1: Collect & Merge ──

    def _collect_all_findings(self) -> list[Finding]:
        """Collect all findings from all agent outputs into a single list."""
        findings: list[Finding] = []
        for output in self.all_agent_outputs:
            findings.extend(output.findings)
        return findings

    def _build_evidence_index(self, findings: list[Finding]) -> dict[str, list[str]]:
        """Build source_id → list of finding IDs that reference it."""
        index: dict[str, list[str]] = defaultdict(list)
        for f in findings:
            for ev in f.evidence:
                index[ev.source_id].append(f.id)
        return dict(index)

    # ── Phase 2: Deduplicate ──

    async def _deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Use LLM to identify duplicates, then merge clusters."""
        if len(findings) <= 1:
            return findings

        # Build finding summary for LLM
        finding_summaries = []
        for f in findings:
            finding_summaries.append(
                f"- [{f.id}] ({f.type}, {f.agent_id}, impact={f.impact}, "
                f"confidence={f.confidence}): {f.title} — {f.description[:200]}"
            )
        user_prompt = "Identify duplicate or overlapping findings:\n\n" + "\n".join(finding_summaries)

        response = await self.call_llm(DEDUP_SYSTEM, user_prompt, response_format={"type": "json_object"})
        clusters = self._parse_json_field(response, "clusters", [])

        # Build a set of finding IDs to remove (keep highest-confidence per cluster)
        findings_by_id = {f.id: f for f in findings}
        remove_ids: set[str] = set()

        for cluster in clusters:
            ids = cluster.get("finding_ids", [])
            reason = cluster.get("reason", "duplicate")
            valid_ids = [fid for fid in ids if fid in findings_by_id]
            if len(valid_ids) < 2:
                continue

            # Sort by confidence rank descending, keep the first
            sorted_ids = sorted(
                valid_ids,
                key=lambda fid: CONFIDENCE_RANK.get(findings_by_id[fid].confidence, 0),
                reverse=True,
            )
            keeper_id = sorted_ids[0]
            keeper = findings_by_id[keeper_id]

            # Merge evidence from duplicates into the keeper
            for dup_id in sorted_ids[1:]:
                dup = findings_by_id[dup_id]
                existing_source_ids = {ev.source_id for ev in keeper.evidence}
                for ev in dup.evidence:
                    if ev.source_id not in existing_source_ids:
                        keeper.evidence.append(ev)
                        existing_source_ids.add(ev.source_id)
                remove_ids.add(dup_id)

            self.dedup_log.append(
                {
                    "cluster": valid_ids,
                    "kept": keeper_id,
                    "removed": [fid for fid in sorted_ids[1:]],
                    "reason": reason,
                }
            )

        return [f for f in findings if f.id not in remove_ids]

    # ── Phase 3: Rank & Prioritize ──

    async def _rank_findings(self, findings: list[Finding]) -> list[dict]:
        """Use LLM to score findings and calculate weighted priority."""
        if not findings:
            return []

        finding_summaries = []
        for f in findings:
            finding_summaries.append(f"- [{f.id}] ({f.type}, impact={f.impact}): {f.title} — {f.description[:200]}")
        user_prompt = "Score each finding:\n\n" + "\n".join(finding_summaries)

        response = await self.call_llm(RANKING_SYSTEM, user_prompt, response_format={"type": "json_object"})
        scores_list = self._parse_json_field(response, "scores", [])

        # Build ranked list with priority score
        scores_by_id = {s["finding_id"]: s for s in scores_list if "finding_id" in s}
        ranked: list[dict] = []

        for f in findings:
            s = scores_by_id.get(f.id, {})
            user_impact = s.get("user_impact", 5)
            business_value = s.get("business_value", 5)
            effort = s.get("effort", 5)
            risk = s.get("risk", 5)

            # Weighted priority: higher = more important
            denominator = effort * 0.20 + risk * 0.15
            if denominator == 0:
                denominator = 0.01
            priority_score = (user_impact * 0.35 + business_value * 0.30) / denominator

            ranked.append(
                {
                    "finding_id": f.id,
                    "title": f.title,
                    "user_impact": user_impact,
                    "business_value": business_value,
                    "effort": effort,
                    "risk": risk,
                    "priority_score": round(priority_score, 3),
                }
            )

        ranked.sort(key=lambda r: r["priority_score"], reverse=True)
        return ranked

    # ── Phase 4: Conflict Resolution ──

    async def _resolve_conflicts(self, findings: list[Finding]) -> list[dict]:
        """Use LLM to identify and resolve contradictions between findings."""
        if len(findings) <= 1:
            return []

        finding_summaries = []
        for f in findings:
            finding_summaries.append(
                f"- [{f.id}] ({f.type}, {f.agent_id}, impact={f.impact}): {f.title} — {f.description[:200]}"
            )

        policy_context = (
            f"\nPolicy rules to apply:\n"
            f"- Block on critical privacy: {self.policy_pack.risk_gating.block_on_critical_privacy}\n"
            f"- Block on critical security: {self.policy_pack.risk_gating.block_on_critical_security}\n"
            f"- Max unmitigated high risks: {self.policy_pack.risk_gating.max_unmitigated_high_risks}\n"
        )

        user_prompt = (
            "Identify contradictions between these findings and resolve them:\n\n"
            + "\n".join(finding_summaries)
            + policy_context
        )

        response = await self.call_llm(CONFLICT_SYSTEM, user_prompt, response_format={"type": "json_object"})
        return self._parse_json_field(response, "conflicts", [])

    # ── Helpers ──

    def _parse_json_field(self, response: str, field: str, default: list) -> list:
        """Parse a JSON response and extract a specific field."""
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return default
            else:
                return default
        return data.get(field, default)

    def _build_meta_findings(self, original: list[Finding], deduped: list[Finding]) -> list[Finding]:
        """Create meta-findings about the consolidation process."""
        findings: list[Finding] = []

        # Finding 1: Consolidation summary
        findings.append(
            Finding(
                id="lead_pm-001",
                agent_id=self.agent_id,
                type="insight",
                title="Pipeline Consolidation Summary",
                description=(
                    f"Consolidated {len(original)} findings from "
                    f"{len(self.all_agent_outputs)} agents into {len(deduped)} "
                    f"unique findings. Removed {len(original) - len(deduped)} duplicates. "
                    f"Identified {len(self.conflicts)} cross-agent conflicts."
                ),
                impact="high",
                confidence="validated",
                evidence=[
                    EvidenceItem(
                        source_id=o.agent_id,
                        source_type="doc",
                        excerpt=f"{o.agent_name}: {len(o.findings)} findings",
                    )
                    for o in self.all_agent_outputs
                ],
                tags=["consolidation", "meta"],
                metadata={
                    "original_count": len(original),
                    "deduped_count": len(deduped),
                    "duplicates_removed": len(original) - len(deduped),
                    "conflicts_resolved": len(self.conflicts),
                    "evidence_sources": len(self.evidence_index),
                },
            )
        )

        # Finding 2: Top priorities
        if self.ranked_findings:
            top_5 = self.ranked_findings[:5]
            findings.append(
                Finding(
                    id="lead_pm-002",
                    agent_id=self.agent_id,
                    type="recommendation",
                    title="Top Priority Findings",
                    description=(
                        "Highest priority items based on weighted scoring "
                        "(user_impact×0.35 + business_value×0.30) / (effort×0.20 + risk×0.15): "
                        + "; ".join(f"{r['title']} (score={r['priority_score']})" for r in top_5)
                    ),
                    impact="critical",
                    confidence="directional",
                    evidence=[
                        EvidenceItem(
                            source_id=r["finding_id"],
                            source_type="doc",
                            excerpt=f"Priority score: {r['priority_score']}",
                        )
                        for r in top_5
                    ],
                    tags=["prioritization", "meta"],
                    metadata={"top_priorities": top_5},
                )
            )

        # Finding 3: Conflict report
        if self.conflicts:
            findings.append(
                Finding(
                    id="lead_pm-003",
                    agent_id=self.agent_id,
                    type="insight",
                    title="Cross-Agent Conflict Resolution Report",
                    description=(
                        f"Resolved {len(self.conflicts)} conflicts between agent findings. "
                        + "; ".join(
                            f"{c.get('finding_a', '?')} vs {c.get('finding_b', '?')}: {c.get('description', '')}"
                            for c in self.conflicts[:3]
                        )
                    ),
                    impact="high",
                    confidence="directional",
                    evidence=[
                        EvidenceItem(
                            source_id=c.get("finding_a", "unknown"),
                            source_type="doc",
                            excerpt=c.get("description", ""),
                        )
                        for c in self.conflicts
                    ],
                    tags=["conflicts", "meta"],
                    metadata={"conflicts": self.conflicts},
                )
            )

        return findings

    def _build_summary(self, original: list[Finding], deduped: list[Finding]) -> str:
        """Build a summary of the consolidation process."""
        top_title = self.ranked_findings[0]["title"] if self.ranked_findings else "N/A"
        return (
            f"Consolidated {len(original)} findings into {len(deduped)} unique items. "
            f"Removed {len(original) - len(deduped)} duplicates, resolved {len(self.conflicts)} conflicts. "
            f"Top priority: {top_title}."
        )

    def _save_intermediate_results(self) -> None:
        """Save intermediate results for Part 2 artifact generation."""
        results_dir = Path(self.run_config.output_dir) / self.run_config.run_id / "findings"
        results_dir.mkdir(parents=True, exist_ok=True)

        intermediate = {
            "evidence_index": self.evidence_index,
            "dedup_log": self.dedup_log,
            "ranked_findings": self.ranked_findings,
            "conflicts": self.conflicts,
            "consolidated_finding_ids": [f.id for f in self.consolidated_findings],
        }

        path = results_dir / "lead_pm_intermediate.json"
        path.write_text(json.dumps(intermediate, indent=2, default=str), encoding="utf-8")
        self.logger.info("Saved intermediate results to %s", path)

    # ── Artifact Generation (Part 2) ──

    def _artifacts_dir(self) -> Path:
        """Return the artifacts directory, creating it if needed."""
        d = Path(self.run_config.output_dir) / self.run_config.run_id / "artifacts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _gate_result(self) -> dict:
        """Load the risk gate result if available."""
        gate_path = Path(self.run_config.output_dir) / self.run_config.run_id / "findings" / "risk_gate_result.json"
        if gate_path.exists():
            return json.loads(gate_path.read_text(encoding="utf-8"))
        return {"passed": True, "blockers": [], "warnings": []}

    def _findings_by_agent(self, agent_id: str) -> list[Finding]:
        """Return findings from a specific agent."""
        for output in self.all_agent_outputs:
            if output.agent_id == agent_id:
                return list(output.findings)
        return []

    async def generate_recommendation(self) -> str:
        """Determine the overall product recommendation based on risk gate, policy, and findings.

        The policy's ``max_unmitigated_high_risks`` controls how many blockers
        the pipeline tolerates before rejecting outright.  A relaxed policy
        (e.g. startup_fast with max=5) needs more blockers to reach
        ``do_not_pursue`` than a strict policy (default with max=2).

        Returns one of: proceed, proceed_with_mitigations, validate_first, do_not_pursue.
        """
        gate = self._gate_result()
        speculative_count = sum(1 for f in self.consolidated_findings if f.confidence == "speculative")
        total = len(self.consolidated_findings) or 1
        speculative_ratio = speculative_count / total

        if gate.get("blockers"):
            # Policy-aware threshold: relaxed policies tolerate more blockers
            tolerance = self.policy_pack.risk_gating.max_unmitigated_high_risks
            reject_threshold = tolerance + 1  # default=3, startup=6

            if len(gate["blockers"]) >= reject_threshold:
                return "do_not_pursue"
            # Blockers exist but within policy tolerance → validate first
            return "validate_first"

        if speculative_ratio > 0.5:
            return "validate_first"

        if gate.get("warnings"):
            return "proceed_with_mitigations"

        return "proceed"

    async def generate_prd(self) -> str:
        """Generate a PRD using PRDGenerator (with findings-based fallbacks), save to artifacts/prd.md."""
        recommendation = await self.generate_recommendation()

        generator = PRDGenerator(
            llm_client=self.llm_client,
            context_packet=self.context_packet,
            all_findings=self.consolidated_findings,
            policy_pack=self.policy_pack,
            run_config=self.run_config,
            all_agent_outputs=self.all_agent_outputs,
        )
        prd_content = await generator.generate(recommendation)

        path = self._artifacts_dir() / "prd.md"
        path.write_text(prd_content, encoding="utf-8")
        self.logger.info("Saved PRD to %s", path)
        return str(path)

    async def generate_roadmap(self) -> dict:
        """Build roadmap.json using RoadmapGenerator, save to artifacts/roadmap.json."""
        generator = RoadmapGenerator(
            llm_client=self.llm_client,
            all_findings=self.consolidated_findings,
            run_config=self.run_config,
            product_name=self.context_packet.product_name,
        )
        roadmap = await generator.generate()

        path = self._artifacts_dir() / "roadmap.json"
        generator.save(roadmap, str(path))
        self.logger.info("Saved roadmap to %s", path)
        return roadmap

    async def generate_experiment_plan(self) -> str:
        """Generate experiment plan using ExperimentPlanGenerator, save to artifacts/experiment_plan.md."""
        generator = ExperimentPlanGenerator(
            llm_client=self.llm_client,
            metrics_findings=self._findings_by_agent("metrics"),
            risk_findings=self._findings_by_agent("risk"),
            policy_pack=self.policy_pack,
            run_config=self.run_config,
            product_name=self.context_packet.product_name,
        )
        content = await generator.generate()

        path = self._artifacts_dir() / "experiment_plan.md"
        generator.save(content, str(path))
        self.logger.info("Saved experiment plan to %s", path)
        return str(path)

    async def generate_decision_log(self) -> str:
        """Generate decision log using DecisionLogGenerator."""
        # Transform dedup_log into the format expected by DecisionLogGenerator
        dedup_decisions = []
        for entry in self.dedup_log:
            kept_id = entry["kept"]
            # Find the kept finding to get its title
            kept_finding = next(
                (f for f in self.consolidated_findings if f.id == kept_id),
                None,
            )
            dedup_decisions.append(
                {
                    "kept_id": kept_id,
                    "finding_title": kept_finding.title if kept_finding else kept_id,
                    "merged_ids": entry.get("removed", []),
                    "reason": entry.get("reason", "Duplicate findings"),
                    "confidence": "validated",
                    "kept_rationale": "Highest confidence score among duplicates",
                }
            )

        # Transform conflicts into the format expected by DecisionLogGenerator
        conflict_resolutions = []
        for conflict in self.conflicts:
            conflict_resolutions.append(
                {
                    "id": f"{conflict.get('finding_a', '?')}-vs-{conflict.get('finding_b', '?')}",
                    "finding_a": conflict.get("finding_a", "?"),
                    "finding_b": conflict.get("finding_b", "?"),
                    "what_conflicted": conflict.get("description", ""),
                    "resolution": conflict.get("resolution", "N/A"),
                    "alternatives": conflict.get("reasoning", "Accept either finding"),
                    "confidence": "directional",
                }
            )

        gate = self._gate_result()

        generator = DecisionLogGenerator(
            dedup_decisions=dedup_decisions,
            conflict_resolutions=conflict_resolutions,
            risk_gate_results=gate,
            policy_pack=self.policy_pack,
            product_name=self.context_packet.product_name,
            run_id=self.run_config.run_id,
        )
        content = generator.generate()

        path = self._artifacts_dir() / "decision_log.md"
        generator.save(content, str(path))
        self.logger.info("Saved decision log to %s", path)
        return str(path)

    async def generate_backlog(self) -> str:
        """Generate backlog.csv using BacklogGenerator."""
        requirements = self._findings_by_agent("requirements")
        feasibility = self._findings_by_agent("feasibility")

        generator = BacklogGenerator()
        csv_content = generator.generate(
            requirements, feasibility, tickets=self.context_packet.tickets
        )

        path = self._artifacts_dir() / "backlog.csv"
        generator.save_csv(csv_content, str(path))
        self.logger.info("Saved backlog to %s", path)
        return str(path)

    async def generate_all_artifacts(self) -> dict[str, str]:
        """Run all artifact generation methods. Return dict of artifact paths."""
        paths: dict[str, str] = {}

        recommendation = await self.generate_recommendation()
        paths["recommendation"] = recommendation

        paths["prd"] = await self.generate_prd()
        paths["roadmap"] = str(self._artifacts_dir() / "roadmap.json")
        await self.generate_roadmap()
        paths["experiment_plan"] = await self.generate_experiment_plan()
        paths["decision_log"] = await self.generate_decision_log()
        paths["backlog"] = await self.generate_backlog()

        # Generate final_plan.json — the master consolidated output
        paths["final_plan"] = await self.generate_final_plan()

        self.logger.info("Generated %d artifacts: %s", len(paths), list(paths.keys()))
        return paths

    async def generate_final_plan(self) -> str:
        """Generate final_plan.json using the FinalPlanGenerator.

        Returns:
            Path to the saved final_plan.json file.
        """
        # Collect all findings from all agents
        all_findings = self._collect_all_findings()

        # Get lead_pm output (last output added by analyze())
        lead_pm_output = None
        for output in reversed(self.all_agent_outputs):
            if output.agent_id == self.agent_id:
                lead_pm_output = output
                break

        # If analyze() was already called, use its output saved on self
        if lead_pm_output is None:
            lead_pm_output = AgentOutput(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                run_id=self.run_config.run_id,
                findings=[],
                summary="",
            )

        # Build artifact_paths without final_plan (to avoid circular ref)
        existing_artifacts = {
            k: v for k, v in self._current_artifact_paths().items()
            if k != "final_plan"
        }

        generator = FinalPlanGenerator(
            llm_client=self.llm_client,
            lead_pm_output=lead_pm_output,
            all_findings=all_findings,
            policy_pack=self.policy_pack,
            run_config=self.run_config,
            artifact_paths=existing_artifacts,
            product_name=self.context_packet.product_name,
        )

        plan = await generator.generate()
        output_path = str(self._artifacts_dir() / "final_plan.json")
        generator.save(plan, output_path)
        self.logger.info("Saved final_plan.json to %s", output_path)
        return output_path

    def _current_artifact_paths(self) -> dict[str, str]:
        """Return artifact paths generated so far (for final_plan cross-refs)."""
        artifacts_dir = self._artifacts_dir()
        paths: dict[str, str] = {}
        for name in ("prd.md", "roadmap.json", "experiment_plan.md", "decision_log.md", "backlog.csv"):
            p = artifacts_dir / name
            if p.exists():
                key = name.split(".")[0]
                if key == "experiment_plan":
                    key = "experiment_plan"
                paths[key] = str(p)
        return paths
