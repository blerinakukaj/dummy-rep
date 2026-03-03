# Autonomous AI Product Manager (AIPM)

A multi-agent system that automates product management workflows using LLMs. AIPM takes a product request (a text prompt or a bundle of tickets, documents, and metrics) and produces structured PM artifacts: PRD, roadmap, experiment plan, decision log, and backlog.

## Architecture

```
Input Bundle ──► Intake Agent ──► ┌─ Customer Insights Agent ─┐
                                  ├─ Competitive Agent        ├──► ┌─ Requirements Agent ─┐
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
1. **Intake** — normalizes input data and builds a `ContextPacket`
2. **Parallel analysis** — Customer, Competitive, and Metrics agents run concurrently, followed by Requirements and Feasibility in parallel
3. **Risk gate** — Risk agent scans all findings against policy rules
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

# Start the API server
uvicorn aipm.api:app --reload --port 8000
```

## Agents

| # | Agent | Purpose | Key Inputs | Key Outputs |
|---|-------|---------|------------|-------------|
| 1 | **Intake** | Normalizes input, deduplicates tickets, detects gaps, tags risk hotspots | Raw bundle (tickets, docs, metrics) | `ContextPacket` consumed by all downstream agents |
| 2 | **Customer Insights** | Segments users, frames jobs-to-be-done, identifies research gaps | Customer notes, interviews, NPS data, tickets | Insights (user needs, JTBD), gaps, validation plans |
| 3 | **Competitive** | Builds feature parity matrix, identifies differentiation opportunities | Competitor briefs, market analysis | Competitor analysis, parity gaps, positioning pillars |
| 4 | **Metrics** | Defines North Star, input/guardrail metrics, proposes event taxonomy | Metrics snapshots, KPI docs | Metric definitions, instrumentation gaps, event taxonomy |
| 5 | **Requirements** | Converts insights into user journeys, stories with acceptance criteria | Upstream findings from agents 2-4 | Functional/non-functional requirements, epics, stories (P0-P3, MVP/V1/V2) |
| 6 | **Feasibility** | Assesses dependencies, complexity, build-vs-buy, phased delivery | Requirements, technical docs | Dependency maps, complexity ratings, phase assignments, blocking flags |
| 7 | **Risk** | Scans for privacy, security, compliance, accessibility risks | All upstream findings + policy pack | Risk findings with severity, mitigations, blocker flags |
| 8 | **Lead PM** | Deduplicates, resolves conflicts, ranks, generates all artifacts | All agent outputs | PRD, roadmap, backlog, experiment plan, decision log, final plan |

## Output Artifacts

| Artifact | Format | Description |
|----------|--------|-------------|
| `prd.md` | Markdown | Product Requirements Document with goals, scope, requirements, acceptance criteria (GIVEN/WHEN/THEN), rollout plan |
| `roadmap.json` | JSON | Strategic themes, milestones, sequencing, dependencies, critical path, phased delivery (MVP/V1/V2) |
| `experiment_plan.md` | Markdown | Hypotheses, success metrics, guardrail metrics, A/B test design, instrumentation |
| `decision_log.md` | Markdown | Deduplication decisions, conflict resolutions, risk gate results, prioritization rationale, assumption register |
| `backlog.csv` | CSV | Epics and stories with acceptance criteria, priority (P0-P3), complexity (simple-epic), phase, dependencies |
| `final_plan.json` | JSON | Master consolidated output with recommendation (proceed / proceed_with_mitigations / validate_first / do_not_pursue) |

## Policy Configuration

Policies are YAML files in `src/aipm/policies/` that control how the pipeline evaluates risks and makes decisions.

| Policy | Description | Risk Tolerance |
|--------|-------------|----------------|
| `default_policy.yaml` | Balanced baseline — consent required, WCAG AA, blocks critical risks | Max 2 unmitigated high risks |
| `enterprise_policy.yaml` | Strict compliance — SOC 2, audit trails, 30-day retention | Zero tolerance for high risks |
| `startup_fast_policy.yaml` | Speed-to-market — relaxed gates, WCAG A, smaller sample sizes | Up to 5 unmitigated high risks |
| `strict_privacy_policy.yaml` | Privacy-first — explicit consent, legal review gates everything | Zero tolerance, no behavioral profiling |

**How policies change outcomes:** Running the same `privacy_risk` bundle with `default_policy.yaml` vs `startup_fast_policy.yaml` produces different recommendations because the startup policy has higher risk tolerance and fewer compliance gates.

To create a custom policy, copy an existing one and modify the sections:

```yaml
# my_policy.yaml
product_principles:
  - "Ship iteratively"
  - "User value over feature count"

risk_gating:
  block_on_critical_privacy: true
  block_on_critical_security: true
  require_legal_review_for_pii: false
  max_unmitigated_high_risks: 3

experimentation:
  require_guardrail_metrics: true
  min_sample_size: 500
  max_experiment_duration_days: 21
```

