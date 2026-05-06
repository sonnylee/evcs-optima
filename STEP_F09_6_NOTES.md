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

## §2 / §4

(To be filled in after each subsequent F09.6 commit.)
