import os
import stat
import subprocess
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "opengpu-storage-init"
STUB = r'''#!/bin/bash
set -euo pipefail
cmd=$(basename "$0")
state=${OPENGPU_STUB_STATE:?}
mkdir -p "$state/loops"
touch "$state/mounted"
case "$cmd" in
  mkfs.ext4|resize2fs)
    exit 0
    ;;
  e2fsck)
    exit "${OPENGPU_E2FSCK_RC:-0}"
    ;;
  findmnt)
    target=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --mountpoint) target=$2; shift 2 ;;
        *) shift ;;
      esac
    done
    grep -Fxq "$target" "$state/mounted" 2>/dev/null
    ;;
  mount)
    dir=${*: -1}
    mkdir -p -- "$dir"
    grep -Fxq "$dir" "$state/mounted" 2>/dev/null || printf '%s\n' "$dir" >> "$state/mounted"
    ;;
  umount)
    dir=${*: -1}
    if [[ -d "$dir" ]]; then
      find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    fi
    if [[ -f "$state/mounted" ]]; then
      grep -Fxv "$dir" "$state/mounted" > "$state/mounted.next" || true
      mv "$state/mounted.next" "$state/mounted"
    fi
    ;;
  losetup)
    mkdir -p "$state/loops"
    if [[ "$1" == "--find" ]]; then
      img=${*: -1}
      n=0
      while [[ -e "$state/loops/loop$n" ]]; do
        n=$((n + 1))
      done
      printf '%s\n' "$img" > "$state/loops/loop$n"
      echo "/dev/loop$n"
      exit 0
    fi
    if [[ "$1" == "--detach" ]]; then
      dev=$(basename "$2")
      rm -f "$state/loops/$dev"
      exit 0
    fi
    if [[ "$1" == "-c" ]]; then
      exit 0
    fi
    img=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --associated) img=$2; shift 2 ;;
        *) shift ;;
      esac
    done
    if [[ -n "$img" ]]; then
      for loop_file in "$state/loops"/loop*; do
        [[ -f "$loop_file" ]] || continue
        if [[ "$(cat "$loop_file")" == "$img" ]]; then
          echo "/dev/$(basename "$loop_file")"
        fi
      done
    fi
    ;;
  *)
    echo "unexpected stub $cmd" >&2
    exit 1
    ;;
esac
'''


def _env(root: Path, stub_bin: Path, state: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENGPU_WORKSPACE_ROOT"] = str(root)
    env["OPENGPU_STUB_STATE"] = str(state)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    return env


def _stub_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "workspaces"
    stub_bin = tmp_path / "bin"
    state = tmp_path / "stub-state"
    stub_bin.mkdir()
    state.mkdir()
    for name in ("mkfs.ext4", "losetup", "mount", "umount", "findmnt", "resize2fs", "e2fsck"):
        path = stub_bin / name
        path.write_text(STUB)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return root, _env(root, stub_bin, state)


def _run(args: list[str], env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HELPER), *args],
        capture_output=True, text=True, env=env, check=check,
    )


def test_prepare_is_idempotent_and_teardown_removes_scratch(tmp_path):
    root, env = _stub_env(tmp_path)
    first = _run(["prepare", "7", "2", "3"], env)
    assert first.returncode == 0
    user = root / "users" / "7"
    assert (user / "workspace.img").stat().st_size == 2 * 1024 ** 3
    assert (user / "scratch.img").stat().st_size == 3 * 1024 ** 3
    assert (user / "ssh-host-keys").is_dir()
    assert (user / "scratch" / "home").is_dir()
    assert (user / "scratch" / "tmp").is_dir()
    assert (user / "scratch" / "etc").is_dir()
    assert (user / "scratch" / "etc").stat().st_mode & 0o777 == 0o755
    (user / "workspace" / "lost+found").mkdir()
    _run(["prepare", "7", "2", "3"], env)
    assert not (user / "workspace" / "lost+found").exists()
    second = _run(["prepare", "7", "2", "3"], env)
    assert second.returncode == 0
    _run(["release", "7"], env)
    assert not (user / "scratch.img").exists()
    assert (user / "workspace.img").exists()
    assert (user / "ssh-host-keys").is_dir()
    mounted = (tmp_path / "stub-state" / "mounted").read_text()
    assert str(user / "workspace") not in mounted.splitlines()
    assert str(user / "scratch") not in mounted.splitlines()


def test_prepare_grows_workspace_and_refuses_shrink(tmp_path):
    root, env = _stub_env(tmp_path)
    _run(["prepare", "8", "2", "1"], env)
    _run(["release", "8"], env)
    env["OPENGPU_E2FSCK_RC"] = "1"
    _run(["prepare", "8", "4", "1"], env)
    assert (root / "users" / "8" / "workspace.img").stat().st_size == 4 * 1024 ** 3
    failed = _run(["prepare", "8", "1", "1"], env, check=False)
    assert failed.returncode != 0
    assert "Refusing to shrink" in failed.stderr


def test_prepare_refuses_directory_convert_without_flag(tmp_path):
    root, env = _stub_env(tmp_path)
    workspace = root / "users" / "9" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "keep-me.txt").write_text("data")
    failed = _run(["prepare", "9", "2", "1"], env, check=False)
    assert failed.returncode != 0
    assert "convert" in failed.stderr
    converted = _run(["prepare", "9", "2", "1", "convert"], env)
    assert converted.returncode == 0
    assert (root / "users" / "9" / "workspace.img").is_file()


def test_prepare_rejects_invalid_argv(tmp_path):
    _root, env = _stub_env(tmp_path)
    bad = _run(["prepare", "0", "2", "3"], env, check=False)
    assert bad.returncode == 2
    missing = _run(["1", "2"], env, check=False)
    assert missing.returncode == 2
    over_cap = _run(["prepare", "5", "199", "199"], env, check=False)
    assert over_cap.returncode == 1
    assert "200 GB" in over_cap.stderr
