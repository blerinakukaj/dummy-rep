# Experiment Plan: SmartNotify

**Run ID:** 6e92cdd8-0d34-4be2-802d-e21fd30d6906
**Date:** 2026-03-09

---

## Hypothesis

If we improve the notification format, then the Notification Click-Through Rate (CTR) will increase by 25% because a more engaging format will capture user attention more effectively. This hypothesis is supported by finding [metrics-002], which indicates that the current CTR is below the target, suggesting room for improvement in notification effectiveness.

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                          | Baseline | Target | Measurement Method                    | Window         |
|---------------------------------|----------|--------|---------------------------------------|----------------|
| User Engagement (DAU)          | 45000    | 50000  | User login tracking                   | 30 days        |
| Notification Click-Through Rate  | 0.12     | 0.15   | Click tracking on notifications       | 30 days        |
| Unsubscribe Rate                | 0.08     | 0.05   | Unsubscribe tracking                  | 30 days        |

### Guardrail Metrics

| Metric                          | Current Value | Max Acceptable Degradation | Measurement Method                    |
|---------------------------------|----------------|----------------------------|---------------------------------------|
| Average Notifications per User   | 23             | 20                         | Notification delivery logs             |
| 95th Percentile Delivery Latency | 340            | 200                        | Performance monitoring tools           |

## Experiment Design

This will be a standard A/B test with a control group and a treatment group. The control group (50% of users) will receive the current notification format, while the treatment group (50% of users) will receive the new notification format. Users will be randomly assigned to each group to ensure unbiased results. Ethical considerations are addressed as all users will receive notifications, and the treatment group will only experience an enhancement in their notification format.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 25% increase in CTR with a power of 0.8 and significance level of 0.05, we will require a sample size of at least 1000 users per arm. Given the current user engagement levels, we estimate that the experiment will last for 30 days to gather sufficient data.

## Segmentation

Post-hoc analysis will focus on segments such as new users vs. returning users and users with different device types (e.g., Android vs. iOS). This segmentation is important as it allows us to understand how different user cohorts respond to the notification format changes, ensuring that improvements benefit all user types.

## Rollback Criteria

The experiment will be rolled back if the Unsubscribe Rate exceeds 0.08 or if the Average Notifications per User exceeds 23. Additionally, if the 95th Percentile Delivery Latency exceeds 340ms, the experiment will be halted to prevent negative user experiences.

## Data Collection Plan

We will track the following events: `user_login`, `notification_click`, `unsubscribe_event`, `notification_delivery`, and `notification_latency`. We will also log user device types to facilitate segmentation analysis. This data will help measure the success and guardrail metrics accurately.

## Analysis Plan

We will use a chi-square test for proportions to analyze the CTR and Unsubscribe Rate, as these metrics are categorical. For the User Engagement metric, we will use a paired t-test to compare means before and after the experiment. Interim looks will be scheduled at 15 days, applying the Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be signed off by the product manager and the data analyst.
