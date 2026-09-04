# Architecture invariants
Treat these as review heuristics, never defect proof: idempotency for duplicate delivery; explicit retry ownership; finite remote timeouts; no fake NOT_FOUND for outages; recovery for cross-system partial success; safe production defaults; traceable critical state changes; compatible contracts; no unnecessary sensitive-data logging.
