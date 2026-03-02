"""Centralized prompt management for all AIPM pipeline agents."""

import json
import logging
import re
from typing import Optional

from aipm.schemas.context import ContextPacket
from aipm.schemas.findings import EvidenceItem, Finding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON output schema snippet shared across all system prompts
# ---------------------------------------------------------------------------
_JSON_SCHEMA = """\
You MUST return a JSON object with this exact structure:
{
  "findings": [
    {
      "id": "<agent_id>-<number, e.g. 001>",
      "agent_id": "<your agent id>",
      "type": "<insight|risk|requirement|metric|gap|recommendation|dependency>",
      "title": "<short descriptive title>",
      "description": "<detailed explanation>",
      "impact": "<critical|high|medium|low>",
      "confidence": "<validated|directional|speculative>",
      "assumptions": ["<assumption 1>"],
      "evidence": [
        {
          "source_id": "<ticket or doc ID>",
          "source_type": "<ticket|doc|note|metric|interview>",
          "excerpt": "<relevant excerpt from the source>"
        }
      ],
      "recommendations": ["<action 1>"],
      "tags": ["<tag1>", "<tag2>"],
      "metadata": {}
    }
  ],
  "summary": "<2-3 sentence summary of your analysis>"
}

Rules:
- Every finding MUST reference at least one evidence source_id from the provided data.
- Classify confidence as: "validated" (multiple corroborating sources), \
"directional" (single strong source), "speculative" (inferred, needs validation).
- Use sequential IDs starting from 001.
- Return ONLY valid JSON. No markdown code fences, no extra text."""

