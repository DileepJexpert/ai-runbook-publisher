# Spring Review Rules

Review only when relevant.

- Verify proxy-based annotations actually apply at the invocation boundary; check self-invocation.
- Review `@Transactional` scope, propagation and exception rollback semantics.
- Flag remote calls inside database transactions only when they can materially increase lock/connection duration or break consistency.
- Check controller/service/repository responsibility boundaries when they affect correctness/testability.
- Validate external input at a defined boundary.
- Check exception translation so infrastructure failure is not converted into incorrect business semantics.
- For async work, inspect MDC/security/transaction/context propagation and lifecycle semantics.
- Check singleton bean mutable state for concurrency safety.
- Prefer configuration externalization for environment-dependent behavior.
