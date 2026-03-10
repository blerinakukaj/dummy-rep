# Experiment Plan: DataPipe

**Run ID:** d0eeb368-d35f-4ba2-91f9-0b017e65a3c7
**Date:** 2026-03-06

---

## Hypothesis

If we reduce the number of services on end-of-life dependencies from 18 to 10, then the events processed per day will increase by 50% because improved dependency management will enhance system performance and reliability.

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                             | Baseline | Target | Measurement Method                             | Window        |
|------------------------------------|----------|--------|------------------------------------------------|---------------|
| Events Processed Per Day           | 50       | 75     | Daily aggregation of processed events          | 30 days      |
| Services on EOL Dependencies        | 18       | 10     | Count of services with EOL dependencies        | 30 days      |

### Guardrail Metrics

| Metric                             | Current Value | Max Acceptable Degradation | Measurement Method                             |
|------------------------------------|---------------|---------------------------|------------------------------------------------|
| Critical CVEs Open                 | 7             | 0                         | Count of open critical CVEs                     |

## Experiment Design

We will implement a phased rollout to reduce the number of services on EOL dependencies. The rollout will occur in three phases: 10% of services will be updated in the first phase, monitored for 10 days; if metrics are satisfactory, we will proceed to 25% for another 10 days; finally, if successful, we will update 50% of services for the remaining 10 days. The go/no-go criteria for advancing phases will be based on the success metrics showing positive trends without breaching guardrail metrics.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 50% increase in events processed per day with a power of 0.8 and significance level of 0.05, we calculate the required sample size using the formula for comparing two proportions. The minimum sample size per arm is 1000, ensuring we meet the policy constraint. Given our traffic volume, the estimated duration for the full experiment is 30 days.

## Segmentation

We will analyze the following cohorts post-hoc: services with high dependency risk vs. low dependency risk, and services that have undergone recent updates vs. those that have not. This segmentation is crucial to understand the impact of dependency management on different service types and their performance metrics.

## Rollback Criteria

The experiment will be rolled back if the number of critical CVEs open exceeds 7 or if the events processed per day drop below 50 during any phase of the rollout.

## Data Collection Plan

We will log the following events: `event_processed`, `service_updated`, and `cve_opened`. Each event will include properties such as `service_id`, `timestamp`, and `cve_severity` to accurately measure success and guardrail metrics.

## Analysis Plan

We will use a paired t-test to compare the means of events processed per day before and after the changes. Interim looks will be scheduled after each phase, applying Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be signed off by the product management team.
