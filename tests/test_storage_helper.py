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
  mkfs.ext4|resize2fs|e2fsck)
    exit 0
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
    if [[ -f "$state/mounted" ]]; then
      grep -Fxv "$dir" "$state/mounted" > "$state/mounted.next" || true
      mv "$state/mounted.next" "$state/mounted"
    fi
    ;;
  losetup)
    if [[ "$1" == "--find" ]]; then
      img=${*: -1}
      printf '%s\n' "$img" > "$state/loops/loop0"
      echo /dev/loop0
      exit 0
    fi
    if [[ "$1" == "--detach" ]]; then
      rm -f "$state/loops/loop0"
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
    if [[ -n "$img" && -f "$state/loops/loop0" && "$(cat "$state/loops/loop0")" == "$img" ]]; then
      echo /dev/loop0
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
    second = _run(["prepare", "7", "2", "3"], env)
    assert second.returncode == 0
    _run(["teardown-scratch", "7"], env)
    assert not (user / "scratch.img").exists()
    assert (user / "workspace.img").exists()
    assert (user / "ssh-host-keys").is_dir()


def test_prepare_grows_workspace_and_refuses_shrink(tmp_path):
    root, env = _stub_env(tmp_path)
    _run(["prepare", "8", "2", "1"], env)
    _run(["prepare", "8", "4", "1"], env)
    assert (root / "users" / "8" / "workspace.img").stat().st_size == 4 * 1024 ** 3
    failed = _run(["prepare", "8", "1", "1"], env, check=False)
    assert failed.returncode != 0
    assert "Refusing to shrink" in failed.stderr


def test_prepare_rejects_invalid_argv(tmp_path):
    _root, env = _stub_env(tmp_path)
    bad = _run(["prepare", "0", "2", "3"], env, check=False)
    assert bad.returncode == 2
    missing = _run(["1", "2"], env, check=False)
    assert missing.returncode == 2
    over_cap = _run(["prepare", "5", "199", "199"], env, check=False)
    assert over_cap.returncode == 1
    assert "200 GB" in over_cap.stderr
