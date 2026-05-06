# Step F09.6 — Notes

## §1 Bug fixes

- **§1.1 updateCarPort rollback**: Added `prev` snapshot before optimistic
  update; on PATCH failure restore `carPorts: prev` and surface a clearer
  error message. UI now snaps back to last known-good state when network
  / backend fails.

- **§1.2 refreshSnapshot retry hint**: globalError message changed to
  `"Snapshot refresh failed — try the +/- button again"` to guide users
  toward the implicit retry path (any subsequent ±25 click will trigger
  a fresh refreshSnapshot).

- **§1.3 (deferred to Sprint 2)**: `<MaxRequiredField>` async race —
  rapid typing during in-flight PATCH could overwrite draft. TODO
  comment added at commit() function. Not reproducible in normal demo.

## §2 Backend integration tests

- **§2.1 SPEC §6.2 sequence regression**: pinned the 0/25/50/25/0
  user sequence with expected alloc 0/50/50/50/0 to prevent any
  future demand-floor regression like F09.5c. Test docstring
  carries the rationale for each step.

- **§2.2 Repeated-PATCH determinism**: verified rebuild-engine
  throwaway gives byte-identical snapshots between
  incremental-PATCH and direct-PATCH paths.

Backend test count: 55 → 57 passed (+ 23 xfailed unchanged).

## §4

(To be filled in after each subsequent F09.6 commit.)
