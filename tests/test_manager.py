import subprocess
from dataclasses import replace

import pytest

import manager


def test_fresh_ext4_mount_is_empty_for_volume_copy(tmp_path):
    (tmp_path / "lost+found").mkdir()
    assert manager.storage_destination_has_user_files(tmp_path) is False
    (tmp_path / "notes.txt").write_text("keep")
    assert manager.storage_destination_has_user_files(tmp_path) is True


def test_unmanaged_container_is_rejected(monkeypatch):
    foreign = type("Container", (), {"labels": {}, "name": "gpu-user-1"})()
    fake_client = type("Client", (), {"containers": type("Containers", (), {"get": lambda _self, _name: foreign})()})()
    monkeypatch.setattr(manager, "get_client", lambda: fake_client)
    with pytest.raises(RuntimeError, match="unmanaged"):
        manager._get_owned_container("gpu-user-1", 1)


def test_user_storage_paths_are_stable_and_created(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    def run_helper(command, **_kwargs):
        assert command[-4:] == ["prepare", "42", "2", "100"]
        (tmp_path / "users" / "42" / "workspace").mkdir(parents=True)
        (tmp_path / "users" / "42" / "scratch" / "home").mkdir(parents=True)
        (tmp_path / "users" / "42" / "scratch" / "tmp").mkdir()
        (tmp_path / "users" / "42" / "scratch" / "etc").mkdir()
        (tmp_path / "users" / "42" / "ssh-host-keys").mkdir()
        (tmp_path / "users" / "42" / "ssh-host-keys").chmod(0o700)
    monkeypatch.setattr(manager.subprocess, "run", run_helper)
    workspace, host_keys, scratch_home, scratch_tmp, scratch_etc = manager.prepare_user_storage(42)
    assert workspace == tmp_path / "users" / "42" / "workspace"
    assert host_keys == tmp_path / "users" / "42" / "ssh-host-keys"
    assert scratch_home == tmp_path / "users" / "42" / "scratch" / "home"
    assert scratch_tmp == tmp_path / "users" / "42" / "scratch" / "tmp"
    assert scratch_etc == tmp_path / "users" / "42" / "scratch" / "etc"
    assert workspace.is_dir()
    assert host_keys.stat().st_mode & 0o777 == 0o700


def test_user_storage_paths_do_not_stat_root_owned_helper_output(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    monkeypatch.setattr(manager.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager.Path, "is_dir", lambda _self: pytest.fail("must not stat helper-owned paths"))

    workspace, host_keys, scratch_home, scratch_tmp, scratch_etc = manager.prepare_user_storage(7)

    assert workspace == tmp_path / "users" / "7" / "workspace"
    assert host_keys == tmp_path / "users" / "7" / "ssh-host-keys"
    assert scratch_home == tmp_path / "users" / "7" / "scratch" / "home"
    assert scratch_tmp == tmp_path / "users" / "7" / "scratch" / "tmp"
    assert scratch_etc == tmp_path / "users" / "7" / "scratch" / "etc"


def _storage_paths(tmp_path):
    return (
        tmp_path / "users" / "1" / "workspace",
        tmp_path / "users" / "1" / "ssh-host-keys",
        tmp_path / "users" / "1" / "scratch" / "home",
        tmp_path / "users" / "1" / "scratch" / "tmp",
        tmp_path / "users" / "1" / "scratch" / "etc",
    )


def test_retry_recreates_container_before_emailing_new_password(monkeypatch, tmp_path):
    class Existing:
        def __init__(self):
            self.labels = {"app": manager.APP_LABEL, "aiml.user_id": "1"}
            self.status = "exited"
            self.removed = False
        def reload(self): pass
        def remove(self, force=False): self.removed = True

    existing = Existing()
    volume = type("Volume", (), {"attrs": {"Labels": existing.labels}})()
    created = type("Created", (), {"remove": lambda self, force=False: None})()
    captured = {}

    class Containers:
        def get(self, _name): return existing
        def create(self, **kwargs): captured.update(kwargs); return created

    fake = type("Client", (), {
        "containers": Containers(),
        "volumes": type("Volumes", (), {"get": lambda self, _name: volume})(),
    })()
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    monkeypatch.setattr(manager, "random_password", lambda: "new-password")
    monkeypatch.setattr(manager, "linux_password_hash", lambda _password: "$6$new-hash")
    monkeypatch.setattr(manager, "send_credentials", lambda *args: None)
    monkeypatch.setattr(manager.socket, "socket", lambda *args: type("Probe", (), {
        "__enter__": lambda self: self, "__exit__": lambda self, *args: None,
        "bind": lambda self, address: None,
    })())
    monkeypatch.setattr(
        manager,
        "settings",
        replace(
            manager.settings,
            workspace_root=str(tmp_path),
            memory_limit="32g",
            cpu_limit=16,
            shm_size="16g",
        ),
    )
    monkeypatch.setenv("CPU_ONLY", "false")
    events = []
    def prepare(_user_id, _workspace_gb=2, _temp_storage_gb=100, convert=False):
        assert existing.removed
        assert convert is True
        events.append("prepare")
        return _storage_paths(tmp_path)
    monkeypatch.setattr(manager, "prepare_user_storage", prepare)
    monkeypatch.setattr(manager, "seed_scratch_etc", lambda _path: events.append("seed"))

    result = manager.provision_user(1, "user@example.edu", "gpu1", 0, "gpu-user-1", "gpu-workspace-1")
    assert events == ["prepare", "seed"]
    assert existing.removed
    assert captured["environment"]["TEAM_PASSWORD_HASH"] == "$6$new-hash"
    assert captured["environment"]["WORKSPACE_GB"] == "2"
    assert captured["environment"]["TEMP_STORAGE_GB"] == "100"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "workspace")]["bind"] == "/workspace"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "ssh-host-keys")]["bind"] == "/etc/ssh/host_keys"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "scratch" / "home")]["bind"] == "/home/gpu1"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "scratch" / "tmp")]["bind"] == "/tmp"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "scratch" / "etc")]["bind"] == "/etc"
    assert captured["read_only"] is True
    assert captured["tmpfs"]["/run"] == "rw,nosuid,nodev,mode=755"
    assert "storage_opt" not in captured
    assert captured["mem_limit"] == "32g"
    assert captured["nano_cpus"] == 16_000_000_000
    assert captured["pids_limit"] == 4096
    assert captured["shm_size"] == "16g"
    assert captured["device_requests"]
    assert result == "$6$new-hash"


