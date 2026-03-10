# Experiment Plan: EnterpriseSuite

**Run ID:** 57c812f2-883d-4582-8e51-b74e62e04b23
**Date:** 2026-03-06

---

## Hypothesis

If we optimize the onboarding process for enterprise tenants, then the Monthly Active Enterprise Users will increase by 25% because a more efficient onboarding experience will lead to higher user engagement and retention.

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                                   | Baseline | Target  | Measurement Method                           | Window         |
|------------------------------------------|----------|---------|----------------------------------------------|----------------|
| Monthly Active Enterprise Users           | 28000    | 35000   | User activity tracking through analytics     | Monthly        |
| Churn Rate for Enterprise Tenants       | 0.02     | 0.015   | Customer retention analysis                   | Quarterly      |

### Guardrail Metrics

| Metric                | Current Value | Max Acceptable Degradation | Measurement Method               |
|-----------------------|---------------|-----------------------------|----------------------------------|
| Uptime Percentage     | 0.9987        | 0.999                       | System monitoring tools          |

## Experiment Design

We will conduct an A/B test with a control group and a treatment group. The control group will experience the current onboarding process, while the treatment group will experience the optimized onboarding process. We will allocate 50% of the traffic to the control group and 50% to the treatment group. Randomization will occur at the user level to ensure unbiased results. Ethical considerations are met as all users will receive the onboarding process, but they will be assigned to different experiences.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 25% increase in Monthly Active Enterprise Users with a power of 0.8 and a significance level of 0.05, we will require a sample size of at least 1000 users per group. Given our current traffic, we estimate that the experiment will last approximately 30 days to reach the required sample size.

## Segmentation

Post-hoc analysis will focus on new versus returning enterprise tenants. This segmentation is vital as new users may respond differently to onboarding optimizations compared to returning users. New users will be identified based on their account creation date, while returning users will be those with prior activity within the last 6 months.

## Rollback Criteria

The experiment will be terminated if the Uptime Percentage drops below 0.9985 or if the Churn Rate for Enterprise Tenants exceeds 0.02 during the experiment period.

## Data Collection Plan

We will track the following events: `onboarding_start`, `onboarding_complete`, `monthly_active_user`, and `churn_event`. Properties will include user ID, onboarding method (control/treatment), and timestamps. Additionally, we will log assistive technology usage to understand the impact on users with disabilities.

## Analysis Plan

We will use a chi-square test for proportions to analyze the difference in Monthly Active Enterprise Users between the control and treatment groups. For churn rate analysis, we will use a paired t-test to compare pre- and post-experiment rates. Interim looks will be scheduled at 15 days, applying Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be signed off by the product manager and data analyst.
