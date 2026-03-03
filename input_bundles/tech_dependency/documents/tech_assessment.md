# Tech Assessment — DataPipe Dependency Risks

## Critical Dependencies at Risk

### 1. Apache Kafka 2.8 (EOL: Q1 2026)
- **Risk Level:** Critical
- **Impact:** Core message broker for entire platform; 14 producers, 22 consumers
- **CVEs:** CVE-2023-25194 (RCE, CVSS 8.8), CVE-2024-31141 (info disclosure, CVSS 6.5)
- **Migration Path:** Upgrade to Kafka 3.7+ with KRaft mode, eliminating ZooKeeper. Requires client library upgrades across all services. Estimated effort: 8-12 weeks.
- **Risk:** Breaking changes in consumer group protocol between 2.x and 3.x

### 2. VendorX ETL SDK v4.2 (Price increase: Jan 2026)
- **Risk Level:** Critical (financial)
- **Impact:** Transformation layer for all data pipelines; 40+ customer-built jobs depend on SDK APIs
- **Alternatives Evaluated:**
  - Apache Beam: Good abstraction, multi-runner support, 70% API compatibility
  - dbt: SQL-focused, not suitable for streaming workloads
  - Custom Flink: Maximum flexibility but 6+ month build time
- **Recommendation:** Apache Beam with custom compatibility shims for VendorX-specific APIs

### 3. Python 3.9 (EOL: October 2025)
- **Risk Level:** High
- **Impact:** 8 pipeline worker services, internal ML library
- **Blockers:** numpy 1.x incompatibility, custom C extensions, removed asyncio APIs
- **Estimated Effort:** 4-6 weeks with focused sprint

### 4. Redis 6.2 (EOL: March 2026)
- **Risk Level:** Medium-High
- **Impact:** Caching layer, single point of failure in us-east-1
- **Migration Path:** Redis 7.x with Redis Cluster multi-region or DragonflyDB for cost savings
- **Estimated Effort:** 3-4 weeks
