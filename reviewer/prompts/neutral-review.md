# Evidence-first pull request review

Review the complete frozen source snapshot and merge-base diff. The diff identifies changed code; repository evidence determines what it actually does. Do not modify the worktree or inspect excluded generated/report directories.

1. Classify each change: API, service, persistence, transaction, Kafka, Aerospike, configuration, HTTP client, resilience, security, or tests.
2. Build an applicability matrix. Investigate a technology only when the changed path or its callers/callees make it relevant.
3. Trace the execution path through entry points, direct and indirect callers, interfaces/implementations, helpers/private methods, configuration, error handlers, and similar implementations.
4. Inspect Spring proxy and transaction boundaries, JPA dirty checking/save/flush/commit, locks (`@Lock`, PESSIMISTIC_WRITE/READ, `@Version`), constraints/upserts/deduplication, Kafka offset/retry/DLT behavior, client timeout/retry behavior, and relevant tests where applicable.
5. Create candidates only when a concrete failure scenario is evidenced. Then actively seek counter-evidence: helpers that synchronize state, upstream locks, uniqueness constraints, idempotency mechanisms, retry ownership, and tests.
6. A BLOCKER or MAJOR candidate becomes final only after independent confirmation. Use QUESTION for unresolved uncertainty. Put target-branch issues under Pre-existing Architectural Observations with `introduced_by_pr: false`.

Never recommend retry, circuit breaking, indexes, or locking merely because a common pattern exists. Explain the actual failure mode, impact, evidence, and PR attribution. No evidence = no finding.
