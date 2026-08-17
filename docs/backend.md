# Backend

`api.py` is a synchronous FastAPI control plane. It serves the frontend, owns authentication and reservation transactions, and deliberately has no Docker dependency.

## Authentication

Only enabled rows in `teams` can receive an OTP. The request response indicates whether the address is approved so the frontend can show the administrator-contact flow. Requests are limited to five challenges per user per hour. Codes and session tokens are stored as SHA-256 hashes; the raw session token exists only in the browser's HTTP-only cookie.

Verification locks the newest usable challenge, increments attempts before comparison, consumes the challenge on success, and creates a server-side session. Logout revokes the matching session and deletes the cookie.

Authenticated users may replace or clear one SSH public key through `/me/ssh-key`. Administrators can manage another user's key through `/admin/users/{id}/ssh-key`. The API stores the canonical OpenSSH line and returns only fingerprint and comment.

State-changing requests enforce the configured browser `Origin` when an Origin header is present. Production must use HTTPS with `COOKIE_SECURE=true`.

## Reservation transaction

Reservation creation requires an authenticated enabled user, timezone-aware timestamps, and an `Idempotency-Key` header. The transaction locks the team row and follows two paths:

- If provisioning is not ready, queue initial provisioning and return `202` without reserving the slot.
- If ready, replay an identical idempotent request or insert the reservation, queue credential rotation, mark provisioning pending, and commit audit events.

Database constraints remain authoritative for past times, maximum duration, per-user booking count, and global overlap. Expected constraint failures are converted to stable `400` or `409` responses.

Reservation listings expose timing and ownership but hide another user's reservation ID. Cancellation is restricted to the owning user and a non-expired reservation.

## Health

- `/health/live` proves the API process can respond.
- `/health/ready` queries PostgreSQL, requires a scheduler heartbeat newer than 30 seconds, and rejects a scheduler-reported reconciliation error.

## Extension rules

- Put cross-request invariants in PostgreSQL, not only in Python.
- Keep user identity derived from the session; never accept ownership IDs from the browser.
- Use parameterized SQL and explicit transaction boundaries.
- Keep code-verification failures generic. OTP requests intentionally expose allowlist status to support the administrator-contact screen; do not expose any additional account data.
- Sanitize operational errors before returning or persisting them.
- Add route contract tests and database tests for new correctness rules.
