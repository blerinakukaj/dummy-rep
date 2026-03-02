# Competitive Analysis — User Profiling & Personalization

## Competitor A: DataPulse
**Status:** Fined €8.2M by French DPA (CNIL) in Q3 2025

DataPulse operated a behavioral profiling system similar to PersonaLens. They collected browsing history, device fingerprints, and location data to build user profiles for content personalization and ad targeting. Key regulatory findings:
- **Consent mechanism was insufficient:** Pre-checked boxes and buried privacy settings did not constitute valid GDPR consent
- **Data retention was excessive:** Raw behavioral events were stored for 36 months with no automatic purging
- **Right to erasure was incomplete:** User deletion requests removed account data but left behavioral traces in ML training datasets
- **Cross-device tracking lacked lawful basis:** Probabilistic device matching (IP + browser fingerprint) was ruled as processing without consent

**Lesson:** Any profiling system that uses cross-device tracking or shares data with third parties requires explicit, granular, freely-given consent under GDPR. Retroactive consent collection is not accepted.

## Competitor B: ClearFeed
**Status:** Market leader in privacy-first personalization

ClearFeed launched a privacy-first recommendation engine in 2025 that has gained significant market share among privacy-conscious enterprises. Their approach:
- **On-device processing:** User profiles are computed locally on the user's device, never sent to servers
- **Differential privacy:** When aggregate data is needed for model training, they apply differential privacy guarantees (ε=1.0)
- **Consent tiers:** Users choose from three clear levels — "Basic" (no tracking), "Standard" (anonymous usage stats), "Full" (personalized recommendations with explicit data list)
- **Monthly transparency reports:** Users receive an automated email summarizing what data was collected and how it was used
- **No third-party data sharing:** ClearFeed explicitly does not share any user data with advertisers, and markets this as a competitive advantage

ClearFeed's NPS is 67 (vs. industry average of 34). Their enterprise adoption grew 140% YoY after DataPulse's fine.

## Competitor C: InsightGrid
**Status:** Active, facing regulatory scrutiny

InsightGrid takes a middle-ground approach:
- Server-side profiling with 90-day data retention
- Offers data export functionality (Article 20 compliance)
- Shares "anonymized" cohort data with partners — but researchers demonstrated re-identification is possible with 3+ cohort intersections
- Currently under investigation by the Irish DPC

## Feature Comparison Matrix

| Feature | DataPulse | ClearFeed | InsightGrid | PersonaLens (Proposed) |
|---------|-----------|-----------|-------------|----------------------|
| Behavioral Tracking | Server-side | On-device | Server-side | Server-side |
| Cross-device | Yes (fingerprint) | No | Yes (login only) | Yes (deterministic + probabilistic) |
| Consent Mechanism | Pre-checked | Tiered opt-in | Single toggle | TBD |
| Data Retention | 36 months | On-device only | 90 days | TBD |
| Third-party Sharing | Yes | No | Anonymized cohorts | Anonymized cohorts (proposed) |
| Transparency Dashboard | No | Yes | Partial | Proposed |
| GDPR Compliant | No (fined) | Yes | Under review | TBD |
| Differential Privacy | No | Yes (ε=1.0) | No | No |
