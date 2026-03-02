# Legal Memo — PersonaLens Privacy & Compliance Review

**From:** Legal & Compliance Team
**To:** Product Team
**Date:** 2026-01-22
**Subject:** Critical concerns regarding PersonaLens User Profiling system
**Priority:** URGENT

---

## Summary

The Legal team has reviewed the proposed PersonaLens feature set and identified **multiple critical compliance risks** that must be resolved before any development proceeds beyond prototyping. We strongly recommend pausing feature development until a Data Protection Impact Assessment (DPIA) is completed and reviewed by our external privacy counsel.

## Critical Concerns

### 1. Lawful Basis for Processing (GDPR Article 6)
The proposed behavioral tracking pipeline collects browsing history, click patterns, and time-on-page data tied to authenticated user accounts. This constitutes **processing of personal data** under GDPR. The current product spec does not identify a lawful basis for this processing.

- **Consent (Art. 6(1)(a)):** If we rely on consent, it must be freely given, specific, informed, and unambiguous. Our current consent banner is a single "Accept All" / "Reject All" toggle — this does NOT meet the granularity requirement for profiling consent under Article 22.
- **Legitimate Interest (Art. 6(1)(f)):** We could potentially argue legitimate interest for basic personalization, but this requires a documented Legitimate Interest Assessment (LIA). Cross-device tracking and data sharing with advertisers almost certainly cannot be justified under legitimate interest.

### 2. Cross-Device Tracking Risks
The proposed probabilistic matching (device fingerprinting + IP correlation) is classified as **covert tracking** by multiple DPAs. The French CNIL and Austrian DSB have both ruled that device fingerprinting requires explicit consent, not just a general privacy policy mention. Deterministic matching (logged-in user_id) is less problematic but still requires clear disclosure.

### 3. Data Export to Advertisers
Sharing user profile data with third-party advertising partners — even in "anonymized" form — creates significant legal exposure:
- **Re-identification risk:** Academic research has shown that cohort-based segments can enable re-identification when 3+ segments intersect. Our proposed cohort export does not include differential privacy protections.
- **Joint controller obligations:** Under GDPR Article 26, sharing personal data (or re-identifiable data) with partners may create joint controller arrangements requiring formal agreements.
- **User consent for third-party sharing:** 61% of surveyed users said they would NOT consent to ad partner data sharing. Proceeding without clear opt-in consent risks regulatory action and user trust erosion.

### 4. Right to Erasure (GDPR Article 17)
The ML recommendation engine is trained on user behavioral data. If a user requests data deletion:
- Raw event data can be purged from the data lake — **but the trained model retains learned patterns from that data.**
- We need a clear policy on whether model retraining is required after deletion requests, or whether learned model weights are considered "anonymized."
- DataPulse was specifically cited for this exact issue in their CNIL fine.

### 5. Data Retention
No data retention policy has been defined for the behavioral tracking pipeline. Storing raw behavioral events indefinitely is a GDPR violation. We need:
- Defined retention periods per data category
- Automatic purging mechanisms
- Justification for any retention beyond 12 months

### 6. DPIA Requirement
Under GDPR Article 35, a Data Protection Impact Assessment is **mandatory** for:
- Systematic and extensive profiling with significant effects on individuals ✓
- Processing of personal data on a large scale ✓
- Innovative use of new technologies (ML-based profiling) ✓

**A DPIA has not been initiated.** This must be completed before processing begins.

## Recommendations

1. **HALT** development of PROF-104 (cross-device tracking) and PROF-105 (advertiser data export) until legal review is complete
2. **INITIATE** a DPIA immediately — estimated 4-6 weeks with external counsel
3. **REDESIGN** consent mechanisms to provide granular, per-feature opt-in
4. **DEFINE** data retention policies before any pipeline goes live
5. **EVALUATE** privacy-enhancing technologies (differential privacy, on-device processing) as alternatives to server-side profiling
6. **ENGAGE** external privacy counsel for a formal compliance audit

## Risk Assessment

| Risk | Severity | Likelihood | Impact |
|------|----------|------------|--------|
| GDPR fine (Art. 83) | Critical | High | Up to €20M or 4% annual revenue |
| User trust erosion | High | High | Churn increase, NPS decline |
| Regulatory investigation | High | Medium | 6-12 month operational disruption |
| Class action lawsuit | Medium | Medium | Legal costs + settlement |
| Market reputation damage | High | Medium | Competitive disadvantage |

**Bottom line:** The PersonaLens feature has strong business potential, but launching without addressing these compliance gaps would expose the company to **material regulatory and legal risk**. We recommend a "validate first" approach — complete the DPIA, redesign consent flows, and consider privacy-preserving alternatives before committing engineering resources to the full feature set.
