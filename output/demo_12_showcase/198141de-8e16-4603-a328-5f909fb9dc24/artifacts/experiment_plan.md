# Experiment Plan: SmartNotify

**Run ID:** 198141de-8e16-4603-a328-5f909fb9dc24
**Date:** 2026-03-06

---

## Hypothesis

If we optimize notification content to improve relevance and engagement, then the Notification Click-Through Rate (CTR) will increase by 25% because users will find the notifications more appealing and relevant to their interests. This is supported by the need to enhance user engagement as indicated by the North Star Metric [metrics-001] and the importance of CTR as a primary KPI [metrics-002].

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                          | Baseline | Target | Measurement Method                   | Window          |
|---------------------------------|----------|--------|--------------------------------------|-----------------|
| User Engagement (DAU)          | 45000    | 50000  | User login tracking                  | 30 days         |
| Notification Click-Through Rate | 0.12     | 0.15   | Click tracking on notifications      | 30 days         |
| Unsubscribe Rate                | 0.08     | 0.05   | Tracking unsubscribe actions         | 30 days         |

### Guardrail Metrics

| Metric                          | Current Value | Max Acceptable Degradation | Measurement Method                   |
|---------------------------------|----------------|----------------------------|--------------------------------------|
| Average Notifications per User   | 23             | 20                         | Notification delivery tracking         |
| 95th Percentile Delivery Latency | 340            | 200                        | Latency tracking in delivery pipeline |

## Experiment Design

We will conduct a standard A/B test with a control group receiving the current notification content and a treatment group receiving the optimized notification content. Traffic allocation will be 50% control and 50% treatment. Users will be randomly assigned to either group based on user ID to ensure unbiased results. Ethical considerations are met as all users will receive notifications, and the treatment group will only experience an enhancement in content, not a reduction in service.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 25% increase in CTR with a power of 0.8 and a significance level of 0.05, we will require a sample size of at least 1000 users per arm (2000 total). Given our average daily user engagement of 45000, we estimate the experiment will take approximately 30 days to reach the required sample size.

## Segmentation

Post-hoc analysis will focus on segments such as new vs. returning users and users with different notification preferences (e.g., frequency of notifications). These segments are crucial for understanding how different user cohorts respond to notification content changes, and users will be classified based on their interaction history and preferences recorded in the system.

## Rollback Criteria

The experiment will be terminated if the Unsubscribe Rate exceeds 0.08 or if the Average Notifications per User exceeds 23 during the experiment. Additionally, if the 95th Percentile Delivery Latency exceeds 340ms, we will halt the experiment to ensure user experience is not compromised.

## Data Collection Plan

We will track the following events: 'user_login' for User Engagement, 'notification_click' for Notification Click-Through Rate, 'unsubscribe_action' for Unsubscribe Rate, 'notification_delivery' for Average Notifications per User, and 'delivery_latency' for 95th Percentile Delivery Latency. We will also implement assistive technology detection to monitor screen reader usage and keyboard-only navigation patterns.

## Analysis Plan

We will use a chi-square test for proportions to analyze the CTR and Unsubscribe Rate between control and treatment groups. Interim looks will be scheduled at 15 days, and we will apply the Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be reviewed and signed off by the product management team and data analysis team.
