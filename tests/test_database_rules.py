import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from fastapi import HTTPException

import api


TEST_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL is not configured")


@pytest.fixture(scope="module", autouse=True)
def safe_test_database():
    if not TEST_URL.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        pytest.fail("Refusing to use a database whose name does not end in _test")
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute(Path("postgres/init.sql").read_text())
    yield
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE audit_events,provisioning_jobs,sessions,auth_challenges,reservations,teams RESTART IDENTITY CASCADE")


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_URL)
    connection.execute("TRUNCATE audit_events,provisioning_jobs,sessions,auth_challenges,reservations,teams RESTART IDENTITY CASCADE")
    yield connection
    connection.rollback()
    connection.close()


def user(conn, email="a@example.edu"):
    return conn.execute(
        "INSERT INTO teams(name,email,provisioning_state) VALUES ('gpu1',%s,'ready') RETURNING id", (email,)
    ).fetchone()[0]


def test_valid_and_overlong_reservations(conn):
    uid = user(conn)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    conn.execute("INSERT INTO reservations(team_id,start_time,end_time) VALUES (%s,%s,%s)",
                 (uid, start, start + timedelta(hours=3)))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO reservations(team_id,start_time,end_time,cancelled) VALUES (%s,%s,%s,TRUE)",
                     (uid, start + timedelta(hours=4), start + timedelta(hours=8)))


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
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=30))

    result = api.create_reservation(request, user={"id": user_id}, idempotency_key="first-click-0001")

    assert result["id"] > 0
    with psycopg.connect(TEST_URL) as check:
        assert check.execute("SELECT count(*) FROM reservations WHERE team_id=%s", (user_id,)).fetchone()[0] == 1
        assert check.execute("SELECT provisioning_state FROM teams WHERE id=%s", (user_id,)).fetchone()[0] == "pending"
        assert check.execute("SELECT purpose,state FROM provisioning_jobs WHERE team_id=%s", (user_id,)).fetchone() == ("reservation", "pending")
