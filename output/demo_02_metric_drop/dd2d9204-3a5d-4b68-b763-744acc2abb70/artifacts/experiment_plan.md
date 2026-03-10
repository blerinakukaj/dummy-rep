# Experiment Plan: SearchBoost Query Engine

**Run ID:** dd2d9204-3a5d-4b68-b763-744acc2abb70
**Date:** 2026-03-06

---

## Hypothesis

If we improve the SearchBoost Query Engine's algorithm to enhance result relevance, then the Search Relevance Score will increase by 5.88% (from 0.85 to 0.9) because users will find the search results more aligned with their queries, leading to higher satisfaction and engagement. This is supported by the critical nature of the Search Relevance Score in measuring user satisfaction and engagement with search results [metrics-001].

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                          | Baseline | Target | Measurement Method          | Window                |
|---------------------------------|----------|--------|-----------------------------|-----------------------|
| Search Relevance Score          | 0.85     | 0.9    | 7-day trailing average      | 30 days               |
| Search Click-Through Rate (CTR) | 0.47     | 0.5    | 7-day trailing average      | 30 days               |

### Guardrail Metrics

| Metric                          | Current Value | Max Acceptable Degradation | Measurement Method          |
|---------------------------------|----------------|----------------------------|-----------------------------|
| Session Abandonment After Search | 0.28           | 0.25                       | 7-day trailing average      |

## Experiment Design

We will conduct a phased rollout of the improved SearchBoost Query Engine algorithm. The rollout will occur in four phases: 10% of users for 7 days, 25% for 7 days, 50% for 7 days, and finally 100%. At each phase, we will evaluate the success and guardrail metrics. If the Search Relevance Score does not reach at least 0.87 after the first phase or if Session Abandonment After Search exceeds 0.28, we will halt the rollout and reassess the changes. This design ensures that all users benefit from accessibility improvements without withholding them from any group.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 5.88% increase in Search Relevance Score with a power of 0.8 and a significance level of 0.05, we estimate a required sample size of 1000 users per phase. Given the maximum experiment duration of 30 days and a traffic volume of approximately 10,000 users per day, we can complete the phased rollout within this timeframe.

## Segmentation

Post-hoc analysis will focus on different user cohorts: users who utilize assistive technologies (screen reader users vs. sighted users) and new vs. returning users. This segmentation is crucial as it allows us to understand how different user groups experience the changes and whether the improvements are equitable across all user types.

## Rollback Criteria

The experiment will be rolled back if the Search Relevance Score does not improve to at least 0.87 after the first phase or if the Session Abandonment After Search exceeds 0.28 at any point during the rollout.

## Data Collection Plan

We will track the following events: `search_performed`, `search_result_clicked`, `session_abandoned`. Each event will capture relevant properties such as user ID, timestamp, search query, and whether assistive technology was used (detected through user agent strings). This data will enable us to measure the success and guardrail metrics accurately.

## Analysis Plan

We will use a paired t-test to compare pre- and post-rollout metrics for the Search Relevance Score and Search CTR, as these metrics are expected to follow a normal distribution. For Session Abandonment, we will use a chi-square test to assess changes in proportions. Interim looks will be scheduled after each phase, applying Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be reviewed and signed off by the product management team.
