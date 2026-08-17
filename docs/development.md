# Development Guide

## Setup

Create a virtual environment and install the control-plane dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
opengpu setup --skip-helper --skip-image
```

`opengpu setup` writes `.env`. It asks only for admin emails, optional SMTP, and the public contact address. CPU, memory, NVIDIA, ports, bind addresses, and browser origins are detected and stored without prompting. Optional variables accept `skip`. Use `--skip-env` to keep an existing file. `requirements-ml.txt` belongs to the GPU image and is not required for routine API or scheduler tests.

## Source map

| Area | Entry points |
|---|---|
| HTTP API and static frontend | `api.py`, `frontend/` |
| Authentication helpers | `security.py` |
| Database connection and schema | `database.py`, `postgres/` |
| Scheduler and desired state | `scheduler.py` |
| Docker provisioning | `manager.py`, `entrypoint.sh` |
| User image | `Dockerfile`, `Dockerfile.cpu`, `requirements-ml.txt` |
| Email | `mailer.py` |
| Administration | `admin.py`, `python -m cli admin` |
| Local CLI | `opengpu setup`, `opengpu migrate`, `opengpu doctor`, `opengpu serve`, `detect.py` |
| Asset paths | `paths.py` |
| Local supervision | `start.sh` |
| Production units | `deploy/` |
| Tests | `tests/`, `scripts/run-tests.sh` |

## Working locally

The frontend is served by FastAPI from `/`; it has no Node build step. With a configured PostgreSQL database and `.env`:

```bash
opengpu migrate
opengpu doctor
opengpu serve
```

`./start.sh --check` also runs `opengpu doctor` (via `python -m cli doctor`). `opengpu serve` runs the API, scheduler, and local SSH gateway together. Do not pass `--tunnel` unless you are testing remote SSH.

## Change boundaries

- Frontend changes must preserve same-origin cookie authentication and API error handling.
- API changes must keep reservation decisions transactional and must not gain Docker access.
- Scheduler changes must preserve advisory-lock leadership and label-based ownership checks.
- Database rule changes need both fresh-install SQL and an upgrade migration.
- Container changes must preserve workspace, scratch, and host-key mounts, one-GPU allocation, unique reservation credentials, and a read-only container root.
- Email code must never log or retain OTPs or plaintext SSH passwords.

Run the tests described in [Testing](testing.md) before submitting a change. Add regression coverage at the lowest layer that can reproduce a bug, and add database coverage whenever correctness depends on constraints or concurrent transactions.

## Debugging map

- Login failure: inspect SMTP configuration and `auth_challenges`. Do not log codes. When SMTP is skipped, admin codes print only on the `opengpu serve` terminal.
- Booking conflict: inspect active `reservations` and database constraint errors.
- Provisioning failure: inspect `provisioning_jobs.last_error`, team state, scheduler heartbeat, and Docker labels.
- Container did not start: compare the active reservation, `teams.container_name`, container status, and scheduler audit events.
- SSH fingerprint warning: confirm the user's `ssh-host-keys` directory survived recreation.
- Blank timeline: verify `/reservations`, browser authentication, and frontend console/network errors.

Do not test destructive cleanup against a production reservation or production database.
