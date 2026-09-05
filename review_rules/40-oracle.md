# Oracle / Relational Database Review Rules

Review only if the PR affects relational persistence or an impacted path uses it.

- Verify transaction boundaries and rollback behavior.
- Inspect queries and existing indexes before claiming an index is required.
- Consider uniqueness/constraints for business invariants.
- Identify lock duration, lock ordering and high-contention update patterns where applicable.
- Check migrations for compatibility, ordering and rollback/roll-forward strategy used by the project.
- Detect N+1/query amplification on high-frequency paths.
- Consider connection-pool occupancy when DB transactions contain blocking remote calls.
