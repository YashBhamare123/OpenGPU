from types import SimpleNamespace

import scheduler


class FakeContainer:
    def __init__(self, name):
        self.name = name
        self.labels = {"aiml.user_id": name.rsplit("-", 1)[-1]}
        self.status = "running"

    def reload(self): pass

    def stop(self, timeout=15):
        self.status = "exited"


def test_reconcile_stops_old_before_starting_new(monkeypatch):
    events = []
    old = FakeContainer("gpu-user-1")
    monkeypatch.setattr(scheduler, "desired_container", lambda: (2, "gpu-user-2"))
    monkeypatch.setattr(scheduler, "retained_container_names", lambda: {"gpu-user-1", "gpu-user-2"})
    monkeypatch.setattr(scheduler, "managed_containers", lambda: [old])
    monkeypatch.setattr(old, "stop", lambda timeout=15: events.append(("stop", old.name)))
    monkeypatch.setattr(scheduler, "start_container", lambda n, i: events.append(("start", n, i)))
    monkeypatch.setattr(scheduler, "record_transition", lambda *args: None)
    scheduler.reconcile()
    assert events == [("stop", "gpu-user-1"), ("start", "gpu-user-2", 2)]


def test_reconcile_never_stops_when_desired_is_already_running(monkeypatch):
    events = []
    current = FakeContainer("gpu-user-2")
    monkeypatch.setattr(scheduler, "desired_container", lambda: (2, "gpu-user-2"))
    monkeypatch.setattr(scheduler, "retained_container_names", lambda: {"gpu-user-2"})
    monkeypatch.setattr(scheduler, "managed_containers", lambda: [current])
    monkeypatch.setattr(scheduler, "start_container", lambda n, i: events.append("start"))
    monkeypatch.setattr(scheduler, "record_transition", lambda *args: None)
    scheduler.reconcile()
    assert events == []


def test_reconcile_removes_all_managed_containers_without_booking(monkeypatch):
    events = []
    running = [FakeContainer("gpu-user-1"), FakeContainer("gpu-user-2")]
    monkeypatch.setattr(scheduler, "desired_container", lambda: None)
    monkeypatch.setattr(scheduler, "retained_container_names", lambda: set())
    monkeypatch.setattr(scheduler, "managed_containers", lambda: running)
    monkeypatch.setattr(scheduler, "remove_container", lambda c: events.append(c.name))
    monkeypatch.setattr(scheduler, "record_transition", lambda *args: None)
    scheduler.reconcile()
    assert events == ["gpu-user-1", "gpu-user-2"]


def test_reconcile_keeps_stopped_container_for_future_reservation(monkeypatch):
    future = FakeContainer("gpu-user-3")
    future.status = "exited"
    events = []
    monkeypatch.setattr(scheduler, "desired_container", lambda: None)
    monkeypatch.setattr(scheduler, "retained_container_names", lambda: {"gpu-user-3"})
    monkeypatch.setattr(scheduler, "managed_containers", lambda: [future])
    monkeypatch.setattr(scheduler, "remove_container", lambda c: events.append("remove"))
    monkeypatch.setattr(scheduler, "start_container", lambda n, i: events.append("start"))
    monkeypatch.setattr(scheduler, "record_transition", lambda *args: None)
    scheduler.reconcile()
    assert events == []
