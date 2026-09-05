# Security / Compliance Review Rules

- Check authentication/authorization only where the change crosses or affects a trust boundary.
- Check sensitive data exposure in logs, error messages, metrics and events.
- Check secrets only where credentials/configuration handling changes.
- Audit logging is required only when the project's policy or a business/compliance event requires it; do not add audit events to every low-level method automatically.
- Preserve correlation/traceability across async or event-driven boundaries where project conventions require it.
- Distinguish security defects from governance requirements such as Jira references or approval metadata.
