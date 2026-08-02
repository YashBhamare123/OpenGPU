# OpenGPU contributor guide

OpenGPU is a self-hosted GPU-reservation service. FastAPI serves the same-origin
web UI and owns authenticated, transactional reservation decisions; PostgreSQL is
the source of truth; `scheduler.py` reconciles those decisions into labelled Docker
GPU containers.

## Source map

- API and static frontend: `api.py`, `frontend/`
- Authentication: `security.py`
- Database and migrations: `database.py`, `postgres/`
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
python -m py_compile api.py admin.py config.py database.py mailer.py manager.py scheduler.py security.py
docker build --check .
```

Add the lowest-layer regression test that reproduces a bug; add database coverage
when correctness depends on constraints or concurrent transactions.
