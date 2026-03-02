# Input Bundles

Each input bundle is a directory containing product data for AIPM to analyze.

## Bundle Structure

```
my_bundle/
├── manifest.json          # Required: product name, description, input type
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

- **customer_notes.md** — Interview transcripts, NPS feedback, support tickets
- **competitor_brief.md** — Competitive analysis, feature comparisons
- **metrics_snapshot.json** — Current product metrics (DAU, conversion, etc.)
- **stakeholder_requests.md** — Internal stakeholder requirements
- **tech_assessment.md** — Engineering feasibility notes
- **legal_memo.md** — Legal/compliance considerations