def test_cpu_only_omits_gpu_device_request(monkeypatch, tmp_path):
    captured = {}
    created = type("Created", (), {"remove": lambda self, force=False: None})()

    class Containers:
        def create(self, **kwargs):
            captured.update(kwargs)
            return created

    fake = type("Client", (), {"containers": Containers()})()
    monkeypatch.setenv("CPU_ONLY", "true")
    monkeypatch.setenv("DOCKER_IMAGE", "opengpu:cpu")
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    monkeypatch.setattr(manager, "random_password", lambda: "cpu-password")
    monkeypatch.setattr(manager, "linux_password_hash", lambda _password: "$6$cpu-hash")
    monkeypatch.setattr(manager, "send_credentials", lambda *args: None)
    monkeypatch.setattr(manager.socket, "socket", lambda *args: type("Probe", (), {
        "__enter__": lambda self: self, "__exit__": lambda self, *args: None,
        "bind": lambda self, address: None,
    })())
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    monkeypatch.setattr(manager, "prepare_user_storage", lambda *_args, **_kwargs: _storage_paths(tmp_path))
    monkeypatch.setattr(manager, "seed_scratch_etc", lambda _path: None)
    monkeypatch.setattr(manager, "_get_owned_container", lambda *_args, **_kwargs: None)

    result = manager.provision_user(1, "user@example.edu", "gpu1", 0, "gpu-user-1", "gpu-workspace-1")
    assert result == "$6$cpu-hash"
    assert captured["image"] == "opengpu:cpu"
    assert captured["device_requests"] == []


def test_managed_container_query_includes_stopped_containers(monkeypatch):
    captured = {}
    fake = type("Client", (), {
        "containers": type("Containers", (), {
            "list": lambda self, **kwargs: captured.update(kwargs) or [],
        })(),
    })()
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    manager.managed_containers()
    assert captured["all"] is True


def test_initial_provisioning_can_skip_credentials_email(monkeypatch, tmp_path):
    volume = type("Volume", (), {"attrs": {"Labels": {"app": manager.APP_LABEL, "aiml.user_id": "1"}}})()
    created = type("Created", (), {})()
    fake = type("Client", (), {
        "containers": type("Containers", (), {
            "get": lambda self, name: (_ for _ in ()).throw(manager.docker.errors.NotFound("missing")),
            "create": lambda self, **kwargs: created,
        })(),
        "volumes": type("Volumes", (), {"get": lambda self, name: volume})(),
    })()
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    monkeypatch.setattr(manager, "linux_password_hash", lambda password: "$6$hash")
    monkeypatch.setattr(manager, "send_credentials", lambda *args: pytest.fail("credentials should not be sent"))
    monkeypatch.setattr(manager.socket, "socket", lambda *args: type("Probe", (), {
        "__enter__": lambda self: self, "__exit__": lambda self, *args: None, "bind": lambda self, address: None,
    })())
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    monkeypatch.setattr(manager, "prepare_user_storage", lambda *_args, **_kwargs: _storage_paths(tmp_path))
    monkeypatch.setattr(manager, "seed_scratch_etc", lambda _path: None)

    result = manager.provision_user(
        1, "user@example.edu", "gpu1", 22001, "gpu-user-1", "gpu-workspace-1",
        email_credentials=False,
    )
    assert result == "$6$hash"


