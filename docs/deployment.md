# Deployment

This is a minimal deployment reference for contributors and small internal installations.

## Prerequisites

- Linux host with Docker Engine. NVIDIA driver and NVIDIA Container Toolkit are required for GPU reservations; `opengpu doctor` can switch the host to CPU-only mode instead.
- PostgreSQL 15 or newer with permission to create `btree_gist` and `citext`
- Python 3.10 or newer
- SMTP relay with STARTTLS for Lab mode, or Tailscale for Personal mode
- Private network address for published SSH ports
- HTTPS reverse proxy, or configured ngrok tunnel for development
- Absolute `WORKSPACE_ROOT` with enough free space for sparse workspace and scratch images (loop mounts; XFS project quotas are not required)

## Configure

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
opengpu setup
opengpu migrate
opengpu doctor
opengpu serve
```

`opengpu setup` writes a mode-600 `.env`. Each question is a separate page with the OpenGPU wordmark at the top. Choose Lab vs Personal, SMTP, HTTPS cookies, and GPU vs CPU from numbered options; host CPU, memory, ports, bind addresses, and browser origins are detected automatically. After upgrade, run `opengpu migrate` so `teams.handle` and `share_claims` exist before `opengpu doctor` or the API start.

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

`opengpu setup` and `opengpu doctor` do this using `DOCKER_IMAGE` (default `yashbhamare123/opengpu:ml`). Set `CPU_ONLY=true` or pass `--cpu` to pull `yashbhamare123/opengpu:cpu` instead. Set `DOCKER_IMAGE` if you use another tag.

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

For remote SSH, set `NGROK_AUTHTOKEN` or `NGROK_TOKEN` and run `opengpu serve --tunnel`. `./start.sh --tunnel` still only publishes the web UI on `NGROK_DOMAIN`; include that hostname in `ALLOWED_ORIGINS`.

Verify:

```bash
curl -fsS http://127.0.0.1:9473/health/live
curl -fsS http://127.0.0.1:9473/health/ready
```

Adjust the address if `API_HOST` is not localhost. The default API port is `9473` and the SSH gateway is `9474`; setup picks the next free port if either is taken.

## systemd

`deploy/aiml-gpu-api.service` and `deploy/aiml-gpu-scheduler.service` are the production split:

- The API unit runs `opengpu api` (FastAPI plus the SSH gateway). That process has no Docker access and must not start the scheduler.
- The scheduler unit runs `opengpu scheduler` as the Docker-capable account.
- `opengpu serve` remains the local all-in-one command (API, scheduler, and gateway in one process). Do not point the API unit at `serve`, or the two units will contest the scheduler advisory lock.

The API unit listens on `127.0.0.1:9473`. Point the reverse proxy or Tailscale Funnel at that port, and keep `API_PORT=9473` in the environment file. Existing installs that still proxy port `8000` should change the unit `--port` or the proxy together.

## Administration

```bash
python -m cli admin whitelist person@example.edu --display-name "Person"
python -m cli admin list-users
python -m cli admin disable person@example.edu
python -m cli admin enable person@example.edu
python -m cli admin cancel 42 --reason "admin request"
python -m cli admin retry-provision person@example.edu
python -m cli admin rotate-password person@example.edu
python -m cli admin set-ssh-key person@example.edu --file ~/.ssh/id_ed25519.pub
python -m cli admin show-ssh-key person@example.edu
python -m cli admin clear-ssh-key person@example.edu
```

Password rotation refuses to replace a running container. Disabling a user removes its container on the next reconciliation because disabled users are not retained.

Back up PostgreSQL and `WORKSPACE_ROOT`. Do not rely on user containers as backups: their writable filesystems are intentionally disposable. Keep the API and SSH port range behind institutional firewall or VPN controls.
