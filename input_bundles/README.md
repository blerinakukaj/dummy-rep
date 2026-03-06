# Input Bundles

Each input bundle is a directory containing product data for the AIPM pipeline to analyze. The system ships with 10 scenario bundles that exercise different pipeline behaviors.

## Bundle Structure

```
my_bundle/
├── manifest.json          # Required: product name, description
├── tickets.json           # Optional: array of ticket/work items
└── documents/             # Optional: supporting documents
    ├── customer_notes.md
    ├── competitor_brief.md
    ├── metrics_snapshot.json
    └── ...
```

## manifest.json Format

```json
{
    "product_name": "Your Product Name",
    "description": "Brief description of the product or feature request",
    "input_type": "bundle"
}
```

## tickets.json Format

```json
[
    {
        "id": "TICKET-001",
        "title": "Feature request title",
        "description": "Detailed description",
        "status": "open",
        "priority": "high",
        "labels": ["feature", "ux"],
        "created_at": "2025-01-15",
        "source": "jira"
    }
]
```

## Supported Document Types

| File | Purpose |
|------|---------|
| `customer_notes.md` | Interview transcripts, NPS feedback, support tickets |
| `competitor_brief.md` | Competitive analysis, feature comparisons |
| `metrics_snapshot.json` | Current product metrics (DAU, conversion, latency, etc.) |
| `stakeholder_requests.md` | Internal stakeholder requirements and priorities |
| `tech_assessment.md` | Engineering feasibility notes, dependency analysis |
| `legal_memo.md` | Legal/compliance considerations |
| `incident_report.md` | Post-incident reports for regression scenarios |

## Included Bundles

| Bundle | Scenario | Key Documents |
|--------|----------|---------------|
| `sample_bundle/` | Notification prioritization using ML | customer_notes, metrics_snapshot, competitor_brief |
| `privacy_risk/` | ML behaviour profiling with PII exposure | customer_notes, metrics_snapshot, competitor_brief, legal_memo |
| `metric_drop/` | 15% search relevance drop post-deploy | customer_notes, metrics_snapshot, incident_report |
| `competitive_parity/` | Matching competitor real-time co-editing | customer_notes, metrics_snapshot, competitor_brief, tech_assessment |
| `conflicting_stakeholders/` | Conversion vs stability tradeoff | customer_notes, metrics_snapshot, competitor_brief, stakeholder_requests |
| `a11y_gap/` | Accessibility gap from UI redesign | customer_notes, metrics_snapshot, competitor_brief |
| `enterprise_complexity/` | Enterprise request with custom workflows | customer_notes, metrics_snapshot, competitor_brief |
| `perf_regression/` | Performance regression (latency + UX) | customer_notes, metrics_snapshot, incident_report |
| `pricing_change/` | Pricing/packaging change proposal | customer_notes, metrics_snapshot, competitor_brief |
| `tech_dependency/` | Blocked by platform team dependency | customer_notes, metrics_snapshot, tech_assessment |

## Creating Your Own Bundle

1. Create a new directory under `input_bundles/`
2. Add a `manifest.json` with `product_name` and `description`
3. Optionally add `tickets.json` with work items
4. Add relevant documents under `documents/`
5. Run the pipeline:

```bash
aipm run input_bundles/my_bundle/
```

The Intake agent will normalize whatever data you provide, flag missing information, and build a context packet for downstream agents.