def test_start_container_prepares_storage_before_start(monkeypatch, tmp_path):
    events = []
    class Container:
        def __init__(self):
            self.labels = {"app": manager.APP_LABEL, "aiml.user_id": "3"}
        def start(self):
            events.append("start")
    fake = type("Client", (), {
        "containers": type("Containers", (), {"get": lambda self, _name: Container()})(),
    })()
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))

    monkeypatch.setattr(manager, "seed_scratch_etc", lambda _path: events.append("seed"))
    def run_helper(command, **_kwargs):
        events.append(tuple(command[-4:]))

    monkeypatch.setattr(manager.subprocess, "run", run_helper)
    manager.start_container("gpu-user-3", 3, workspace_gb=4, temp_storage_gb=50)
    assert events == [("prepare", "3", "4", "50"), "seed", "start"]


def test_remove_container_tears_down_scratch_after_remove(monkeypatch):
    events = []
    class Container:
        def __init__(self):
            self.labels = {"app": manager.APP_LABEL, "aiml.user_id": "9"}
            self.status = "exited"
        def reload(self): pass
        def remove(self): events.append("container")

    def run_helper(command, **_kwargs):
        events.append(tuple(command[-2:]))

    monkeypatch.setattr(manager.subprocess, "run", run_helper)
    manager.remove_container(Container())
    assert events == ["container", ("release", "9")]


def test_remove_container_retries_scratch_teardown(monkeypatch):
    attempts = {"n": 0}
    class Container:
        def __init__(self):
            self.labels = {"app": manager.APP_LABEL, "aiml.user_id": "9"}
            self.status = "exited"
        def reload(self): pass
        def remove(self): pass

    def run_helper(command, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(manager.subprocess, "run", run_helper)
    monkeypatch.setattr(manager.time, "sleep", lambda _seconds: None)
    manager.remove_container(Container())
    assert attempts["n"] == 2


def test_start_container_rejects_missing_container_before_prepare(monkeypatch):
    events = []
    fake = type("Client", (), {
        "containers": type("Containers", (), {
            "get": lambda self, _name: (_ for _ in ()).throw(manager.docker.errors.NotFound("missing")),
        })(),
    })()
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    monkeypatch.setattr(manager, "prepare_user_storage", lambda *_args, **_kwargs: events.append("prepare"))
    with pytest.raises(RuntimeError, match="missing"):
        manager.start_container("gpu-user-3", 3)
    assert events == []


def test_email_failure_releases_storage_through_remove_container(monkeypatch, tmp_path):
    events = []

    class Created:
        def __init__(self):
            self.labels = {"app": manager.APP_LABEL, "aiml.user_id": "1"}
            self.status = "created"
            self.name = "gpu-user-1"
        def reload(self): pass
        def remove(self, force=False): events.append("container")

    created = Created()
    fake = type("Client", (), {
        "containers": type("Containers", (), {
            "get": lambda self, _name: (_ for _ in ()).throw(manager.docker.errors.NotFound("missing")),
            "create": lambda self, **kwargs: created,
        })(),
    })()
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    monkeypatch.setattr(manager, "linux_password_hash", lambda _password: "$6$hash")
    monkeypatch.setattr(manager, "send_credentials", lambda *_args: (_ for _ in ()).throw(RuntimeError("smtp down")))
    monkeypatch.setattr(manager.socket, "socket", lambda *args: type("Probe", (), {
        "__enter__": lambda self: self, "__exit__": lambda self, *args: None,
        "bind": lambda self, address: None,
    })())
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    monkeypatch.setattr(manager, "prepare_user_storage", lambda *_args, **_kwargs: _storage_paths(tmp_path))
    monkeypatch.setattr(manager, "seed_scratch_etc", lambda _path: None)

    def run_helper(command, **_kwargs):
        events.append(tuple(command[-2:]))

    monkeypatch.setattr(manager.subprocess, "run", run_helper)
    with pytest.raises(RuntimeError, match="smtp down"):
        manager.provision_user(1, "user@example.edu", "gpu1", 22001, "gpu-user-1", "gpu-workspace-1")
    assert events == ["container", ("release", "1")]
