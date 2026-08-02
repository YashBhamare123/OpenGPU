# HTTP API

OpenGPU serves JSON endpoints and the static frontend from one origin. Authenticated calls use the `session` cookie; there is no bearer-token API.

## Authentication

### `POST /auth/request-code`

```json
{"email": "person@example.edu"}
```

Returns `202` with `approved` and the public `ACCESS_CONTACT_EMAIL` as `admin_contact`. Approved users receive a code and are limited to five generated challenges per hour; unapproved users are directed to the public contact by the frontend. Private `ADMIN_EMAILS` values are never returned.

### `POST /auth/verify-code`

```json
{"email": "person@example.edu", "code": "123456"}
```

Returns `200` and sets the session cookie, or `401` for an invalid, exhausted, or expired challenge.

### `POST /auth/logout`

Revokes the current session when present, deletes the cookie, and returns `204`.

## User and availability

### `GET /me`

Returns the authenticated user's ID, email, generated SSH username, display name, provisioning state, and `is_admin` flag. Returns `401` without a valid enabled session.

### `GET /reservations`

Returns every non-cancelled reservation whose end is in the future:

```json
[{"id": 42, "mine": true, "start_time": "2026-07-27T10:00:00Z", "end_time": "2026-07-27T11:00:00Z"}]
```

For another user's reservation, `id` is `null` and `mine` is `false`.

## Reservations

### `POST /reservations`

Required header:

```text
Idempotency-Key: at-least-8-characters
```

Body timestamps must contain timezone offsets:

```json
{"start_time": "2026-07-27T15:30:00+05:30", "end_time": "2026-07-27T16:30:00+05:30"}
```

Responses:

- `200`: reservation created or an identical request replayed
- `202`: account provisioning queued; no reservation was created
- `400`: invalid time ordering or duration
- `401`: authentication required
- `403`: user disabled
- `409`: overlap, second booking, conflicting idempotency reuse, or another database conflict
- `422`: malformed input, missing timezone, or invalid header length

### `DELETE /reservations/{id}`

Cancels the authenticated user's active or future reservation and returns `204`. Returns `404` when the reservation is missing, expired, cancelled, or belongs to someone else.

## Administration

Admin endpoints require a valid session whose normalized email is listed in `ADMIN_EMAILS`.

- `GET /admin` serves the administration page.
- `GET /admin/users` lists users and their enabled state; the booking UI offers enabled users.
- `POST /admin/users` allowlists a new email and optional display name, or safely re-enables a disabled account. Already-enabled emails return `409`.
- `GET /admin/reservations` lists current and future reservations with owner details and full IDs.
- `POST /admin/reservations` books for the `email` supplied in the request. Its `allow_extended` flag must be `true` above `RESERVATION_LIMIT_MINUTES`; the admin frontend calculates this flag from the configured limit without exposing a toggle.
- `DELETE /admin/reservations/{id}` cancels any current or future reservation.

Admin creation and cancellation actions record the acting administrator in audit-event details. Overlap protection, enabled-user checks, timezone requirements, idempotency, and the one-current-or-future-reservation rule continue to apply.

## Health and frontend

- `GET /` returns the web application.
- `GET /admin` returns the admin application; its management APIs remain authorization protected.
- `GET /health/live` returns `{"status":"ok"}`.
- `GET /health/ready` returns readiness details or `503` for a stale/degraded scheduler.

For state-changing browser requests, an Origin outside `ALLOWED_ORIGINS` receives `403` when origin enforcement is configured.
