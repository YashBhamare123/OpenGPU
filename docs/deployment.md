# Deployment

This is a minimal deployment reference for contributors and small internal installations.

## Prerequisites

- Linux host with NVIDIA driver, Docker Engine, and NVIDIA Container Toolkit
- PostgreSQL 15 or newer with permission to create `btree_gist` and `citext`
- Python 3.10 or newer
- SMTP relay with STARTTLS
- Private network address for published SSH ports
- HTTPS reverse proxy, or configured ngrok tunnel for development
- Absolute `WORKSPACE_ROOT` with enough free space for sparse workspace and scratch images (loop mounts; XFS project quotas are not required)

## Configure

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Review every value in `.env`. Required settings are the database URL, advertised and bind addresses, SMTP sender/relay, allowed browser origins, secure-cookie policy, and the comma-separated `ADMIN_EMAILS` allowlist. `WORKSPACE_ROOT` must be an absolute path with room for per-user `workspace.img` and `scratch.img` files.

Install the storage helper and optional remote SSH token:

```bash
opengpu setup
opengpu setup --token "$NGROK_AUTHTOKEN"
opengpu migrate
opengpu doctor
opengpu serve
```

`setup` installs the storage helper, pulls `DOCKER_IMAGE` (default `yashbhamare123/opengpu:ml`) if it is not already local, and can store a remote SSH tunnel token. `migrate` applies `postgres/init.sql` to an empty database, records versions on a schema that already matches `init.sql`, or applies only unrecorded numbered upgrades. Rollback (`*_down.sql`) files are never applied automatically. `doctor` repeats the image pull if needed, then checks NVIDIA, SMTP, PostgreSQL, the helper, and workspace free space. It does not install NVIDIA or Docker and does not build the GPU image. `serve` starts the API, scheduler, local SSH gateway, and — when a tunnel token is configured — a remote TCP tunnel.

`scripts/configure-docker-storage-backend` is not required for these virtual-disk caps; it only forces Docker onto overlay2 and is optional. Reservations default to a 2 GB persistent workspace and 100 GB scratch disk for `/home`, `/tmp`, and a writable `/etc` copy; administrators can adjust both up to a combined 200 GB. The container root filesystem is read-only so users cannot fill the Docker overlay. The helper owns image creation and loop mounts; the scheduler account does not need general write access to `WORKSPACE_ROOT`.

Do not run the first directory-to-image `prepare ... convert` while a reservation container still exists. After upgrade, reinstall the helper before starting the scheduler.

You can still apply SQL by hand:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f postgres/init.sql
```

## GPU image

Hosts pull the published user image; they do not build it during setup:

```bash
docker pull yashbhamare123/opengpu:ml
```

`opengpu setup` and `opengpu doctor` do this using `DOCKER_IMAGE` (default `yashbhamare123/opengpu:ml`). Set that variable if you use another tag.

## Build and validate

Contributors changing the Dockerfile can still build locally:

```bash
docker build -t opengpu:ml .
./start.sh --check
```

The preflight verifies required configuration, database tables and columns, Docker access, image existence, passwordless access to the storage helper, and Python syntax. `./start.sh --check` runs `python -m cli doctor` for the host checks, then confirms `DOCKER_IMAGE` is present.

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
python -m cli admin whitelist person@example.edu --display-name "Person"
python -m cli admin list-users
python -m cli admin disable person@example.edu
python -m cli admin enable person@example.edu
python -m cli admin cancel 42 --reason "admin request"
python -m cli admin retry-provision person@example.edu
python -m cli admin rotate-password person@example.edu
```

Password rotation refuses to replace a running container. Disabling a user removes its container on the next reconciliation because disabled users are not retained.

Back up PostgreSQL and `WORKSPACE_ROOT`. Do not rely on user containers as backups: their writable filesystems are intentionally disposable. Keep the API and SSH port range behind institutional firewall or VPN controls.