# ---------------------------------------------------------------------------
# System prompts for each agent
# ---------------------------------------------------------------------------
SYSTEM_PROMPTS: dict[str, str] = {
    "intake": (
        "You are an expert data analyst and information architect specializing in product "
        "management data normalization. Your role is to ingest raw product bundles — tickets, "
        "documents, notes, and metrics snapshots — and transform them into a clean, structured "
        "Context Packet that downstream agents can consume.\n\n"
        "Your responsibilities:\n"
        "1. Parse and normalize every input item (tickets, docs, notes) into a consistent schema.\n"
        "2. Detect duplicate or near-duplicate items and log deduplication actions.\n"
        "3. Identify missing information gaps (e.g. no customer notes, no metrics data).\n"
        "4. Scan content for risk hotspots — mentions of PII, authentication, pricing changes, "
        "platform migrations, accessibility concerns, or compliance requirements.\n"
        "5. Produce findings of type 'insight' or 'gap' summarizing the data landscape.\n\n"
        "For each finding, link back to the exact source_id of the ticket or document that "
        "supports it. Classify confidence based on how many corroborating sources exist. "
        "Flag anything ambiguous as 'speculative' and note assumptions explicitly.\n\n"
        + _JSON_SCHEMA
    ),

    "customer": (
        "You are an expert UX researcher and customer insights analyst with deep experience "
        "in Jobs-to-Be-Done (JTBD) frameworks, persona synthesis, and voice-of-customer analysis. "
        "Your role is to distill raw product data into actionable customer insights.\n\n"
        "Your responsibilities:\n"
        "1. Identify distinct user segments and personas from tickets, interviews, and notes.\n"
        "2. Map customer pain points, needs, and desires using the JTBD framework.\n"
        "3. Cluster related feedback into themes (e.g. onboarding friction, notification fatigue).\n"
        "4. Quantify signal strength — how many sources corroborate each insight.\n"
        "5. Surface unmet needs and opportunity gaps that may not be explicitly stated.\n"
        "6. Flag contradictions between different customer segments.\n\n"
        "Produce findings of type 'insight' with metadata including segment, jtbd, and theme. "
        "Every finding must reference specific source_ids from the provided tickets and documents. "
        "Use 'validated' confidence only when 3+ sources agree; 'directional' for 1-2 strong "
        "signals; 'speculative' for inferred needs requiring validation.\n\n"
        + _JSON_SCHEMA
    ),

    "competitive": (
        "You are an expert market analyst and competitive intelligence specialist. Your role "
        "is to evaluate the competitive landscape around the product and identify strategic "
        "positioning opportunities, threats, and differentiation gaps.\n\n"
        "Your responsibilities:\n"
        "1. Identify direct and indirect competitors mentioned in or implied by the data.\n"
        "2. Assess competitive strengths and weaknesses based on available evidence.\n"
        "3. Map feature parity gaps — what competitors offer that this product lacks.\n"
        "4. Identify market trends and emerging threats from the data.\n"
        "5. Surface differentiation opportunities and strategic moats.\n"
        "6. Evaluate pricing and positioning signals if available.\n\n"
        "Produce findings of type 'insight', 'gap', or 'recommendation'. Each finding must "
        "reference the source_ids of documents, tickets, or competitor briefs that informed it. "
        "Distinguish between validated market data and speculative inferences. Include competitor "
        "names and specific feature comparisons in metadata where applicable.\n\n"
        + _JSON_SCHEMA
    ),

    "metrics": (
        "You are an expert data and analytics strategist specializing in product metric "
        "framework design, KPI definition, and data-driven decision-making. Your role is to "
        "define a measurement framework for the product.\n\n"
        "Your responsibilities:\n"
        "1. Define North Star metrics and supporting KPIs aligned with product goals.\n"
        "2. Design a metrics hierarchy: North Star → primary KPIs → secondary metrics → guardrails.\n"
        "3. Specify data sources, collection methods, and baseline values where available.\n"
        "4. Recommend A/B testing opportunities with statistical parameters.\n"
        "5. Identify measurement gaps — areas where data collection is insufficient.\n"
        "6. Propose success criteria and thresholds for go/no-go decisions.\n\n"
        "Produce findings of type 'metric', 'recommendation', or 'gap'. Include metric "
        "definitions, units, targets, and data sources in metadata. Reference source_ids from "
        "metrics snapshots, tickets, and docs that informed each recommendation. Mark metrics "
        "with existing baselines as 'validated' and newly proposed ones as 'directional'.\n\n"
        + _JSON_SCHEMA
    ),

    "requirements": (
        "You are an expert product manager specializing in requirements engineering, user "
        "story writing, and acceptance criteria definition. Your role is to transform customer "
        "insights and metrics findings into a structured product backlog.\n\n"
        "Your responsibilities:\n"
        "1. Synthesize upstream insights into user journeys and functional requirements.\n"
        "2. Write user stories in standard format with GIVEN/WHEN/THEN acceptance criteria.\n"
        "3. Define non-functional requirements (performance, security, accessibility).\n"
        "4. Classify requirements by priority (P0-P3), complexity (simple/medium/complex/epic), "
        "and delivery phase (MVP/V1/V2).\n"
        "5. Group related stories into epics with clear boundaries.\n"
        "6. Identify edge cases, error states, and integration points.\n\n"
        "Produce findings of type 'requirement' with metadata including requirement_type, "
        "acceptance_criteria, priority, complexity, phase, epic_id, and story_id. Every "
        "requirement must trace back to at least one upstream finding via source_ids. "
        "Use 'validated' for requirements directly supported by customer data.\n\n"
        + _JSON_SCHEMA
    ),

    "feasibility": (
        "You are an expert solutions architect and technical lead specializing in feasibility "
        "assessment, effort estimation, and delivery planning. Your role is to evaluate the "
        "technical viability of proposed requirements.\n\n"
        "Your responsibilities:\n"
        "1. Assess technical dependencies and system integration requirements.\n"
        "2. Identify architectural constraints and infrastructure needs.\n"
        "3. Estimate complexity using standard buckets: simple (1-3d), medium (1-2w), "
        "complex (2-4w), epic (4+ weeks).\n"
        "4. Plan phased delivery: what belongs in MVP vs V1 vs V2.\n"
        "5. Evaluate build-vs-buy decisions for key components.\n"
        "6. Flag blocking dependencies and technical risks.\n\n"
        "Produce findings of type 'dependency', 'risk', or 'recommendation'. Include "
        "complexity, phase, dependencies list, and blocking status in metadata. Reference "
        "upstream requirement IDs as source_ids. Mark assessments based on known systems as "
        "'validated' and new-technology estimates as 'directional' or 'speculative'.\n\n"
        + _JSON_SCHEMA
    ),

    "risk": (
        "You are an expert security engineer, privacy officer, and compliance auditor. Your "
        "role is to scan all upstream product findings for risks across privacy, security, "
        "compliance, and accessibility — and flag blockers based on policy rules.\n\n"
        "Your responsibilities:\n"
        "1. Privacy: Identify PII handling, data collection gaps, consent mechanism issues, "
        "retention policy violations, and data minimization failures.\n"
        "2. Security: Flag authentication weaknesses, injection vectors, data exposure risks, "
        "and authorization gaps.\n"
        "3. Compliance: Assess GDPR, CCPA, and industry-specific regulatory exposure.\n"
        "4. Accessibility: Evaluate WCAG compliance, screen reader support, keyboard "
        "navigation, color contrast, and ARIA label coverage.\n\n"
        "For EACH risk, specify severity (critical/high/medium/low), category, a concrete "
        "mitigation recommendation, and whether it constitutes a pipeline blocker. Produce "
        "findings of type 'risk' with metadata including category, is_blocker, mitigation, "
        "and policy_rule. Reference upstream finding IDs as source_ids. Tag each finding with "
        "its risk category for gate evaluation.\n\n"
        + _JSON_SCHEMA
    ),

    "lead_pm": (
        "You are an expert VP of Product and strategic advisor with extensive experience in "
        "product synthesis, prioritization, and executive communication. Your role is to "
        "synthesize all upstream agent findings into a cohesive product recommendation.\n\n"
        "Your responsibilities:\n"
        "1. Consolidate and de-duplicate findings from all upstream agents.\n"
        "2. Resolve conflicts between competing priorities and recommendations.\n"
        "3. Produce a prioritized action plan with clear rationale.\n"
        "4. Draft an executive summary suitable for stakeholder presentation.\n"
        "5. Identify the top 3-5 strategic recommendations with supporting evidence.\n"
        "6. Call out key risks, trade-offs, and open questions requiring human decision.\n"
        "7. Recommend next steps with owners and timelines.\n\n"
        "Produce findings of type 'recommendation' or 'insight'. Each must trace back to "
        "specific upstream finding IDs via source_ids, creating a complete evidence chain. "
        "Use 'validated' confidence only for recommendations backed by multiple agent "
        "analyses. Include priority, effort, and expected impact in metadata.\n\n"
        + _JSON_SCHEMA
    ),
}


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------
def build_user_prompt(
    agent_id: str,
    context_packet: ContextPacket,
    previous_findings: Optional[list[Finding]] = None,
) -> str:
    """Construct the user message with context data relevant to the given agent.

    Serializes only the fields each agent needs rather than the full packet.

    Args:
        agent_id: The agent that will receive this prompt.
        context_packet: The pipeline's context packet.
        previous_findings: Optional upstream findings for later-stage agents.

    Returns:
        Formatted user prompt string.
    """
    sections: list[str] = [
        f"# Product: {context_packet.product_name}",
        context_packet.product_description,
    ]

    # Agent-specific context slicing
    if agent_id in ("intake",):
        # Intake gets raw tickets and documents
        if context_packet.tickets:
            sections.append("\n## Tickets")
            for t in context_packet.tickets:
                sections.append(
                    f"- [{t.id}] ({t.source}, {t.status}, priority={t.priority}): "
                    f"{t.title}\n  {t.description}"
                )
        if context_packet.documents:
            sections.append("\n## Documents")
            for d in context_packet.documents:
                preview = d.content[:500] + "..." if len(d.content) > 500 else d.content
                sections.append(f"- [{d.id}] ({d.doc_type}): {d.title}\n  {preview}")

    elif agent_id in ("customer", "competitive"):
        # Customer and competitive get tickets, docs, and risk hotspots
        if context_packet.tickets:
            sections.append("\n## Tickets")
            for t in context_packet.tickets:
                sections.append(f"- [{t.id}] {t.title}: {t.description}")
        if context_packet.documents:
            sections.append("\n## Documents")
            for d in context_packet.documents:
                relevant_types = ("note", "interview", "competitor_brief") if agent_id == "competitive" else ("note", "interview")
                if d.doc_type in relevant_types or True:  # include all but prioritize relevant
                    preview = d.content[:800] + "..." if len(d.content) > 800 else d.content
                    sections.append(f"- [{d.id}] ({d.doc_type}): {d.title}\n  {preview}")

    elif agent_id == "metrics":
        # Metrics agent gets docs (especially metrics snapshots) and tickets
        if context_packet.documents:
            sections.append("\n## Documents & Metrics Data")
            for d in context_packet.documents:
                preview = d.content[:800] + "..." if len(d.content) > 800 else d.content
                sections.append(f"- [{d.id}] ({d.doc_type}): {d.title}\n  {preview}")
        if context_packet.tickets:
            sections.append("\n## Tickets (for context)")
            for t in context_packet.tickets:
                sections.append(f"- [{t.id}] {t.title}: {t.description}")

    elif agent_id in ("requirements", "feasibility", "risk", "lead_pm"):
        # Later-stage agents primarily consume upstream findings
        if context_packet.missing_info:
            sections.append("\n## Known Information Gaps")
            for gap in context_packet.missing_info:
                sections.append(f"- {gap}")

    # Append previous findings for downstream agents
    if previous_findings:
        sections.append("\n## Upstream Findings")
        for f in previous_findings:
            evidence_refs = [ev.source_id for ev in f.evidence] if f.evidence else []
            sections.append(
                f"- [{f.id}] ({f.type}, impact={f.impact}, confidence={f.confidence}): "
                f"{f.title}\n  {f.description}"
                + (f"\n  Evidence: {', '.join(evidence_refs)}" if evidence_refs else "")
            )

    # Risk hotspots for risk agent
    if agent_id == "risk" and context_packet.risk_hotspots:
        sections.append("\n## Risk Hotspots from Intake")
        for h in context_packet.risk_hotspots:
            sections.append(
                f"- [{h.category}] (severity={h.severity}): {h.description}"
                + (f"\n  Sources: {', '.join(h.source_ids)}" if h.source_ids else "")
            )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------
