# Experiment Plan: PageSpeed

**Run ID:** 52672bc6-8a27-478b-9af6-e15501799d17
**Date:** 2026-03-06

---

## Hypothesis

If we optimize the API performance, then the API p95 Latency will decrease by 10% because improved backend processing will reduce response times.

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                  | Baseline | Target | Measurement Method                       | Window         |
|-------------------------|----------|--------|------------------------------------------|----------------|
| Dashboard Load Time     | 1200 ms  | 1200 ms| Continuous monitoring of dashboard load time | 30 days        |
| API p95 Latency         | 120 ms   | 108 ms | API performance monitoring                | 30 days        |

### Guardrail Metrics

| Metric                  | Current Value | Max Acceptable Degradation | Measurement Method                       |
|-------------------------|---------------|-----------------------------|------------------------------------------|
| Error Rate Percentage    | 0.4%          | 0.4%                        | Error tracking system                       |

## Experiment Design

We will implement a phased rollout of the API performance optimization. The rollout will proceed as follows: 10% of users will receive the changes for the first week, followed by 25% for the second week, and then 50% for the third week. If the error rate percentage exceeds 0.4% at any phase, we will halt the rollout and revert to the previous version. Ethical considerations are met as all users will eventually receive the performance improvements.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 10% with a power of 0.8 and a significance level of 0.05, we will require a sample size of at least 1000 users per arm. Given our traffic volume, we estimate the experiment will last 30 days, adhering to the maximum experiment duration policy.

## Segmentation

Post-hoc analysis will focus on user segments such as new vs. returning users and users with different device types (desktop vs. mobile). This segmentation is important to understand how different user cohorts are affected by the performance changes, allowing us to tailor future optimizations.

## Rollback Criteria

The experiment will be rolled back if the error rate percentage exceeds 0.4% or if the API p95 Latency does not show at least a 5% improvement after the first phase.

## Data Collection Plan

We will log the following events: `dashboard_load_time`, `api_response_time`, and `error_rate`. Each event will include properties such as `user_id`, `timestamp`, and `device_type` to facilitate detailed analysis. Additionally, we will track assistive technology usage to ensure accessibility compliance.

## Analysis Plan

We will use a paired t-test to compare API p95 Latency before and after the optimization. Interim looks will be scheduled after each phase of the rollout, applying Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be signed off by the product management team.
