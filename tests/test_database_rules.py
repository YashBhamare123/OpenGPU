import os
import threading
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi import HTTPException

import api
from paths import postgres_path

TEST_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL is not configured")


@pytest.fixture(scope="module", autouse=True)
def safe_test_database():
    if not TEST_URL.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        pytest.fail("Refusing to use a database whose name does not end in _test")
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute(postgres_path("init.sql").read_text())
    yield
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE audit_events,provisioning_jobs,sessions,auth_challenges,reservations,teams RESTART IDENTITY CASCADE")


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_URL)
    connection.execute("TRUNCATE audit_events,provisioning_jobs,sessions,auth_challenges,reservations,teams RESTART IDENTITY CASCADE")
    connection.commit()
    yield connection
    connection.rollback()
    connection.close()


def user(conn, email="a@example.edu"):
    return conn.execute(
        "INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu1',%s,'ready') RETURNING id", (email,)
    ).fetchone()[0]


def test_admin_can_allowlist_a_new_user(monkeypatch, conn):
    conn.rollback()
    monkeypatch.setattr(api, "get_connection", lambda: psycopg.connect(TEST_URL))
    created = api.admin_whitelist_user(
        api.AdminUserRequest(email="new-user@iiti.ac.in", display_name="New User"),
        admin={"id": 999, "email": "mc240041040@iiti.ac.in"},
    )
    assert created["email"] == "new-user@iiti.ac.in"
    assert created["username"].startswith("gpu")
    assert created["enabled"] is True
    with psycopg.connect(TEST_URL) as check:
        assert check.execute(
            "SELECT display_name,enabled,provisioning_state FROM teams WHERE email=%s",
            ("new-user@iiti.ac.in",),
        ).fetchone() == ("New User", True, "unprovisioned")


def test_overlap_is_rejected(conn):
    first = user(conn)
    second = conn.execute(
        "INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu2','b@example.edu','ready') RETURNING id"
    ).fetchone()[0]
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    conn.execute("INSERT INTO reservations(team_id,start_time,end_time) VALUES (%s,%s,%s)",
                 (first, start, start + timedelta(hours=2)))
    with pytest.raises(psycopg.errors.ExclusionViolation):
        conn.execute("INSERT INTO reservations(team_id,start_time,end_time) VALUES (%s,%s,%s)",
                     (second, start + timedelta(minutes=30), start + timedelta(hours=2, minutes=30)))


def test_cancelled_slot_can_be_reused(conn):
    uid = user(conn)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    rid = conn.execute(
        "INSERT INTO reservations(team_id,start_time,end_time) VALUES (%s,%s,%s) RETURNING id",
        (uid, start, start + timedelta(hours=1)),
    ).fetchone()[0]
    conn.execute("UPDATE reservations SET cancelled=TRUE WHERE id=%s", (rid,))
    conn.execute("INSERT INTO reservations(team_id,start_time,end_time) VALUES (%s,%s,%s)",
                 (uid, start, start + timedelta(hours=1)))


def test_two_users_competing_for_one_slot_have_one_winner():
    with psycopg.connect(TEST_URL) as setup:
        setup.execute("TRUNCATE audit_events,provisioning_jobs,sessions,auth_challenges,reservations,teams RESTART IDENTITY CASCADE")
        first = setup.execute("INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu1','a@example.edu','ready') RETURNING id").fetchone()[0]
        second = setup.execute("INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu2','b@example.edu','ready') RETURNING id").fetchone()[0]
        setup.commit()
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    barrier = threading.Barrier(2)
    results = []

    def book(uid):
        connection = psycopg.connect(TEST_URL)
        try:
            barrier.wait()
            connection.execute("INSERT INTO reservations(team_id,start_time,end_time) VALUES (%s,%s,%s)",
                               (uid, start, start + timedelta(hours=1)))
            connection.commit()
            results.append("ok")
        except psycopg.Error:
            connection.rollback()
            results.append("conflict")
        finally:
            connection.close()

    threads = [threading.Thread(target=book, args=(uid,)) for uid in (first, second)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=10)
    assert sorted(results) == ["conflict", "ok"]


def test_immediate_idempotent_api_retry_returns_original_while_provisioning(monkeypatch):
    with psycopg.connect(TEST_URL) as setup:
        setup.execute("TRUNCATE audit_events,provisioning_jobs,sessions,auth_challenges,reservations,teams RESTART IDENTITY CASCADE")
        user_id = setup.execute(
            "INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu1','retry@example.edu','ready') RETURNING id"
        ).fetchone()[0]
        setup.commit()

    monkeypatch.setattr(api, "get_connection", lambda: psycopg.connect(TEST_URL))
    monkeypatch.setattr(api, "smtp_enabled", lambda: True)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=30))
    user = {"id": user_id}

    first = api.create_reservation(request, user=user, idempotency_key="retry-key-0001")
    retry = api.create_reservation(request, user=user, idempotency_key="retry-key-0001")

    assert retry == first
    with psycopg.connect(TEST_URL) as check:
        assert check.execute("SELECT provisioning_state FROM teams WHERE id=%s", (user_id,)).fetchone()[0] == "pending"
        assert check.execute("SELECT count(*) FROM reservations WHERE team_id=%s", (user_id,)).fetchone()[0] == 1

    different = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=45))
    with pytest.raises(HTTPException) as error:
        api.create_reservation(different, user=user, idempotency_key="retry-key-0001")
    assert error.value.status_code == 409


