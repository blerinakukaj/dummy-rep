# Customer Notes — PageSpeed Performance Regression

## Interview 1: Jun W. (SRE Lead, Enterprise Customer)
Jun's team relies on PageSpeed for real-time production monitoring across 300 services. "When your dashboard takes 5 seconds to load, I can't use it during an incident — which is exactly when I need it most." He described switching to raw Grafana queries during the v3.2 regression period. "We almost moved to a competitor. The only thing that saved you was the 2-year contract." He wants SLA guarantees on dashboard load times and automated regression alerts.

## Interview 2: Maria C. (Product Analyst, Mid-Market Customer)
Maria uses PageSpeed for daily product analytics reviews. "The dashboard was my first tool every morning, but now I dread opening it because it takes forever to render my 15-chart dashboard." She reported that the WebSocket disconnections cause her real-time conversion funnel to go blank mid-presentation, which is embarrassing in stakeholder meetings. She wants performance baseline guarantees in the SLA.

## Interview 3: Chris B. (DevOps Manager, Startup Customer)
Chris has a small team and noticed the API latency regression immediately because their automated alerts pipeline calls PageSpeed APIs. "Our alerting latency doubled overnight, which means we're detecting incidents minutes later than before." He is evaluating alternatives and will switch if performance isn't restored within 30 days.
