import subprocess
from dataclasses import replace

import pytest

import manager


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
        (tmp_path / "users" / "42" / "ssh-host-keys").mkdir()
        (tmp_path / "users" / "42" / "ssh-host-keys").chmod(0o700)
    monkeypatch.setattr(manager.subprocess, "run", run_helper)
    workspace, host_keys, scratch_home, scratch_tmp = manager.prepare_user_storage(42)
    assert workspace == tmp_path / "users" / "42" / "workspace"
    assert host_keys == tmp_path / "users" / "42" / "ssh-host-keys"
    assert scratch_home == tmp_path / "users" / "42" / "scratch" / "home"
    assert scratch_tmp == tmp_path / "users" / "42" / "scratch" / "tmp"
    assert workspace.is_dir()
    assert host_keys.stat().st_mode & 0o777 == 0o700


def test_user_storage_paths_do_not_stat_root_owned_helper_output(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    monkeypatch.setattr(manager.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager.Path, "is_dir", lambda _self: pytest.fail("must not stat helper-owned paths"))

    workspace, host_keys, scratch_home, scratch_tmp = manager.prepare_user_storage(7)

    assert workspace == tmp_path / "users" / "7" / "workspace"
    assert host_keys == tmp_path / "users" / "7" / "ssh-host-keys"
    assert scratch_home == tmp_path / "users" / "7" / "scratch" / "home"
    assert scratch_tmp == tmp_path / "users" / "7" / "scratch" / "tmp"


def _storage_paths(tmp_path):
    return (
        tmp_path / "users" / "1" / "workspace",
        tmp_path / "users" / "1" / "ssh-host-keys",
        tmp_path / "users" / "1" / "scratch" / "home",
        tmp_path / "users" / "1" / "scratch" / "tmp",
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
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    events = []
    def prepare(_user_id, _workspace_gb=2, _temp_storage_gb=100):
        assert existing.removed
        events.append("prepare")
        return _storage_paths(tmp_path)
    monkeypatch.setattr(manager, "prepare_user_storage", prepare)

    result = manager.provision_user(1, "user@example.edu", "gpu1", 0, "gpu-user-1", "gpu-workspace-1")
    assert events == ["prepare"]
    assert existing.removed
    assert captured["environment"]["TEAM_PASSWORD_HASH"] == "$6$new-hash"
    assert captured["environment"]["WORKSPACE_GB"] == "2"
    assert captured["environment"]["TEMP_STORAGE_GB"] == "100"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "workspace")]["bind"] == "/workspace"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "ssh-host-keys")]["bind"] == "/etc/ssh/host_keys"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "scratch" / "home")]["bind"] == "/home/gpu1"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "scratch" / "tmp")]["bind"] == "/tmp"
    assert "storage_opt" not in captured
    assert captured["mem_limit"] == "32g"
    assert captured["nano_cpus"] == 16_000_000_000
    assert captured["pids_limit"] == 4096
    assert captured["shm_size"] == "16g"
    assert result == "$6$new-hash"


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

    def run_helper(command, **_kwargs):
        events.append(tuple(command[-4:]))

    monkeypatch.setattr(manager.subprocess, "run", run_helper)
    manager.start_container("gpu-user-3", 3, workspace_gb=4, temp_storage_gb=50)
    assert events == [("prepare", "3", "4", "50"), "start"]


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
    assert events == ["container", ("teardown-scratch", "9")]


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
