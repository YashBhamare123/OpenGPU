# OpenGPU

OpenGPU is a self-hosted reservation service for sharing one NVIDIA GPU over SSH. Approved users sign in with an emailed one-time code, inspect availability, reserve a session, and receive reservation-specific SSH credentials. PostgreSQL is the source of truth; a dedicated scheduler reconciles reservations into disposable Docker containers.

The current deployment profile is an NVIDIA A6000 with 48 GB VRAM, CUDA 12.8, 16 CPU cores, and 32 GB RAM per user container.

## What it does

- Email allowlist and one-time-code authentication
- View-only horizontal availability timeline
- Conflict-safe, idempotent reservations of up to three hours
- One current or future reservation per user
- Fresh SSH password for every reservation
- GPU container start and removal tied to reservation state
- Persistent bind-mounted `/workspace` and SSH host keys
- Audit events, provisioning retries, and scheduler health reporting
- CUDA 12.8 image with PyTorch and common ML tooling

## Architecture

```text
Browser ──HTTP──> FastAPI ──SQL──> PostgreSQL
                    │                  ▲
                    │                  │ desired state
                    └──SMTP            │
                                       │
                              Scheduler ──Docker──> GPU container
```

The API authenticates users and records reservations. It does not control Docker. The scheduler holds a PostgreSQL advisory lock, processes provisioning jobs, and reconciles labelled containers to active reservations. See [Architecture](docs/architecture.md).

## Contributor quick start

Requirements:

- Python 3.10+
- PostgreSQL 15+
- Docker Engine
- NVIDIA Container Toolkit and a compatible GPU for container smoke tests

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Create a disposable database whose name ends in `_test`, apply `postgres/init.sql`, and run:

```bash
TEST_MODE=true \
TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1/opengpu_test \
scripts/run-tests.sh
```

Without `TEST_DATABASE_URL`, database integration tests are skipped. Docker, SMTP, and GPU operations are mocked by the routine suite.

For a configured development host:

```bash
./start.sh --check
./start.sh --build
```

Use `./start.sh --tunnel` only when `NGROK_DOMAIN`, the ngrok account, and `ALLOWED_ORIGINS` are configured.

## Documentation

- [Architecture and lifecycle](docs/architecture.md)
- [Development guide](docs/development.md)
- [Frontend](docs/frontend.md)
- [Backend and API behavior](docs/backend.md)
- [HTTP API reference](docs/api.md)
- [Scheduler and containers](docs/scheduler-and-containers.md)
- [Database](docs/database.md)
- [Container image](docs/container-image.md)
- [Email](docs/email.md)
- [Deployment](docs/deployment.md)
- [Security model](docs/security.md)
- [Testing](docs/testing.md)

## Important boundaries

Only `/workspace` persists between reservations. The rest of a user container is deleted when its reservation ends or is cancelled. Workspace size and retention are not currently enforced.

OpenGPU assumes trusted institutional users. Containers grant their user passwordless sudo and are not a hostile multi-tenant isolation boundary. Keep the web service and SSH port range on an institutional LAN or VPN, terminate browser traffic with HTTPS, and never expose the Docker socket to the API process.

Some internal names retain the earlier `aiml-gpu-reservation` identifier for compatibility. Contributors should not rename Docker labels, database tables, or systemd units without a migration plan.
