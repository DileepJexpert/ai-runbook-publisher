# Kafka Review Rules

Review only if the PR affects Kafka or a call path invoked by Kafka.

- Determine consumer acknowledgement/offset behavior and error-handler configuration.
- Determine retry topic/DLT behavior if present.
- Check idempotency against duplicate delivery and replay.
- Inspect side effects that occur before offset acknowledgement.
- Check partition key and ordering assumptions when business ordering matters.
- Evaluate consumer concurrency/rebalance implications for shared state.
- Check producer success/failure semantics and whether DB state can diverge from published events.
- Review schema compatibility and optional/default field behavior for event contract changes.
- Combine Kafka retries with method/client/SDK retries when estimating attempts.
