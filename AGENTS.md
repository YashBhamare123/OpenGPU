# OpenGPU contributor guide

OpenGPU is a self-hosted GPU-reservation service. FastAPI serves the same-origin
web UI and owns authenticated, transactional reservation decisions; PostgreSQL is
the source of truth; `scheduler.py` reconciles those decisions into labelled Docker
GPU containers.

## Source map

- API and static frontend: `api.py`, `frontend/`
- Authentication: `security.py`
- Database and migrations: `database.py`, `migrate.py`, `postgres/`
- Scheduling and provisioning: `scheduler.py`, `manager.py`
- User image and container startup: `Dockerfile`, `entrypoint.sh`
- Email, administration, and local supervision: `mailer.py`, `admin.py`, `start.sh`
- Deployment and tests: `deploy/`, `tests/`, `scripts/run-tests.sh`

Read `docs/development.md` and the relevant focused document in `docs/` before
changing a subsystem.

## Non-negotiable boundaries

- Keep API code free of Docker access. Docker lifecycle operations belong to the
  scheduler/manager path.
- Preserve the scheduler's PostgreSQL advisory-lock leadership and label-based
  container ownership checks.
- Keep reservation decisions transactional. Database constraints are authoritative
  for overlap, time, and user-booking rules.
- Database rule changes require both `postgres/init.sql` and an ordered upgrade
  migration (with a matching down migration where this repository uses one).
- Preserve the per-user `/workspace` and SSH host-key mounts, one-GPU allocation,
  and per-reservation SSH credentials. Only `/workspace` persists after a session.
- Never log or retain OTPs, plaintext passwords, or secrets.

## Working safely

- The working tree may contain unrelated user changes. Preserve them and avoid
  broad formatting or cleanup.
- Do not perform destructive database, container, or workspace cleanup against a
  production system. Never run lifecycle or GPU smoke tests while another user's
  reservation is active.
- Keep same-origin cookie authentication and frontend API error handling intact.
- Do not rename compatibility identifiers such as Docker labels, database tables,
  or systemd units without a migration plan.

## Core Architecture & Context Maps

To prevent reading large files repeatedly, refer to this reference context:

### 1. Database Schema (`postgres/init.sql`)
- **`teams`**: Represents users. Fields: `id`, `email`, `ssh_port`, `container_name`, `volume_name`, `provisioning_state`.
- **`reservations`**: Tracks GPU bookings. Fields: `team_id`, `start_time`, `end_time`, `workspace_gb`, `temp_storage_gb`.
  - Constraints: `end_time > start_time`, storage limits, and a GIST constraint `no_overlapping_reservations`.
- **`provisioning_jobs`**: Async tasks for scheduler (states: `pending`, `running`, `done`, `failed`).

### 2. API Routes Map (`api.py`)
- **Auth**: `/auth/request-code`, `/auth/verify-code`, `/auth/logout`
- **User**: `/me`, `/reservations` (GET/POST/DELETE)
- **Admin**: `/admin/users` (GET/POST), `/admin/reservations` (GET/POST/DELETE)
- **Health**: `/health/live`, `/health/ready`

### 3. Docker Context (`manager.py`, `scheduler.py`)
- Containers are identified using labels: `app=aiml-gpu-reservation` and `aiml.user_id=<team_id>`.
- Workspaces map the user's `volume_name` to `/workspace` inside the container.

## Token efficiency

- Use line ranges when viewing large files to avoid reading unneeded context.
- Use targeted searches instead of sweeping workspace searches.
- Apply minimal, precise edits rather than overwriting whole files or making cosmetic changes.
- Ensure terminal commands are quiet or paginated to limit context pollution.

## Validation

Run the routine suite before handing off a change:

```bash
TEST_MODE=true scripts/run-tests.sh
```

For database integration tests, use only a disposable database whose name ends in
`_test`:

```bash
TEST_MODE=true TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1/opengpu_test scripts/run-tests.sh
```

For relevant static checks:

```bash
bash -n start.sh entrypoint.sh scripts/run-tests.sh
python -m py_compile api.py admin.py cli.py config.py database.py envfile.py gateway.py host.py localdb.py mailer.py manager.py migrate.py paths.py scheduler.py security.py tunnel.py
docker build --check .
```

Add the lowest-layer regression test that reproduces a bug; add database coverage
when correctness depends on constraints or concurrent transactions.
