# Experiment Plan: DataPipe

**Run ID:** f5c915ad-18fa-441e-81b6-7d94797d37e6
**Date:** 2026-03-06

---

## Hypothesis

If we remediate critical CVEs, then the number of events processed per day will increase by 50% because improved security will enhance platform reliability and user trust.

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                               | Baseline | Target | Measurement Method                               | Window          |
|--------------------------------------|----------|--------|--------------------------------------------------|-----------------|
| Events Processed Per Day             | 50       | 75     | Daily aggregation of events processed             | 30 days         |
| Services on EOL Dependencies         | 18       | 10     | Count of services using EOL dependencies          | 30 days         |

### Guardrail Metrics

| Metric                               | Current Value | Max Acceptable Degradation | Measurement Method                               |
|--------------------------------------|---------------|---------------------------|--------------------------------------------------|
| Critical CVEs Open                   | 7             | 0                         | Count of open critical CVEs                       |

## Experiment Design

We will conduct a phased rollout of the CVE remediation across 4 phases: 10% → 25% → 50% → 100%. Each phase will last 7 days, with a go/no-go decision based on the guardrail metric of critical CVEs remaining at 0. If the number of open critical CVEs exceeds 0 at any phase, we will halt the rollout and reassess the remediation process. Ethical considerations ensure that all users benefit from the security improvements without withholding fixes from any group.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 50% increase in events processed per day with a power of 0.8 and significance level of 0.05, we require a sample size of at least 1000 users per arm. Given our traffic volume, we estimate that the experiment will last 30 days to gather sufficient data across all phases.

## Segmentation

Post-hoc analysis will focus on segments such as services using EOL dependencies versus those that do not, as well as services with varying levels of critical CVEs. This segmentation is crucial to understand the impact of remediation on different service types and to identify any specific cohorts that may benefit more from the changes. Users will be classified based on their service dependencies and CVE status.

## Rollback Criteria

The experiment will be rolled back if the number of open critical CVEs exceeds 0 at any point during the rollout, or if the primary KPI, Services on EOL Dependencies, does not show a downward trend towards the target of 10 services.

## Data Collection Plan

We will log the following events: `event_processed`, `cve_remediation_status`, `service_dependency_status`. Each event will include properties such as `service_id`, `timestamp`, `cve_id`, and `dependency_type` to accurately measure the success and guardrail metrics.

## Analysis Plan

We will use a paired t-test to compare the means of events processed per day before and after the remediation. Interim looks will be scheduled at the end of each phase, applying Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be signed off by the product management team.
