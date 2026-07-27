#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

CHECK_ONLY=false
BUILD_IMAGE=false
START_TUNNEL=false

usage() {
  cat <<'EOF'
Usage: ./start.sh [--check] [--build] [--tunnel]

  --check  Validate configuration and dependencies without starting services.
  --build  Rebuild the configured Docker image before starting.
  --tunnel Start the configured permanent ngrok HTTPS endpoint as well.
  --help   Show this help.

The script starts the API and scheduler together in the foreground. Press
Ctrl+C to stop both. Production systemd deployment should use deploy/*.service.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true ;;
    --build) BUILD_IMAGE=true ;;
    --tunnel) START_TUNNEL=true ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$START_TUNNEL" == true ]]; then
  if ! command -v ngrok >/dev/null 2>&1; then
    echo "Required command is missing: ngrok" >&2
    exit 1
  fi
  ngrok_domain="$(sed -n 's/^NGROK_DOMAIN=//p' .env | tail -n 1)"
  if [[ ! "$ngrok_domain" =~ ^[A-Za-z0-9.-]+\.ngrok-free\.(app|dev)$ ]]; then
    echo "NGROK_DOMAIN must be an assigned ngrok-free.app or ngrok-free.dev hostname." >&2
    exit 1
  fi
  if ! ngrok config check >/dev/null; then
    echo "ngrok is not configured. Run: ngrok config add-authtoken YOUR_TOKEN" >&2
    exit 1
  fi
  if ! grep -Fq "https://$ngrok_domain" .env; then
    echo "ALLOWED_ORIGINS must include https://$ngrok_domain" >&2
    exit 1
  fi
fi

if [[ ! -f .env ]]; then
  echo "Missing $PROJECT_DIR/.env. Copy .env.example and fill the required values." >&2
  exit 1
fi

env_mode="$(stat -c '%a' .env)"
if [[ "$env_mode" != "600" ]]; then
  echo "Refusing to use .env with mode $env_mode; run: chmod 600 $PROJECT_DIR/.env" >&2
  exit 1
fi

for command in python3 docker flock; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command is missing: $command" >&2
    exit 1
  fi
done

# One supervisor per checkout. The scheduler advisory lock separately prevents
# multiple schedulers across different checkouts or service managers.
exec 9>"$PROJECT_DIR/.start.lock"
if ! flock -n 9; then
  echo "Another start.sh instance is already running for this checkout." >&2
  exit 1
fi

echo "Checking configuration..."
python3 - <<'PY'
import os
from config import settings

required = (
    "DATABASE_URL", "SERVER_IP", "DOCKER_BIND_IP", "SMTP_HOST",
    "SMTP_PORT", "SMTP_FROM", "ALLOWED_ORIGINS", "COOKIE_SECURE",
)
missing = [name for name in required if not os.environ.get(name, "").strip()]
if settings.ssh_port_start < 1024 or settings.ssh_port_end > 65535:
    raise SystemExit("SSH port range must stay between 1024 and 65535")
if settings.ssh_port_start > settings.ssh_port_end:
    raise SystemExit("SSH_PORT_START must be less than or equal to SSH_PORT_END")
if missing:
    raise SystemExit("Missing required .env variables: " + ", ".join(missing))
if settings.cookie_secure and not all(origin.startswith("https://") for origin in settings.allowed_origins):
    raise SystemExit("COOKIE_SECURE=true requires HTTPS values in ALLOWED_ORIGINS")
print("Configuration: ok")
PY

workspace_root="$(python3 - <<'PY'
from config import settings
print(settings.workspace_root)
PY
)"
if [[ "$workspace_root" != /* ]]; then
  echo "WORKSPACE_ROOT must be an absolute path." >&2
  exit 1
fi
storage_helper="$(python3 - <<'PY'
from config import settings
print(settings.storage_helper)
PY
)"
if [[ "$storage_helper" != /* || ! -x "$storage_helper" ]]; then
  echo "STORAGE_HELPER must be an installed executable at an absolute path: $storage_helper" >&2
  exit 1
fi
if ! sudo -n -l "$storage_helper" 1 >/dev/null 2>&1; then
  echo "The scheduler cannot run STORAGE_HELPER without a password. Run: sudo ./scripts/install-storage-helper" >&2
  exit 1
fi
echo "Storage helper: ok ($workspace_root)"

echo "Checking PostgreSQL and hardened schema..."
python3 - <<'PY'
from database import get_connection

required_tables = {
    "teams", "reservations", "auth_challenges", "sessions",
    "provisioning_jobs", "audit_events", "service_heartbeats",
}
required_team_columns = {
    "ssh_password_hash", "provisioning_state", "volume_name", "legacy_volume",
}
with get_connection() as connection:
    tables = {
        row[0] for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )
    }
    columns = {
        row[0] for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='teams'"
        )
    }
missing_tables = sorted(required_tables - tables)
missing_columns = sorted(required_team_columns - columns)
if missing_tables or missing_columns:
    detail = []
    if missing_tables:
        detail.append("tables: " + ", ".join(missing_tables))
    if missing_columns:
        detail.append("teams columns: " + ", ".join(missing_columns))
    raise SystemExit(
        "Database is not migrated (missing " + "; ".join(detail) + "). "
        "Apply postgres/migrations/001_hardening.sql after taking a backup."
    )
print("PostgreSQL schema: ok")
PY

echo "Checking Docker access and image..."
if ! docker info >/dev/null 2>&1; then
  echo "Cannot access Docker. Run as the scheduler-capable user or add it to the docker group." >&2
  exit 1
fi

docker_image="$(python3 - <<'PY'
from config import settings
print(settings.docker_image)
PY
)"

if [[ "$BUILD_IMAGE" == true ]]; then
  echo "Building $docker_image..."
  docker build -t "$docker_image" .
fi

if ! docker image inspect "$docker_image" >/dev/null 2>&1; then
  echo "Docker image $docker_image is missing. Run: ./start.sh --build" >&2
  exit 1
fi
echo "Docker: ok ($docker_image)"

python3 -m py_compile \
  api.py admin.py config.py database.py mailer.py manager.py scheduler.py security.py

if [[ "$CHECK_ONLY" == true ]]; then
  echo "All checks passed."
  exit 0
fi

api_host="$(python3 - <<'PY'
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")
print(os.environ.get("API_HOST", "127.0.0.1"))
PY
)"
api_port="$(python3 - <<'PY'
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")
print(os.environ.get("API_PORT", "8000"))
PY
)"

api_pid=""
scheduler_pid=""
tunnel_pid=""

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping AIML GPU reservation services..."
  if [[ -n "$api_pid" ]] && kill -0 "$api_pid" 2>/dev/null; then
    kill -TERM "$api_pid" 2>/dev/null || true
  fi
  if [[ -n "$scheduler_pid" ]] && kill -0 "$scheduler_pid" 2>/dev/null; then
    kill -TERM "$scheduler_pid" 2>/dev/null || true
  fi
  if [[ -n "$tunnel_pid" ]] && kill -0 "$tunnel_pid" 2>/dev/null; then
    kill -TERM "$tunnel_pid" 2>/dev/null || true
  fi
  [[ -z "$api_pid" ]] || wait "$api_pid" 2>/dev/null || true
  [[ -z "$scheduler_pid" ]] || wait "$scheduler_pid" 2>/dev/null || true
  [[ -z "$tunnel_pid" ]] || wait "$tunnel_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting scheduler..."
python3 scheduler.py &
scheduler_pid=$!
sleep 1
if ! kill -0 "$scheduler_pid" 2>/dev/null; then
  wait "$scheduler_pid" || true
  echo "Scheduler failed to start. Check DATABASE_URL, Docker access, and whether another scheduler is active." >&2
  exit 1
fi

echo "Starting API on $api_host:$api_port..."
python3 -m uvicorn api:app --host "$api_host" --port "$api_port" &
api_pid=$!
sleep 1
if ! kill -0 "$api_pid" 2>/dev/null; then
  wait "$api_pid" || true
  echo "API failed to start. Check API_HOST/API_PORT and whether the port is already in use." >&2
  exit 1
fi

if [[ "$START_TUNNEL" == true ]]; then
  echo "Starting ngrok tunnel at https://$ngrok_domain..."
  ngrok http --url "https://$ngrok_domain" "http://$api_host:$api_port" --log stdout &
  tunnel_pid=$!
  sleep 2
  if ! kill -0 "$tunnel_pid" 2>/dev/null; then
    wait "$tunnel_pid" || true
    echo "ngrok failed to start. Check the account token and assigned domain." >&2
    exit 1
  fi
fi

echo
echo "AIML GPU reservation system is running."
echo "API: http://$api_host:$api_port"
if [[ "$START_TUNNEL" == true ]]; then
  echo "Public URL: https://$ngrok_domain"
fi
echo "Press Ctrl+C to stop both processes."

set +e
child_pids=("$api_pid" "$scheduler_pid")
if [[ -n "$tunnel_pid" ]]; then
  child_pids+=("$tunnel_pid")
fi
wait -n "${child_pids[@]}"
exit_code=$?
set -e

if kill -0 "$api_pid" 2>/dev/null && kill -0 "$scheduler_pid" 2>/dev/null; then
  echo "A child process exited unexpectedly." >&2
fi
exit "$exit_code"
