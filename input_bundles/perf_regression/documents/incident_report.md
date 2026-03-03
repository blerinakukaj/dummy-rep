# Incident Report — PageSpeed v3.2 Performance Regression

## Incident Timeline
- **2025-10-05 09:15 UTC**: v3.2 deployed to production (includes charting library migration + PostgreSQL 16 upgrade)
- **2025-10-05 09:45 UTC**: First customer report of slow dashboard loads
- **2025-10-05 10:30 UTC**: Monitoring confirms p95 dashboard load time at 4.2s (baseline: 1.2s)
- **2025-10-05 11:00 UTC**: API latency alerts fire — p95 at 350ms (baseline: 120ms)
- **2025-10-05 14:00 UTC**: WebSocket server first OOM crash observed
- **2025-10-05 16:00 UTC**: Incident declared SEV-1, war room opened
- **2025-10-06 02:00 UTC**: Root causes identified (charting SVG rendering + PG query planner + memory leak)
- **2025-10-06 10:00 UTC**: Partial mitigation deployed (increased WebSocket server memory to 8GB, added restart cron)
- **2025-10-08 present**: Full fixes still in progress

## Root Causes
1. **Charting Library SVG Regression**: New library renders each data point as individual SVG elements instead of using canvas batching. Dashboards with 10+ series generate 50K+ DOM nodes.
2. **PostgreSQL 16 Query Planner**: New planner cost model chooses nested loop joins for our partitioned time-series tables instead of hash joins. Requires explicit query hints or planner configuration.
3. **WebSocket Memory Leak**: Event listeners in the metric aggregation pipeline are not cleaned up when data windows roll forward, causing cumulative allocation.

## Impact
- 89 support tickets in 7 days (baseline: 12)
- NPS dropped from 52 to 18
- 3 enterprise customers escalated to executive team
- Estimated revenue risk: $180K ARR from at-risk accounts