Then pass it to the CLI:

```bash
aipm run input_bundles/sample_bundle/ --policy my_policy.yaml
```

## Test Bundles

Five input bundles in `input_bundles/` exercise different pipeline scenarios:

| Bundle | Product | Scenario | Expected Behaviour |
|--------|---------|----------|-------------------|
| `sample_bundle/` | SmartNotify | Notification prioritization using ML | Full pipeline run with standard artifacts |
| `privacy_risk/` | PersonaLens User Profiling | ML behaviour profiling with PII exposure | Risk gate flags blockers; recommendation: `validate_first` |
| `metric_drop/` | SearchBoost Query Engine | 15% search relevance drop post-deploy | Experiment plan with instrumentation and rollback criteria |
| `competitive_parity/` | CollabDocs Real-time Editor | Matching competitor real-time co-editing | Roadmap with phased approach and competitive urgency |
| `conflicting_stakeholders/` | QuickPay Checkout Redesign | Conversion vs stability tradeoff | Conflict resolution in decision log; balanced recommendation |

Each bundle contains a `manifest.json`, optional `tickets.json`, and a `documents/` folder with customer notes, competitor briefs, metrics snapshots, and other supporting data.

## API Reference

Start the server:

```bash
uvicorn aipm.api:app --reload --port 8000
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check — returns `{"status": "healthy", "version": "1.0.0"}` |
| `POST` | `/api/v1/run` | Start a pipeline run (JSON body or zip bundle upload) |
| `GET` | `/api/v1/run/{run_id}/status` | Poll run status (`running` / `completed` / `failed`) |
| `GET` | `/api/v1/run/{run_id}/artifacts` | List generated artifacts with download links |
| `GET` | `/api/v1/run/{run_id}/artifacts/{name}` | Download a specific artifact (e.g. `prd.md`) |
| `GET` | `/api/v1/run/{run_id}/manifest` | Full run manifest (token usage, timings, agent results) |

### Start a run from a prompt

```bash
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Build a notification prioritization system using ML",
    "provider": "openai",
    "model": "gpt-4o"
  }'
```

```json
{"run_id": "abc-123", "status": "started"}
```

### Upload a zip bundle

```bash
curl -X POST http://localhost:8000/api/v1/run \
  -F "file=@my_bundle.zip"
```

### Poll status and download artifacts

```bash
curl http://localhost:8000/api/v1/run/abc-123/status
curl http://localhost:8000/api/v1/run/abc-123/artifacts
curl http://localhost:8000/api/v1/run/abc-123/artifacts/prd.md -o prd.md
```

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_pipeline.py -v

# Run with debug output
pytest tests/ -v -s
```

The test suite includes:
- **End-to-end pipeline tests** — full pipeline run with mocked LLM
- **Individual agent tests** — per-agent validation with error handling scenarios
- **Output validation tests** — quality checks on generated artifacts (PRD structure, roadmap schema, backlog CSV, decision log completeness)

## Docker

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) 24+
- [Docker Compose](https://docs.docker.com/compose/) v2

### Build and run the API server

```bash
cp .env.example .env
# Edit .env and add your API key(s)

docker compose up --build
```

The API will be available at `http://localhost:8000`. Docker Compose polls `GET /api/v1/health` every 30s to verify container health.

### Run the CLI inside Docker

```bash
# Run pipeline from a bundle
docker run --rm \
  --env-file .env \
  -v "$(pwd)/input_bundles:/app/input_bundles" \
  -v "$(pwd)/output:/app/output" \
  aipm-api aipm run /app/input_bundles/sample_bundle/

# Run from a text prompt
docker run --rm \
  --env-file .env \
  -v "$(pwd)/output:/app/output" \
  aipm-api aipm prompt "Build a smart notification prioritisation system"

# Use a different model
docker run --rm \
  --env-file .env \
  -v "$(pwd)/input_bundles:/app/input_bundles" \
  -v "$(pwd)/output:/app/output" \
  aipm-api aipm run /app/input_bundles/sample_bundle/ \
    --model gpt-4o-mini
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key (for GPT-4o) | Yes |

## Demo Scripts

Two convenience scripts in `scripts/` showcase the pipeline:

```bash
# Run all 5 demo scenarios
python scripts/demo.py

# Run a specific demo (1-5)
python scripts/demo.py --demo 1

# Run a single bundle with formatted output
python scripts/run_single.py input_bundles/sample_bundle/

# Run from a prompt
python scripts/run_single.py --prompt "An AI-powered code review tool"
```

## Team

| Intern | Role |
|--------|------|
| Intern 1 | Platform + Orchestration |
| Intern 2 | Requirements + Metrics |
| Intern 3 | Synthesis + Risk + Lead PM |
