# Customer Notes — DataPipe Technical Dependencies

## Interview 1: Nina V. (Platform Architect, Enterprise Customer)
Nina's team processes 50 billion events per day through DataPipe. "We've noticed increasing instability in the Kafka layer — consumer rebalances are taking 10x longer than a year ago, and we suspect it's related to the outdated ZooKeeper dependency." She also raised concerns about the VendorX transformation SDK: "If the price triples, we'll need to migrate regardless. Better to start now on our terms than be forced into an emergency migration later."

## Interview 2: Sam D. (Security Engineer, Financial Services Customer)
Sam's security team flagged 7 CVEs in DataPipe's dependency tree during their quarterly vendor review. "The Kafka 2.8 CVE is especially concerning — it allows remote code execution under specific configurations. We need a remediation timeline within 30 days or our CISO will require us to sandbox the integration." He also noted that Python 3.9 EOL means no more security patches, which violates their vendor security policy.

## Interview 3: Ayumi T. (Data Engineering Lead, E-Commerce Customer)
Ayumi's team has built 40 custom Flink jobs on top of DataPipe. "We chose DataPipe because of the transformation SDK, but if VendorX pricing makes it unsustainable, we need to know what the migration path looks like. Rewriting 40 jobs is a 6-month project for us." She asked for an open-source-compatible transformation API so they aren't locked into another proprietary dependency.
