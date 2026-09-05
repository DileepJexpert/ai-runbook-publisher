# Testing Review Rules

- Do not say merely "add tests".
- Identify the exact new/changed behavior lacking coverage.
- Unit tests should isolate local logic; integration tests should prove important framework/datastore/serialization/transaction behavior.
- For failure-handling changes, test the failure semantics that matter: timeout, retry exhaustion, partial success, duplicate/replay, or dependency unavailable as applicable.
- For contract changes, test backward compatibility scenarios when relevant.
- For concurrency/idempotency findings, propose a test that can reproduce the race/duplicate behavior.
