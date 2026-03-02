# Incident Report — SearchBoost v2.4.1 Deployment
**Severity:** P1
**Status:** Ongoing / Mitigated
**Incident ID:** INC-2025-1028
**Date of Deploy:** 2025-10-28 14:32 UTC
**Incident Declared:** 2025-10-29 09:15 UTC
**Authored by:** Engineering On-Call Team

---

## Executive Summary

The v2.4.1 release introduced a new ML-based ranking algorithm intended to improve search personalization for signed-in users. The release also launched two new search surfaces: image search and voice search. Within 18 hours of full traffic ramp-up, search relevance scores dropped 15% at p50. The incident disproportionately affected anonymous users (~40% of query volume), a segment that was insufficiently represented in pre-launch A/B testing.

Rollback was blocked because v2.4.1 included a feature flag dependency for the new onboarding flow that was already in use for a concurrent marketing campaign. A partial remediation (model config override) was applied on day 3, stabilizing relevance at -15% rather than allowing continued degradation. Full remediation requires a targeted model patch or re-segment A/B test.

---

## Timeline

| Time (UTC)         | Event |
|--------------------|-------|
| 2025-10-28 14:32   | v2.4.1 deployed to 10% of traffic (canary) |
| 2025-10-28 16:00   | Canary metrics nominal; ramp to 50% traffic |
| 2025-10-28 22:00   | Full 100% traffic ramp completed |
| 2025-10-29 07:00   | Automated relevance monitor detects -8% drop; alert fired |
| 2025-10-29 09:15   | On-call acknowledges; P1 incident declared |
| 2025-10-29 11:30   | Root cause identified: anonymous user ranking path not covered by A/B test |
| 2025-10-29 14:00   | Rollback evaluated; blocked by onboarding feature flag dependency |
| 2025-10-29 18:45   | Model config override applied; degradation stabilized |
| 2025-10-30 09:00   | Support ticket spike confirmed (3x baseline) |
| 2025-10-31 15:00   | Autocomplete cache TTL misconfiguration identified (7d instead of 24h) |
| 2025-10-31 17:30   | Cache TTL corrected; autocomplete fix will propagate within 7 days |
| 2025-11-01 10:00   | Instrumentation gap confirmed: 3 event types missing from new search surfaces |
| 2025-11-04 08:00   | Incident ongoing; remediation plan in progress |

---

## Root Cause Analysis

### Primary: Anonymous User Segment Not Represented in A/B Test

The A/B test (EXP-881) for the new ranking algorithm measured relevance improvement for signed-in users only. The power analysis assumed anonymous traffic was ~35% of queries. Post-launch data shows it is actually ~40%. The algorithm performs significantly worse for anonymous users because it relies on historical session data unavailable for non-authenticated requests. The new ranking model falls back to a less-calibrated generic model for anonymous users, which explains the navigational query degradation.

### Secondary: Autocomplete Cache TTL Misconfiguration

During the v2.4.1 deployment pipeline, an environment variable for `AUTOCOMPLETE_CACHE_TTL` was overwritten from `86400` (24 hours) to `604800` (7 days). This was caused by a misconfigured secrets merge step that pulled stale values from a staging environment configuration. Result: autocomplete suggestions are stale by up to 7 days, surfacing expired promotions and out-of-stock products.

### Contributing: Missing Instrumentation for New Query Types

The v2.4.1 release added image search and voice search without corresponding analytics event instrumentation. Events `image_search_query`, `voice_search_query`, and `filter_applied` were not added to the event schema. This means the team has zero observability into these new surfaces and cannot quantify their contribution to the overall relevance drop or user experience degradation.

---

## Impact

- **Search relevance p50:** -15.3% (0.85 → 0.72)
- **Mobile search latency p95:** +112% (420ms → 890ms)
- **Zero-result rate:** +200% (0.06 → 0.18)
- **Search CTR:** -34% (0.47 → 0.31)
- **Session abandonment post-search:** +57% (0.28 → 0.44)
- **Support ticket volume:** +200% (41 → 123 in 7 days)
- **NPS (search sessions):** -14 points (42 → 28)
- **Enterprise accounts flagging churn risk:** 8

---

## Immediate Actions Taken

1. Model config override applied to stabilize relevance degradation
2. Autocomplete cache TTL corrected to 24 hours (propagation in progress)
3. Rollback deprioritized due to onboarding feature flag dependency; scheduled for next sprint

---

## Open Remediation Items

1. **Re-run A/B test** scoped to anonymous users with properly powered sample size
2. **Patch ranking model** for anonymous user fallback path
3. **Add instrumentation** for `image_search_query`, `voice_search_query`, `filter_applied`
4. **Establish baseline metrics** for image search and voice search
5. **Fix deployment pipeline** to prevent staging config bleed into production
6. **Improve canary metrics** to include anonymous-user-specific relevance scores
7. **Mobile latency investigation**: profile ranking re-ranker for mobile session path

---

## Lessons Learned

- A/B tests must be powered for all major traffic segments independently, not just the majority
- New feature surfaces require instrumentation sign-off as a deploy gate
- Cache configuration changes should be validated as a separate deployment artifact
- Canary phase should run for minimum 48 hours to capture diurnal and authenticated/anonymous traffic patterns
