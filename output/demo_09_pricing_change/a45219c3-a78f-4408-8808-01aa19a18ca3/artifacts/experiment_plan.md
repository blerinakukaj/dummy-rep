# Experiment Plan: CloudMetrics

**Run ID:** a45219c3-a78f-4408-8808-01aa19a18ca3
**Date:** 2026-03-06

---

## Hypothesis

If we implement a consumption-based pricing model, then Monthly Recurring Revenue (MRR) will increase by 28.16% because it aligns pricing with customer usage patterns, encouraging higher spending from active users. This is supported by findings indicating that MRR is critical for business success [metrics-001].

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric | Baseline | Target | Measurement Method | Window |
|--------|----------|--------|--------------------|--------|
| MRR    | 312000   | 400000 | Monthly financial reporting | Monthly |
| ARPA   | 168.65   | 200    | Monthly financial reporting | Monthly |

### Guardrail Metrics

| Metric                             | Current Value | Max Acceptable Degradation | Measurement Method              |
|------------------------------------|---------------|---------------------------|----------------------------------|
| Projected Churn Increase Percentage | 8.5           | 5                         | Customer churn analysis          |

## Experiment Design

The experiment will be a phased rollout of the consumption-based pricing model. The rollout will occur in four phases: 10% of users for 1 week, 25% for 1 week, 50% for 1 week, and 100% for the final phase. Each phase will be evaluated based on the success metrics and guardrail metrics. A go/no-go decision will be made at the end of each phase based on whether MRR has increased and if the projected churn increase percentage remains below 5%. Ethical considerations are addressed by ensuring all users receive the new pricing model eventually, with no group being denied necessary accessibility improvements.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 28.16% increase in MRR with a power of 0.8 and a significance level of 0.05, we will require a sample size of at least 1000 users per arm. Given the traffic volume, the estimated duration for the entire experiment will be 30 days, allowing for sufficient data collection across all phases.

## Segmentation

Post-hoc analysis will segment users into cohorts based on their account size (small, medium, large) and usage patterns (high, medium, low). This segmentation is important to understand how different customer tiers respond to the new pricing model. Users will be identified based on their account type and usage data collected during the experiment.

## Rollback Criteria

The experiment will be rolled back if the MRR does not increase by at least 5% after any phase or if the projected churn increase percentage exceeds 5%. Immediate termination will occur if there is a significant drop in MRR or if customer feedback indicates severe dissatisfaction with the new pricing model.

## Data Collection Plan

We will collect data on the following events: 'monthly_revenue', 'customer_churn', 'account_type', 'usage_pattern', and 'customer_feedback'. Specific properties will include account ID, revenue generated, churn status, account size, and usage metrics. Additionally, we will track assistive technology usage to ensure compliance with accessibility standards.

## Analysis Plan

We will use a paired t-test to compare MRR and ARPA before and after the implementation of the new pricing model. Interim looks will be scheduled at the end of each phase, applying Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be reviewed and signed off by the product management team.
