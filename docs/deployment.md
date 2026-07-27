# Deployment

This is a minimal deployment reference for contributors and small internal installations.

## Prerequisites

- Linux host with NVIDIA driver, Docker Engine, and NVIDIA Container Toolkit
- PostgreSQL 15 or newer with permission to create `btree_gist` and `citext`
- Python 3.10 or newer
- SMTP relay with STARTTLS
- Private network address for published SSH ports
- HTTPS reverse proxy, or configured ngrok tunnel for development
- XFS-backed Docker data root mounted with project quotas (`prjquota` or `pquota`)

## Configure

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Review every value in `.env`. Required settings are the database URL, advertised and bind addresses, SMTP sender/relay, allowed browser origins, and secure-cookie policy. `WORKSPACE_ROOT` must be an absolute path on the quota-enabled XFS mount.

Install the root-owned storage helper and its narrowly scoped sudo rule once:

```bash
sudo ./scripts/configure-docker-storage-backend
sudo ./scripts/install-storage-helper
```

The backend script disables Docker's containerd snapshotter so `overlay2` can enforce per-container `size` storage options on XFS. It restarts Docker and can make images from the other image store temporarily unavailable, so run it before building `opengpu:ml`. The default configuration gives each persistent workspace 1 GB and each disposable container writable layer 30 GB. The helper owns workspace creation; the scheduler account does not need general write access to `WORKSPACE_ROOT`.

For a fresh database, apply `postgres/init.sql`. Numbered migrations are for an existing schema and must be applied in order after a backup.

## Build and validate

```bash
docker build -t opengpu:ml .
./start.sh --check
```

The preflight verifies required configuration, database tables and columns, Docker access, image existence, passwordless access to the storage helper, and Python syntax.

## Run

```bash
./start.sh
```

For the configured development tunnel:

```bash
./start.sh --tunnel
```

The supervisor runs the API and scheduler together and stops all children if one exits. Production deployments may install the separate units in `deploy/`; the API service account should not belong to the Docker group, while the scheduler account requires Docker access and passwordless access only to the installed storage helper.

Verify:

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

Adjust the address if `API_HOST` is not localhost.

## Administration

```bash
python admin.py whitelist person@example.edu --display-name "Person"
python admin.py list-users
python admin.py disable person@example.edu
python admin.py enable person@example.edu
python admin.py cancel 42 --reason "admin request"
python admin.py retry-provision person@example.edu
python admin.py rotate-password person@example.edu
```

Password rotation refuses to replace a running container. Disabling a user removes its container on the next reconciliation because disabled users are not retained.

Back up PostgreSQL and `WORKSPACE_ROOT`. Do not rely on user containers as backups: their writable filesystems are intentionally disposable. Keep the API and SSH port range behind institutional firewall or VPN controls.
