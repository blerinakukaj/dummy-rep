# AIPM — Autonomous AI Product Manager

A multi-agent system that automates product management workflows using LLMs. AIPM takes a product request (prompt or bundle of tickets, docs, and metrics) and produces structured PM artifacts: PRD, roadmap, experiment plan, decision log, and backlog.

## Architecture

```
Input Bundle ──► Agent A (Intake) ──► ┌─ Agent B (Customer)    ─┐
                                      ├─ Agent C (Competitive)  ├──► ┌─ Agent E (Requirements) ─┐
                                      └─ Agent D (Metrics)      ┘    └─ Agent F (Feasibility)   ┘
                                                                              │
                                                                     Agent G (Risk/Compliance)
                                                                              │
                                                                     Agent H (Lead PM)
                                                                              │
                                                              ┌───────────────┼───────────────┐
                                                          prd.md     roadmap.json     backlog.csv
                                                      experiment_plan.md   decision_log.md
```

## Quick Start

### Prerequisites
- Python 3.12+
- An OpenAI API key and/or Anthropic API key

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd aipm

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate    # Linux/Mac
.venv\Scripts\activate       # Windows

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env and add your API key(s)
```

### Usage

```bash
# Run from an input bundle
aipm run input_bundles/sample_bundle/

# Run from a text prompt
aipm prompt "Build a notification prioritization system using ML"

# Run with a specific provider
aipm run input_bundles/sample_bundle/ --provider anthropic --model claude-sonnet-4-20250514

# Validate a previous run's outputs
aipm validate output/<run-id>/

# Start the API server
uvicorn aipm.api:app --reload --port 8000
```

## Output Artifacts

| Artifact | Format | Description |
|----------|--------|-------------|
| `prd.md` | Markdown | Structured PRD with goals, scope, requirements, acceptance criteria, rollout |
| `roadmap.json` | JSON | Themes, milestones, sequencing, dependencies |
| `experiment_plan.md` | Markdown | Hypotheses, success metrics, guardrails, A/B design |
| `decision_log.md` | Markdown | Tradeoffs, assumptions, open questions |
| `backlog.csv` | CSV | Epics/stories with acceptance criteria, priority, complexity |
| `final_plan.json` | JSON | Master consolidated output with recommendation |

## Running Tests

```bash
pytest tests/ -v
```

---

## Docker Setup

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) 24+
- [Docker Compose](https://docs.docker.com/compose/) v2

### 1. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your API key(s)
```

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key (for GPT-4o) | If using OpenAI provider |
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude) | If using Anthropic provider |

### 2. Build and start the API server

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.
Docker Compose polls `GET /api/v1/health` every 30 s to verify the container is healthy.

### 3. Run the CLI inside the container

```bash
# Run pipeline from a bundle directory
docker run --rm \
  --env-file .env \
  -v "$(pwd)/input_bundles:/app/input_bundles" \
  -v "$(pwd)/output:/app/output" \
  aipm-api aipm run /app/input_bundles/sample_bundle/

# Run pipeline from a text prompt
docker run --rm \
  --env-file .env \
  -v "$(pwd)/output:/app/output" \
  aipm-api aipm prompt "Build a smart notification prioritisation system"

# Run with Anthropic instead of OpenAI
docker run --rm \
  --env-file .env \
  -v "$(pwd)/input_bundles:/app/input_bundles" \
  -v "$(pwd)/output:/app/output" \
  aipm-api aipm run /app/input_bundles/sample_bundle/ \
    --provider anthropic --model claude-sonnet-4-20250514
```

---

## CLI Usage

```bash
# Run from a bundle directory
aipm run input_bundles/sample_bundle/

# Run from a text prompt
aipm prompt "Build a notification prioritisation system using ML"

# Select provider and model explicitly
aipm run input_bundles/sample_bundle/ --provider anthropic --model claude-sonnet-4-20250514

# Custom output directory
aipm run input_bundles/sample_bundle/ --output-dir /tmp/my_run

# Custom risk policy
aipm run input_bundles/sample_bundle/ --policy src/aipm/policies/strict_policy.yaml

# Validate a completed run's outputs
aipm validate output/<run-id>/

# Verbose / debug logging
aipm run input_bundles/sample_bundle/ --verbose
```

---

## API Usage

Start the server locally:

```bash
uvicorn aipm.api:app --reload --port 8000
# or via Docker Compose:
docker compose up
```

### Health check

```bash
curl http://localhost:8000/api/v1/health
```

```json
{"status": "ok", "version": "1.0.0"}
```

### Submit a pipeline run

```bash
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "input_bundles/sample_bundle/",
    "provider": "openai",
    "model": "gpt-4o"
  }'
```

```json
{"run_id": "run-20241201-abc123", "status": "running", "message": "Pipeline started"}
```

### Poll run status

```bash
curl http://localhost:8000/api/v1/run/run-20241201-abc123/status
```

### Retrieve generated artifacts

```bash
# List artifact paths
curl http://localhost:8000/api/v1/run/run-20241201-abc123/artifacts

# Download a specific artifact (e.g. PRD)
curl http://localhost:8000/api/v1/run/run-20241201-abc123/artifacts/prd

# Full run manifest (token usage, timings, agent results)
curl http://localhost:8000/api/v1/run/run-20241201-abc123/manifest
```

---

## Team

| Intern | Role |
|--------|------|
| Intern 1 | Platform + Orchestration |
| Intern 2 | Requirements + Metrics |
| Intern 3 | Synthesis + Risk + Lead PM |