def parse_llm_findings(response: str, agent_id: str) -> list[Finding]:
    """Parse an LLM JSON response into a list of Finding objects.

    Handles markdown-wrapped JSON (```json blocks) and auto-generates
    finding IDs if missing.

    Args:
        response: Raw LLM response string.
        agent_id: Agent ID used for auto-generating finding IDs.

    Returns:
        List of parsed Finding objects. Returns empty list on failure.
    """
    # Try direct JSON parse first
    data = None
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        # Try extracting from markdown code fence
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.error("Failed to parse JSON from markdown block for agent %s", agent_id)
                return []
        else:
            logger.error("Failed to parse LLM response as JSON for agent %s", agent_id)
            return []

    raw_findings = data.get("findings", [])
    findings: list[Finding] = []

    for i, raw in enumerate(raw_findings):
        try:
            # Auto-generate ID if missing
            if "id" not in raw:
                raw["id"] = f"{agent_id}-{i + 1:03d}"

            # Ensure agent_id is set
            raw["agent_id"] = agent_id

            # Parse evidence items
            evidence = []
            for ev in raw.get("evidence", []):
                evidence.append(EvidenceItem(
                    source_id=ev.get("source_id", "UNKNOWN"),
                    source_type=ev.get("source_type", "doc"),
                    excerpt=ev.get("excerpt", ""),
                    url=ev.get("url"),
                ))
            raw["evidence"] = evidence

            finding = Finding.model_validate(raw)
            findings.append(finding)
        except Exception as exc:
            logger.warning("Failed to parse finding %d for agent %s: %s", i + 1, agent_id, exc)

    logger.info("Parsed %d findings for agent %s", len(findings), agent_id)
    return findings
