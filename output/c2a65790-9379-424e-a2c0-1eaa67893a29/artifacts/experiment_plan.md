# Experiment Plan: SmartNotify

**Run ID:** c2a65790-9379-424e-a2c0-1eaa67893a29
**Date:** 2026-03-09

---

## Hypothesis

If we optimize the notification content and delivery timing, then the Notification Click-Through Rate (CTR) will increase by 25% because more relevant notifications will engage users effectively. This is supported by the need to improve user engagement as indicated by the North Star Metric [metrics-001] and the Primary KPI [metrics-002].

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                          | Baseline | Target | Measurement Method                     | Window          |
|----------------------------------|----------|--------|----------------------------------------|------------------|
| User Engagement (DAU)           | 45000    | 60000  | User login tracking                    | 30 days          |
| Notification Click-Through Rate   | 0.12     | 0.15   | Click tracking on notifications        | 30 days          |

### Guardrail Metrics

| Metric            | Current Value | Max Acceptable Degradation | Measurement Method             |
|--------------------|---------------|-----------------------------|--------------------------------|
| Unsubscribe Rate    | 0.08          | 0.05                        | Unsubscribe tracking         |

## Experiment Design

We will conduct a phased rollout of the optimized notification content and delivery timing. The rollout will proceed as follows: 10% of users will receive the changes for the first week. If the unsubscribe rate remains below 0.05 and the CTR increases, we will expand to 25% for the second week. If successful, we will then move to 50% for the third week, and finally to 100% in the fourth week. Each phase will require a go/no-go decision based on the guardrail metrics.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 0.03 in CTR with a power of 0.8 and a significance level of 0.05, we will require a sample size of approximately 1000 users per arm. Given our traffic volume, we estimate the experiment will last 30 days, allowing sufficient time for data collection across all phases.

## Segmentation

Post-hoc analysis will focus on screen reader users vs. sighted users, as well as new vs. returning users. This segmentation is crucial to understand how different user groups interact with notifications, particularly given the accessibility concerns identified [risk-004]. Users will be identified through their device settings and user profiles.

## Rollback Criteria

The experiment will be rolled back if the unsubscribe rate exceeds 0.05 or if the CTR does not show a statistically significant increase after the first phase. Additionally, if any critical issues arise during the rollout, such as delivery failures on Android 14 devices [risk-002], the experiment will be halted immediately.

## Data Collection Plan

We will track the following events: `user_login`, `notification_click`, and `unsubscribe_action`. Each event will include properties such as `user_id`, `timestamp`, `notification_id`, and `device_type` to facilitate analysis of success and guardrail metrics. Additionally, we will implement assistive technology detection to monitor screen reader usage.

## Analysis Plan

We will use a chi-square test for proportions to analyze the CTR and unsubscribe rates. Interim looks will be scheduled at the end of each phase, applying the Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be reviewed and signed off by the product management team.
