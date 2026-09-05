# Aerospike Review Rules

Review only if the PR affects Aerospike or an impacted call path uses it.

- Prefer understanding the data model before suggesting a secondary index.
- For exact high-frequency lookups, compare direct primary-key lookup, lookup-set pattern and secondary-index query based on actual constraints.
- Identify full scans and determine whether they are bounded, exceptional/admin-only, or on a production critical path.
- Inspect `Policy`, `QueryPolicy`, `WritePolicy` and effective client timeout/retry settings.
- Understand TTL/expiration behavior where it affects correctness.
- Inspect record generation/version semantics for concurrent update safety where relevant.
- Check serialization/schema compatibility for existing records.
- Secondary indexes have operational/write costs and do not automatically enforce uniqueness; do not prescribe them without evidence.
