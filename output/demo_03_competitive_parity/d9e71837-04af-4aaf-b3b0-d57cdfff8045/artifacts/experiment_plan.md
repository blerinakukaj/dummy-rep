# Experiment Plan: CollabDocs Real-time Editor

**Run ID:** d9e71837-04af-4aaf-b3b0-d57cdfff8045
**Date:** 2026-03-06

---

## Hypothesis

If we enhance the real-time collaboration features in CollabDocs, then the Daily Active Users Engaged in Collaboration will increase by 25% because improved functionality will lead to higher user engagement and satisfaction with collaborative tasks. This is supported by the need to increase daily collaboration sessions by 20% within the first quarter post-launch [metrics-002].

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                                         | Baseline | Target | Measurement Method                                         | Window         |
|------------------------------------------------|----------|--------|-----------------------------------------------------------|----------------|
| Daily Active Users Engaged in Collaboration     | 120000   | 150000 | Daily tracking of active users in collaboration sessions   | 30 days        |
| Daily Collaboration Sessions                     | 14200    | 17040  | Daily tracking of collaboration sessions                    | 30 days        |

### Guardrail Metrics

| Metric                          | Current Value | Max Acceptable Degradation | Measurement Method                                  |
|---------------------------------|---------------|---------------------------|----------------------------------------------------|
| Concurrent Edit Attempts Blocked | 2300          | 2500                      | Daily tracking of blocked edit attempts             |

## Experiment Design

We will conduct a phased rollout of the enhanced collaboration features. The rollout will proceed as follows: 10% of users will receive the update for 7 days, followed by a review of success and guardrail metrics. If the metrics meet the criteria, we will increase to 25% for another 7 days, then to 50% for 7 days, and finally to 100%. The go/no-go criteria for advancing to the next phase will be based on the success metrics meeting or exceeding the target and guardrail metrics not exceeding the acceptable degradation thresholds. Ethical considerations are addressed by ensuring all users receive the accessibility improvements.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) with a power of 0.8 and a significance level of 0.05, we will require a sample size of at least 1000 users per variant. Given our traffic volume, we estimate that the experiment will run for a maximum of 30 days to gather sufficient data across all phases.

## Segmentation

Post-hoc analysis will segment users into cohorts based on their engagement levels: new vs. returning users and users who utilize assistive technologies (e.g., screen reader users vs. sighted users). This segmentation is crucial to understand how different user groups interact with the new features and to ensure that enhancements meet diverse user needs.

## Rollback Criteria

The experiment will be rolled back if the Daily Active Users Engaged in Collaboration falls below 120000 or if the Concurrent Edit Attempts Blocked exceeds 2500 during any phase of the rollout.

## Data Collection Plan

We will track the following events: `collaboration_session_started`, `collaboration_session_ended`, `edit_attempt_blocked`, and `user_engagement_metrics`. These events will include properties such as user ID, session ID, and assistive technology usage to ensure comprehensive data collection.

## Analysis Plan

We will use a paired t-test for comparing means of Daily Active Users and Daily Collaboration Sessions before and after the rollout. For interim looks, we will apply the Holm-Bonferroni correction to account for multiple comparisons. The significance level will be set at 0.05, and results will be reviewed and signed off by the product management team.
