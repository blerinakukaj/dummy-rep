# Autonomous AI Product Manager (AIPM)

A multi-agent system that automates product management workflows using LLMs. AIPM takes a product request (a text prompt or a bundle of tickets, documents, and metrics) and produces structured PM artifacts: PRD, roadmap, experiment plan, decision log, and backlog.

## Architecture

```
Input Bundle ──> Intake Agent ──> ┌─ Customer Insights Agent ─┐
                                  ├─ Competitive Agent        ├──> ┌─ Requirements Agent ─┐
                                  └─ Metrics Agent            ┘    └─ Feasibility Agent   ┘
                                                                            │
                                                                   Risk / Compliance Agent
                                                                            │
                                                                      Lead PM Agent
                                                                            │
                                                            ┌───────────────┼───────────────┐
                                                        prd.md     roadmap.json     backlog.csv
                                                    experiment_plan.md   decision_log.md
                                                                  final_plan.json
```

The pipeline runs in four stages:
1. **Intake** — normalizes input data, deduplicates tickets, tags risk hotspots, and builds a `ContextPacket`
2. **Parallel analysis** — Customer, Competitive, and Metrics agents run concurrently, followed by Requirements and Feasibility in parallel
3. **Risk gate** — Risk agent scans all findings against YAML policy rules and produces a pass/fail gate result
4. **Synthesis** — Lead PM deduplicates, resolves conflicts, ranks findings, and generates all artifacts

## Quick Start

### Prerequisites
- Python 3.12+
- An OpenAI API key

### Setup

```bash
# Clone the repository
git clone git@github.com:blerinakukaj/dummy-rep.git
cd dummy-rep

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate    # Linux/Mac
.venv\Scripts\activate       # Windows

# Install dependencies (including dev tools)
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Usage

```bash
# Run from an input bundle
aipm run input_bundles/sample_bundle/

# Run from a text prompt
aipm prompt "Build a notification prioritization system using ML"

# Run with a specific model
aipm run input_bundles/sample_bundle/ --model gpt-4o-mini

# Custom policy
aipm run input_bundles/sample_bundle/ --policy src/aipm/policies/strict_privacy_policy.yaml

