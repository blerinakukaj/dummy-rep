# Experiment Plan: LearnPath

**Run ID:** 101d847c-6899-492f-ac2c-d3da82309a9c
**Date:** 2026-03-09

---

## Hypothesis

If we implement ARIA roles and improve keyboard navigation, then the Screen Reader Task Completion Rate will increase by 233.33% because users will be able to navigate and complete tasks more effectively using assistive technologies.

## Success Metrics & Guardrails

### Primary Success Metrics

| Metric                                   | Baseline | Target | Measurement Method                                              | Window         |
|------------------------------------------|----------|--------|-----------------------------------------------------------------|----------------|
| Accessibility Compliance Rate             | 13.33%   | 100%   | Percentage of pages passing WCAG 2.1 AA standards              | 30 days        |
| Screen Reader Task Completion Rate        | 15%      | 50%    | Percentage of tasks completed by screen reader users            | 30 days        |
| Keyboard-Only Task Completion Rate        | 30%      | 70%    | Percentage of tasks completed by keyboard-only users            | 30 days        |

### Guardrail Metrics

| Metric                     | Current Value | Max Acceptable Degradation | Measurement Method                                           |
|----------------------------|----------------|---------------------------|------------------------------------------------------------|
| WCAG Violations Count      | 47             | 0                         | Count of WCAG violations                                     |

## Experiment Design

We will conduct a phased rollout of the accessibility improvements. The rollout will occur in the following phases:
1. **Phase 1**: 10% of users for 7 days. Go/no-go criteria: If WCAG Violations Count remains at 47 or fewer, proceed to Phase 2.
2. **Phase 2**: 25% of users for 7 days. Go/no-go criteria: If WCAG Violations Count remains at 47 or fewer, proceed to Phase 3.
3. **Phase 3**: 50% of users for 7 days. Go/no-go criteria: If WCAG Violations Count remains at 47 or fewer, proceed to full rollout.
4. **Full Rollout**: 100% of users. Ethical considerations ensure that all users, including those with disabilities, receive the accessibility improvements without withholding them from any group.

## Sample Size & Duration

To achieve a minimum detectable effect (MDE) of 10% increase in task completion rates with a power of 0.8 and a significance level of 0.05, we calculate:
- Sample size per arm = 1000 (minimum required)
- Total sample size = 2000
- Given the traffic volume, we estimate the experiment will run for 30 days to gather sufficient data across all phases.

## Segmentation

Post-hoc analysis will focus on:
- **Screen Reader Users**: To assess improvements specifically for visually impaired users.
- **Keyboard-Only Users**: To evaluate enhancements for motor-impaired users.
- **New vs. Returning Users**: To understand if the changes impact user experience differently based on familiarity with the platform.
Users will be identified through user agent strings and session data.

## Rollback Criteria

The experiment will be rolled back if:
- WCAG Violations Count exceeds 47 at any phase.
- Screen Reader Task Completion Rate decreases below 15%.
- Keyboard-Only Task Completion Rate decreases below 30%.

## Data Collection Plan

We will track the following events:
- `page_audit_pass`: To measure Accessibility Compliance Rate.
- `task_completion_screen_reader`: To measure Screen Reader Task Completion Rate.
- `task_completion_keyboard`: To measure Keyboard-Only Task Completion Rate.
- `wcag_violation_detected`: To track WCAG Violations Count.
- Assistive technology detection will be implemented to identify screen reader usage and keyboard-only navigation patterns.

## Analysis Plan

We will use a chi-square test for proportions to evaluate the differences in task completion rates across user segments. Interim looks will be scheduled after each phase, applying Holm-Bonferroni correction for multiple comparisons. The significance level will be set at 0.05, and results will be signed off by the product management team and the accessibility compliance officer.