def test_first_reservation_provisions_environment_in_single_request(monkeypatch):
    with psycopg.connect(TEST_URL) as setup:
        setup.execute("TRUNCATE audit_events,provisioning_jobs,sessions,auth_challenges,reservations,teams RESTART IDENTITY CASCADE")
        user_id = setup.execute(
            "INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu1','first@example.edu','unprovisioned') RETURNING id"
        ).fetchone()[0]
        setup.commit()

    monkeypatch.setattr(api, "get_connection", lambda: psycopg.connect(TEST_URL))
    monkeypatch.setattr(api, "smtp_enabled", lambda: True)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=30))

    result = api.create_reservation(request, user={"id": user_id}, idempotency_key="first-click-0001")

    assert result["id"] > 0
    with psycopg.connect(TEST_URL) as check:
        assert check.execute("SELECT count(*) FROM reservations WHERE team_id=%s", (user_id,)).fetchone()[0] == 1
        assert check.execute("SELECT provisioning_state FROM teams WHERE id=%s", (user_id,)).fetchone()[0] == "pending"
        assert check.execute("SELECT purpose,state FROM provisioning_jobs WHERE team_id=%s", (user_id,)).fetchone() == ("reservation", "pending")


def _ed25519(comment="laptop"):
    import base64
    import struct
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + bytes(range(32))
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}"


def test_user_can_replace_and_clear_ssh_key(monkeypatch, conn):
    conn.rollback()
    user_id = conn.execute(
        "INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu1','keys@example.edu','ready') RETURNING id"
    ).fetchone()[0]
    conn.commit()
    monkeypatch.setattr(api, "get_connection", lambda: psycopg.connect(TEST_URL))
    first = api.set_my_ssh_key(api.SshKeyRequest(public_key=_ed25519("one")), user={"id": user_id})
    replaced = api.set_my_ssh_key(api.SshKeyRequest(public_key=_ed25519("two")), user={"id": user_id})
    assert first["comment"] == "one"
    assert replaced["comment"] == "two"
    assert replaced["fingerprint"].startswith("SHA256:")
    with psycopg.connect(TEST_URL) as check:
        stored = check.execute("SELECT ssh_public_key FROM teams WHERE id=%s", (user_id,)).fetchone()[0]
        assert stored.endswith(" two")
        assert check.execute(
            "SELECT event_type,details->>'fingerprint' FROM audit_events WHERE team_id=%s AND event_type='ssh_key_set' ORDER BY id",
            (user_id,),
        ).fetchall()[-1][1] == replaced["fingerprint"]
    api.clear_my_ssh_key(user={"id": user_id})
    with psycopg.connect(TEST_URL) as check:
        assert check.execute("SELECT ssh_public_key FROM teams WHERE id=%s", (user_id,)).fetchone()[0] is None
        assert check.execute(
            "SELECT count(*) FROM audit_events WHERE team_id=%s AND event_type='ssh_key_cleared'",
            (user_id,),
        ).fetchone()[0] == 1


def test_admin_can_set_another_users_ssh_key(monkeypatch, conn):
    conn.rollback()
    user_id = conn.execute(
        "INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu2','other@example.edu','ready') RETURNING id"
    ).fetchone()[0]
    conn.commit()
    monkeypatch.setattr(api, "get_connection", lambda: psycopg.connect(TEST_URL))
    admin = {"id": 999, "email": "mc240041040@iiti.ac.in"}
    view = api.admin_set_ssh_key(user_id, api.SshKeyRequest(public_key=_ed25519("admin")), admin=admin)
    assert view["comment"] == "admin"
    listed = api.admin_users(admin)
    match = next(row for row in listed if row["id"] == user_id)
    assert match["ssh_key"]["comment"] == "admin"
    api.admin_clear_ssh_key(user_id, admin=admin)
    with psycopg.connect(TEST_URL) as check:
        assert check.execute("SELECT ssh_public_key FROM teams WHERE id=%s", (user_id,)).fetchone()[0] is None
    with pytest.raises(HTTPException) as error:
        api.admin_set_ssh_key(user_id + 99, api.SshKeyRequest(public_key=_ed25519()), admin=admin)
    assert error.value.status_code == 404