# Validate a previous run's outputs
aipm validate output/<run-id>/
```

## Agents

| # | Agent | Purpose | Key Inputs | Key Outputs |
|---|-------|---------|------------|-------------|
| A | **Intake** | Normalizes input, deduplicates tickets, detects gaps, tags risk hotspots | Raw bundle (tickets, docs, metrics) | `ContextPacket` consumed by all downstream agents |
| B | **Customer Insights** | Segments users, frames jobs-to-be-done, identifies research gaps | Customer notes, interviews, NPS data, tickets | Insights (user needs, JTBD), gaps, validation plans |
| C | **Competitive** | Builds feature parity matrix, identifies differentiation opportunities | Competitor briefs, market analysis | Competitor analysis, parity gaps, positioning pillars |
| D | **Metrics** | Defines North Star, input/guardrail metrics, proposes event taxonomy | Metrics snapshots, KPI docs | Metric definitions, instrumentation gaps, event taxonomy |
| E | **Requirements** | Converts insights into user journeys, stories with acceptance criteria | Upstream findings from agents B-D | Functional/non-functional requirements, epics, stories (P0-P3, MVP/V1/V2) |
| F | **Feasibility** | Assesses dependencies, complexity, build-vs-buy, phased delivery | Requirements, technical docs | Dependency maps, complexity ratings, phase assignments, blocking flags |
| G | **Risk** | Scans for privacy, security, compliance, accessibility risks | All upstream findings + policy pack | Risk findings with severity, mitigations, blocker flags |
| H | **Lead PM** | Deduplicates, resolves conflicts, ranks, generates all artifacts | All agent outputs | PRD, roadmap, backlog, experiment plan, decision log, final plan |

## Output Artifacts

Each pipeline run produces a timestamped output directory containing:

| Artifact | Format | Description |
|----------|--------|-------------|
| `prd.md` | Markdown | Product Requirements Document with goals, scope, requirements, acceptance criteria (GIVEN/WHEN/THEN), rollout plan |
| `roadmap.json` | JSON | Strategic themes, milestones, sequencing, dependencies, critical path, phased delivery (MVP/V1/V2) |
| `experiment_plan.md` | Markdown | Hypotheses, success metrics, guardrail metrics, A/B test design, sample sizing, rollback criteria |
| `decision_log.md` | Markdown | Deduplication decisions, conflict resolutions, risk gate results, prioritization rationale, assumption register |
| `backlog.csv` | CSV | Epics and stories with acceptance criteria, priority (P0-P3), complexity (simple/medium/complex/epic), phase, dependencies |
| `final_plan.json` | JSON | Master consolidated output with recommendation: `proceed` / `proceed_with_mitigations` / `validate_first` / `do_not_pursue` |

Supporting files per run:
- `context_packet.json` — normalized input data consumed by all agents
- `findings/*.json` — per-agent structured findings (intake, customer, competitive, metrics, requirements, feasibility, risk, lead_pm)
- `findings/risk_gate_result.json` — pass/fail gate with blockers and warnings
- `run_manifest.json` — full run metadata (agent status, timing, token usage, artifact paths)
- `token_usage.json` — per-agent token breakdown with cost estimate

## Findings Schema

Every agent produces structured findings using a shared schema:

```json
{
  "id": "risk-001",
  "agent_id": "risk",
  "type": "risk",
  "title": "Privacy Risk Hotspot Detected",
  "description": "Detected privacy risk keywords...",
  "impact": "critical",
  "confidence": "validated",
  "assumptions": ["Privacy risks may arise from inadequate PII handling"],
  "evidence": [
    {
      "source_id": "DOC-002",
      "source_type": "doc",
      "excerpt": "Detected privacy risk keywords in 1 source(s)"
    }
  ],
  "recommendations": ["Review PII handling practices"],
  "tags": ["privacy"],
  "metadata": {"category": "privacy", "is_blocker": true}
}
```

- **type**: `insight` | `risk` | `requirement` | `metric` | `gap` | `recommendation` | `dependency`
- **impact**: `critical` | `high` | `medium` | `low`
- **confidence**: `validated` | `directional` | `speculative`

## Policy Configuration

Policies are YAML files in `src/aipm/policies/` that control how the pipeline evaluates risks and makes decisions.

| Policy | Description | Risk Tolerance |
|--------|-------------|----------------|
| `default_policy.yaml` | Balanced baseline — consent required, WCAG AA, blocks critical risks | Max 2 unmitigated high risks |
| `startup_fast_policy.yaml` | Speed-to-market — relaxed gates, WCAG A, smaller sample sizes | Up to 5 unmitigated high risks |
| `enterprise_policy.yaml` | Strict compliance — SOC 2, audit trails, 30-day retention | Zero tolerance for high risks |
| `strict_privacy_policy.yaml` | Privacy-first — explicit consent, legal review gates everything | Zero tolerance, no behavioral profiling |

**How policies change outcomes:** Running the same input bundle with `default_policy.yaml` vs `startup_fast_policy.yaml` produces different recommendations because the startup policy has a higher `max_unmitigated_high_risks` threshold and fewer compliance gates. This is demonstrated in Demo 11 where the same `privacy_risk` bundle yields `do_not_pursue` under the default policy but `validate_first` under the startup policy.

Policy sections:

```yaml
product_principles:
  - "Ship iteratively"
  - "User value over feature count"

data_handling:
  require_collection_justification: true
  require_consent_mechanism: true
  retention_limit_days: 90
  minimize_pii: true

experimentation:
  require_guardrail_metrics: true
  min_sample_size: 1000
  max_experiment_duration_days: 30

accessibility:
  wcag_level: "AA"
  require_screen_reader_support: true
  require_keyboard_navigation: true

risk_gating:
  block_on_critical_privacy: true
  block_on_critical_security: true
  require_legal_review_for_pii: true
  max_unmitigated_high_risks: 2
```

To use a custom policy:

```bash
aipm run input_bundles/sample_bundle/ --policy my_policy.yaml
```

## Test Bundles

Ten input bundles in `input_bundles/` exercise different pipeline scenarios:

| Bundle | Product | Scenario | Expected Behaviour |
|--------|---------|----------|-------------------|
| `sample_bundle/` | SmartNotify | Notification prioritization using ML | Full pipeline run with standard artifacts |
| `privacy_risk/` | PersonaLens User Profiling | ML behaviour profiling with PII exposure | Risk gate flags blockers; `do_not_pursue` under default policy |
| `metric_drop/` | SearchBoost Query Engine | 15% search relevance drop post-deploy | Experiment plan with instrumentation and rollback criteria |
| `competitive_parity/` | CollabDocs Real-time Editor | Matching competitor real-time co-editing | Roadmap with phased approach and competitive urgency |
| `conflicting_stakeholders/` | QuickPay Checkout Redesign | Conversion vs stability tradeoff | Conflict resolution in decision log; balanced recommendation |
| `a11y_gap/` | — | Accessibility gap introduced by UI redesign | Accessibility findings flagged against WCAG policy |
| `enterprise_complexity/` | — | Enterprise request with long-tail complexity | Complex dependency mapping; phased delivery plan |
| `perf_regression/` | — | Performance regression (UX complaints + latency metrics) | Performance-focused experiment plan with rollback criteria |
| `pricing_change/` | — | Pricing/packaging change proposal | Pricing risk findings; churn impact analysis |
| `tech_dependency/` | — | Tech dependency risk (blocked by platform team) | Dependency and blocking flags in feasibility findings |

Each bundle contains a `manifest.json`, optional `tickets.json`, and a `documents/` folder with customer notes, competitor briefs, metrics snapshots, and other supporting data.

## API (Optional)

An optional FastAPI endpoint is available for running the pipeline over HTTP:

```bash
uvicorn aipm.api:app --reload --port 8000
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `POST` | `/api/v1/run` | Start a pipeline run (JSON body or zip bundle) |
| `GET` | `/api/v1/run/{run_id}/status` | Poll run status |
| `GET` | `/api/v1/run/{run_id}/artifacts` | List generated artifacts |
| `GET` | `/api/v1/run/{run_id}/artifacts/{name}` | Download a specific artifact |
| `GET` | `/api/v1/run/{run_id}/manifest` | Full run manifest |

## Running Tests

```bash
# Run all 129 tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_agents.py -v

# Run with debug output
pytest tests/ -v -s
```

The test suite (129 tests across 10 files) includes:
- **Schema validation tests** — Pydantic model constraints, finding field enforcement
- **Individual agent tests** — per-agent validation with mock LLM, error handling
- **Validator tests** — duplicate detection, evidence linking, cross-agent consistency
- **Backlog generator tests** — CSV format, acceptance criteria structure
- **Output validation tests** — artifact structure, manifest completeness
- **Integration tests** — multi-agent interaction, policy enforcement
- **End-to-end pipeline tests** — full pipeline with mocked LLM, prompt mode, strict policy scenarios

## Demo Script

A comprehensive demo script in `scripts/demo.py` showcases the pipeline across 13 demo scenarios with Rich-formatted terminal output:

```bash
# Run all 13 demos sequentially
python scripts/demo.py

# Run a specific demo (1-13)
python scripts/demo.py --demo 5

# Run a single bundle with formatted output
python scripts/run_single.py input_bundles/sample_bundle/

# Run from a prompt
python scripts/run_single.py --prompt "An AI-powered code review tool"
```

Demo highlights:
- **Demos 1-10** — Each input bundle run through the full pipeline with formatted results
- **Demo 11** — Policy configurability: same bundle run with `default_policy.yaml` (strict) vs `startup_fast_policy.yaml` (relaxed), showing different recommendations
- **Demo 12** — Full showcase run with detailed artifact inspection
- **Demo 13** — Batch run across multiple bundles with comparison table

## Project Structure

```
dummy-rep/
├── src/aipm/
│   ├── agents/          # 8 specialized agents (intake through lead_pm)
│   ├── core/            # Orchestrator, generators, validators, policy, token tracking
│   ├── schemas/         # Pydantic models (Finding, ContextPacket, RunConfig)
│   ├── policies/        # 4 YAML policy files
│   ├── templates/       # Markdown/CSV templates for artifact generation
│   ├── cli.py           # Typer CLI (run, validate, prompt commands)
│   └── api.py           # Optional FastAPI endpoint
├── input_bundles/       # 10 scenario bundles
├── scripts/             # Demo runner and single-run utility
├── tests/               # 129 tests across 10 files
├── output/              # Generated pipeline outputs (per-run directories)
└── pyproject.toml       # Project config, dependencies, tool settings
```
