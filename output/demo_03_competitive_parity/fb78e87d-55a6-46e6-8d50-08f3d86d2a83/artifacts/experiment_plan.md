# Experiment Plan: CollabDocs Real-time Editor

**Run ID:** fb78e87d-55a6-46e6-8d50-08f3d86d2a83
**Date:** 2026-03-09

---

## Hypothesis

If we enhance the real-time collaboration features in CollabDocs, then the Daily Active Users Engaged in Collaboration will increase by 25% because improved collaboration capabilities will attract more users to engage in collaborative sessions.

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                                      | Baseline | Target  | Measurement Method                                      | Window         |
|---------------------------------------------|----------|---------|--------------------------------------------------------|----------------|
| Daily Active Users Engaged in Collaboration  | 120000   | 150000  | Daily tracking of active users engaging in collaboration sessions. | Daily          |
| Daily Collaboration Sessions                 | 14200    | 17040   | Daily tracking of collaboration sessions initiated.     | Daily          |

### Guardrail Metrics

| Metric                                      | Current Value | Max Acceptable Degradation | Measurement Method                                      |
|---------------------------------------------|---------------|---------------------------|--------------------------------------------------------|
| Lock Frustrated Abandonment Rate           | 0.31          | 0.25                      | Daily tracking of abandonment rates due to locking issues. |

## Experiment Design

We will conduct an A/B test with a control group and a treatment group. The control group (50% of traffic) will use the existing collaboration features, while the treatment group (50% of traffic) will use the enhanced collaboration features. Users will be randomly assigned to either group at the session level to ensure unbiased results. Ethical considerations are met as all users will have access to the improved features post-experiment.

## Sample Size & Duration

To detect a minimum detectable effect (MDE) of 20% increase in Daily Collaboration Sessions with 80% power and a significance level of 0.05, we require a sample size of at least 1000 users per variant. Given our daily traffic, we estimate the experiment will last approximately 15 days to reach the required sample size of 2000 users.

## Segmentation

Post-hoc analysis will include segmentation by user type: new users vs. returning users, and users with assistive technologies (e.g., screen reader users vs. sighted users). This segmentation is important to understand how different user cohorts respond to the enhanced features and to ensure accessibility improvements are effective.

## Rollback Criteria

The experiment will be terminated if the Lock Frustrated Abandonment Rate exceeds 0.31 or if the Daily Active Users Engaged in Collaboration decreases by more than 5% from the baseline during the experiment.

## Data Collection Plan

We will collect the following events: `collaboration_session_initiated`, `user_engaged_in_collaboration`, and `session_abandoned_due_to_locking`. Each event will include properties such as `user_id`, `session_id`, `timestamp`, and `assistive_technology_used` to facilitate comprehensive analysis.

## Analysis Plan

We will use a two-sample t-test to compare the means of Daily Collaboration Sessions between the control and treatment groups. Interim looks will be scheduled at 7 days; we will apply the Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be signed off by the product management team.
