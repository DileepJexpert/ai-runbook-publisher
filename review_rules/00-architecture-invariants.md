# Architecture Invariants

These are default architecture review invariants for a Spring Boot / Kafka / Aerospike / Oracle banking workload. They are review heuristics, not proof of defects. Repository and organization-specific evidence always wins.

1. Financial/event-consuming operations should be idempotent when duplicate delivery is possible.
2. Retry ownership must be explicit. Nested retries across Kafka, Spring, HTTP clients and SDKs must be evaluated together.
3. Every remote dependency call must have a finite timeout somewhere in the effective call stack.
4. Dependency unavailability must not be silently represented as business `NOT_FOUND`.
5. Unbounded datastore scans should not exist on high-frequency synchronous transaction paths without explicit justification.
6. Long-running database transactions should not hold connections/locks while waiting on remote I/O without explicit justification.
7. Cross-system side effects must have a defined recovery strategy for partial success.
8. Sensitive customer/payment data must not be unnecessarily logged and must follow masking policy.
9. Contract/schema changes must consider backward/forward compatibility with existing consumers.
10. Business-critical state changes should be traceable according to the project's audit standard.
11. Failure handling must preserve business correctness before availability convenience.
12. Configuration defaults must not silently create unsafe production behavior.
