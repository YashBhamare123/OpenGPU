import pytest
from dataclasses import replace

import manager


def test_unmanaged_container_is_rejected(monkeypatch):
    foreign = type("Container", (), {"labels": {}, "name": "gpu-user-1"})()
    fake_client = type("Client", (), {"containers": type("Containers", (), {"get": lambda _self, _name: foreign})()})()
    monkeypatch.setattr(manager, "get_client", lambda: fake_client)
    with pytest.raises(RuntimeError, match="unmanaged"):
        manager._get_owned_container("gpu-user-1", 1)


def test_password_shape():
    password = manager.random_password()
    assert len(password) == 20
    assert password.isalnum()


def test_user_storage_paths_are_stable_and_created(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))
    workspace, host_keys = manager.user_storage_paths(42)
    assert workspace == tmp_path / "users" / "42" / "workspace"
    assert host_keys == tmp_path / "users" / "42" / "ssh-host-keys"
    assert workspace.is_dir()
    assert host_keys.stat().st_mode & 0o777 == 0o700


def test_retry_recreates_container_before_emailing_new_password(monkeypatch, tmp_path):
    class Existing:
        labels = {"app": manager.APP_LABEL, "aiml.user_id": "1"}
        status = "exited"
        removed = False
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
    monkeypatch.setattr(manager, "settings", replace(manager.settings, workspace_root=str(tmp_path)))

    result = manager.provision_user(1, "user@example.edu", "gpu1", 0, "gpu-user-1", "gpu-workspace-1")
    assert existing.removed
    assert captured["storage_opt"] == {"size": "16g"}
    assert captured["environment"]["TEAM_PASSWORD_HASH"] == "$6$new-hash"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "workspace")]["bind"] == "/workspace"
    assert captured["volumes"][str(tmp_path / "users" / "1" / "ssh-host-keys")]["bind"] == "/etc/ssh/host_keys"
    assert result == "$6$new-hash"


def test_verified_legacy_volume_is_accepted(monkeypatch):
    volume = type("Volume", (), {"attrs": {"Labels": {}}})()
    fake = type("Client", (), {
        "volumes": type("Volumes", (), {"get": lambda self, _name: volume})(),
    })()
    monkeypatch.setattr(manager, "get_client", lambda: fake)
    assert manager._get_owned_volume("legacy-workspace", 1, allow_legacy=True) is volume


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

    result = manager.provision_user(
        1, "user@example.edu", "gpu1", 22001, "gpu-user-1", "gpu-workspace-1",
        email_credentials=False,
    )
    assert result == "$6$hash"
