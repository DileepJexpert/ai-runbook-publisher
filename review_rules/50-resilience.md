# Resilience Review Rules

- Never recommend retry solely because a dependency is remote.
- Retry requires a retryable failure, idempotent/recoverable operation, bounded attempts/backoff and clear ownership.
- Calculate effective retries across caller, Kafka, framework, HTTP client and SDK layers when possible.
- Never recommend a circuit breaker solely because a remote dependency exists.
- Circuit-breaker recommendations require a concrete failure-amplification scenario and intentional open-circuit behavior.
- A fallback must preserve semantics. Do not turn dependency failure into fake success or `NOT_FOUND`.
- Timeouts, retries and circuit breakers must be analyzed together as one failure strategy.
- Consider retry storms during dependency outages.
