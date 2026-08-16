import json
import os
import shutil
import subprocess
from pathlib import Path

from config import settings

TOKEN_KEYS = ("NGROK_AUTHTOKEN", "NGROK_TOKEN")


def ngrok_token() -> str:
    for name in TOKEN_KEYS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def parse_tcp_endpoint(chunk: str) -> tuple[str, int] | None:
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        url = ""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            if "tcp://" in line:
                url = line[line.index("tcp://"):].split()[0].rstrip(",\"'")
        else:
            url = str(payload.get("url") or payload.get("addr") or "")
            if not url and isinstance(payload.get("msg"), str) and "tcp://" in payload["msg"]:
                url = payload["msg"]
        if url.startswith("tcp://"):
            hostport = url.removeprefix("tcp://")
            host, port_text = hostport.rsplit(":", 1)
            return host, int(port_text)
    return None


def last_ngrok_error(chunk: str) -> str:
    last = ""
    for line in chunk.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            if "ERR_NGROK" in line:
                last = line.strip()
            continue
        err = str(payload.get("err") or "").strip()
        if err and err not in {"<nil>", "None"}:
            last = err.replace("\r", " ").strip()
    return last[:400]


def configure_agent(token: str) -> None:
    ngrok = shutil.which("ngrok")
    if ngrok is None:
        raise RuntimeError("ngrok is not on PATH; install it once, then rerun opengpu setup --token")
    result = subprocess.run(
        [ngrok, "config", "add-authtoken", token],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "ngrok config failed"
        raise RuntimeError(detail[:300])


def start_tunnel(port: int) -> subprocess.Popen[str]:
    ngrok = shutil.which("ngrok")
    if ngrok is None:
        raise RuntimeError("ngrok is not on PATH")
    command = [
        ngrok, "tcp", f"{settings.ssh_gateway_bind}:{port}",
        "--log", "stdout", "--log-format", "json",
    ]
    remote_addr = os.environ.get("NGROK_TCP_ADDR", "").strip()
    if remote_addr:
        command.extend(["--remote-addr", remote_addr])
    return subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def wait_for_endpoint(process: subprocess.Popen[str], timeout: float = 20) -> tuple[str, int]:
    if process.stdout is None:
        raise RuntimeError("ngrok is not logging to stdout")
    import time
    deadline = time.monotonic() + timeout
    buffered = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            rest = process.stdout.read() or ""
            detail = last_ngrok_error(buffered + rest) or "remote access tunnel exited before it became ready"
            raise RuntimeError(detail)
        ready = select_stdout(process, deadline - time.monotonic())
        if not ready:
            continue
        chunk = process.stdout.readline()
        if not chunk:
            continue
        buffered += chunk
        endpoint = parse_tcp_endpoint(buffered)
        if endpoint:
            return endpoint
    raise RuntimeError(last_ngrok_error(buffered) or "timed out waiting for the remote SSH endpoint")


def select_stdout(process: subprocess.Popen[str], timeout: float) -> bool:
    import select as select_mod
    if process.stdout is None:
        return False
    readable, _, _ = select_mod.select([process.stdout], [], [], max(timeout, 0))
    return bool(readable)


def persist_token(env_file: Path, token: str) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.is_file() else []
    replaced = False
    updated = []
    for line in lines:
        if any(line.startswith(f"{name}=") for name in TOKEN_KEYS):
            key = line.split("=", 1)[0]
            updated.append(f"{key}={token}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(f"NGROK_AUTHTOKEN={token}")
    env_file.write_text("\n".join(updated) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
