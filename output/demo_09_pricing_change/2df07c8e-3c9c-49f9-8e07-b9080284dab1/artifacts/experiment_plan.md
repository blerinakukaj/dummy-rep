# Experiment Plan: CloudMetrics

**Run ID:** 2df07c8e-3c9c-49f9-8e07-b9080284dab1
**Date:** 2026-03-09

---

## Hypothesis

If we implement a new pricing model that offers tiered subscription options, then the Monthly Recurring Revenue (MRR) will increase by 12.18% because customers will be more likely to choose higher-value plans that better meet their needs. This is supported by findings indicating that customer segmentation and pricing sensitivity can significantly impact revenue and churn rates [metrics-005].

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                       | Baseline | Target   | Measurement Method               | Window              |
|------------------------------|----------|----------|----------------------------------|---------------------|
| Monthly Recurring Revenue (MRR) | 312000   | 350000   | Monthly financial reporting       | Monthly             |
| Customer Churn Rate          | 8.5      | 5        | Customer database analysis        | Monthly             |

### Guardrail Metrics

| Metric                       | Current Value | Max Acceptable Degradation | Measurement Method               |
|------------------------------|---------------|----------------------------|----------------------------------|
| Net Promoter Score (NPS)    | 42            | No more than 5% decline   | Quarterly customer surveys        |

## Experiment Design

The experiment will be conducted as a phased rollout of the new pricing model. The rollout will occur in the following phases:
1. Phase 1: 10% of users will be exposed to the new pricing model for 7 days. Go/no-go criteria: MRR must not decline by more than 2% compared to the previous month.
2. Phase 2: If Phase 1 is successful, increase to 25% for another 7 days with the same go/no-go criteria.
3. Phase 3: If Phase 2 is successful, increase to 50% for 7 days with the same go/no-go criteria.
4. Phase 4: If Phase 3 is successful, roll out to 100% of users.
Ethical considerations: All users will receive the new pricing model, ensuring no group is unfairly disadvantaged, especially those sensitive to pricing changes.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 12.18% increase in MRR with a power of 0.8 and a significance level of 0.05, we will require a sample size of at least 1000 users per phase. Given our traffic volume, we estimate the total duration of the experiment to be 30 days, with each phase lasting 7 days.

## Segmentation

Post-hoc analysis will focus on customer segments based on subscription tier (basic vs. premium) and customer tenure (new vs. returning). This segmentation is critical as it will help identify which groups are most responsive to the new pricing model and ensure targeted communication strategies are developed.

## Rollback Criteria

The experiment will be rolled back if MRR declines by more than 2% compared to the previous month or if the NPS drops below 40. Immediate action will be taken to revert to the previous pricing model if these thresholds are breached.

## Data Collection Plan

We will track the following events: 'subscription_change' (to capture changes in subscription tier), 'monthly_revenue' (to measure MRR), 'customer_churn' (to analyze churn rates), and 'nps_response' (to collect NPS data). Additionally, we will log assistive technology usage to ensure that all customer segments are represented.

## Analysis Plan

We will use a paired t-test to analyze MRR changes and churn rates before and after the implementation of the new pricing model. For NPS, we will use a chi-square test to compare proportions of promoters, passives, and detractors. Interim looks will be scheduled after each phase, applying Holm-Bonferroni correction for multiple comparisons. A significance level of 0.05 will be maintained, and results will be reviewed and signed off by the product management team.
