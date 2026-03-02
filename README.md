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

## Team

| Intern | Role |
|--------|------|
| Intern 1 | Platform + Orchestration |
| Intern 2 | Requirements + Metrics |
| Intern 3 | Synthesis + Risk + Lead PM |
