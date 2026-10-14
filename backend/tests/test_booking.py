import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from threading import Event as ThreadEvent

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event
from sqlalchemy import func, select, text

from app.db import SessionLocal, engine
from app.main import app
from app.models import Audit, Event, Hold, Seat


def reserve(client, seats=None):
    return client.post("/api/holds", json={"event_id": 1, "seat_ids": seats or [1]})


def test_health_and_readiness(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").json() == {"status": "ready"}


def test_version_reports_deployed_commit(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    assert client.get("/api/version").json() == {"version": "abc1234"}


def test_metrics(client):
    client.get("/api/events")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'route="/api/events"' in response.text


def test_session_cookie_is_private(client):
    with TestClient(app) as fresh:
        cookie = fresh.get("/api/session").headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie


def test_list_and_detail(client):
    assert len(client.get("/api/events").json()) == 1
    assert client.get("/api/events/1").json()["title"] == "Test Show"
    assert client.get("/api/events/999").status_code == 404


def test_seat_inventory(client):
    data = client.get("/api/events/1/seats").json()
    assert len(data["seats"]) == 8
    assert all(s["status"] == "available" for s in data["seats"])


def test_hold_changes_availability(client, other):
    response = reserve(client, [1, 2])
    assert response.status_code == 201
    assert response.json()["total_paise"] == 200000
    assert client.get("/api/events/1/seats").json()["seats"][0]["status"] == "yours"
    assert other.get("/api/events/1/seats").json()["seats"][0]["status"] == "held"


def test_conflict_is_all_or_nothing(client, other):
    reserve(client, [1])
    assert reserve(other, [1, 2]).status_code == 409
    assert reserve(other, [2]).status_code == 201


@pytest.mark.parametrize("seat_ids", [[], [1, 1], [999], [-1], list(range(1, 8))])
def test_invalid_selections(client, seat_ids):
    assert client.post("/api/holds", json={"event_id": 1, "seat_ids": seat_ids}).status_code == 422


def test_missing_event(client):
    assert client.post("/api/holds", json={"event_id": 99, "seat_ids": [1]}).status_code == 404


def test_expired_event_blocks_booking(client):
    with SessionLocal.begin() as db:
        db.get(Event, 1).starts_at = datetime.now(UTC) - timedelta(days=1)
    assert reserve(client).status_code == 409


def test_confirmation_retry_has_same_reference_and_one_audit(client):
    hold = reserve(client).json()
    first = client.post(f"/api/holds/{hold['id']}/confirm")
    second = client.post(f"/api/holds/{hold['id']}/confirm")
    assert first.status_code == second.status_code == 200
    assert first.json()["reference"] == second.json()["reference"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "confirmed")) == 1


def test_other_browser_cannot_access_or_confirm_hold(client, other):
    hold = reserve(client).json()
    assert other.get(f"/api/holds/{hold['id']}").status_code == 404
    assert other.post(f"/api/holds/{hold['id']}/confirm").status_code == 404
    assert other.delete(f"/api/holds/{hold['id']}").status_code == 404


def test_expired_hold_releases_inventory_without_worker(client, other):
    old = reserve(client).json()
    with SessionLocal.begin() as db:
        db.get(Hold, old["id"]).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert client.get(f"/api/holds/{old['id']}").json()["status"] == "expired"
    assert client.get("/api/events/1/seats").json()["seats"][0]["status"] == "available"
    assert reserve(other).status_code == 201
    assert client.post(f"/api/holds/{old['id']}/confirm").status_code == 409


def test_release_is_retry_safe(client, other):
    hold = reserve(client).json()
    assert client.delete(f"/api/holds/{hold['id']}").status_code == 204
    assert client.delete(f"/api/holds/{hold['id']}").status_code == 204
    assert reserve(other).status_code == 201


def test_cancellation_reopens_seats_and_retains_receipt(client, other):
    hold = reserve(client).json()
    client.post(f"/api/holds/{hold['id']}/confirm")
    assert reserve(other).status_code == 409
    assert client.delete(f"/api/holds/{hold['id']}").status_code == 409
    assert client.post(f"/api/bookings/{hold['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/bookings/{hold['id']}/cancel").status_code == 200
    assert client.get("/api/bookings").json()[0]["status"] == "cancelled"
    assert reserve(other).status_code == 201


def test_booking_history_private(client, other):
    hold = reserve(client).json()
    client.post(f"/api/holds/{hold['id']}/confirm")
    assert len(client.get("/api/bookings").json()) == 1
    assert other.get("/api/bookings").json() == []
    assert other.post(f"/api/bookings/{hold['id']}/cancel").status_code == 404


def test_csrf_header_and_origin(client):
    with TestClient(app) as unsafe:
        unsafe.get("/api/session")
        assert reserve(unsafe).status_code == 403
    assert (
        client.post(
            "/api/holds",
            headers={"Origin": "https://not-seatlock.invalid"},
            json={"event_id": 1, "seat_ids": [1]},
        ).status_code
        == 403
    )


def test_missing_session():
    with TestClient(app, headers={"X-Seatlock-Request": "1"}) as fresh:
        assert reserve(fresh).status_code == 401


def test_two_buyers_one_winner():
    barrier = Barrier(2)

    def buyer():
        with TestClient(app, headers={"X-Seatlock-Request": "1"}) as customer:
            customer.get("/api/session")
            barrier.wait(timeout=10)
            return reserve(customer).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: buyer(), range(2)))
    assert sorted(results) == [201, 409]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Hold)) == 1
        assert db.get(Seat, 1).hold_id is not None


def test_concurrent_confirm_is_idempotent(client):
    hold = reserve(client).json()
    cookie = client.cookies.get("seatlock_session")
    barrier = Barrier(2)

    def confirm():
        with TestClient(app, headers={"X-Seatlock-Request": "1"}) as browser:
            browser.cookies.set("seatlock_session", cookie)
            barrier.wait(timeout=10)
            return browser.post(f"/api/holds/{hold['id']}/confirm").json()["reference"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        references = list(pool.map(lambda _: confirm(), range(2)))
    assert references[0] == references[1]


def event_payload():
    return {
        "slug": "another-event",
        "title": "Another Show",
        "category": "Music",
        "venue": "Hall Two",
        "city": "Mumbai",
        "starts_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "description": "A fictional event for testing organizer controls.",
        "theme": "blue",
        "price_paise": 120000,
    }


def test_organizer_create_update_and_duplicate(client):
    payload = event_payload()
    assert client.post("/api/events", json=payload).status_code == 403
    headers = {"X-Admin-Token": "test-organizer-token"}
    response = client.post("/api/events", json=payload, headers=headers)
    assert response.status_code == 201
    event_id = response.json()["id"]
    assert len(client.get(f"/api/events/{event_id}/seats").json()["seats"]) == 72
    assert client.post("/api/events", json=payload, headers=headers).status_code == 409
    payload["description"] = "An updated fictional event description."
    assert client.put(f"/api/events/{event_id}", json=payload, headers=headers).status_code == 200


def test_price_is_snapshotted(client):
    hold = reserve(client).json()
    with SessionLocal.begin() as db:
        db.get(Event, 1).price_paise = 999900
    booking = client.post(f"/api/holds/{hold['id']}/confirm").json()
    assert booking["total_paise"] == 100000


def test_event_edit_cannot_race_a_waiting_reservation(client):
    """An organizer must see the reservation before renaming its event."""
    payload = client.get("/api/events/1").json()
    payload["title"] = "A Different Show"
    buyer_reached_seats = ThreadEvent()

    def reached_seat_query(connection, cursor, statement, parameters, context, executemany):
        if "FROM seats" in statement and "FOR UPDATE" in statement:
            buyer_reached_seats.set()

    def edit():
        with TestClient(
            app, headers={"X-Seatlock-Request": "1", "X-Admin-Token": "test-organizer-token"}
        ) as organizer:
            return organizer.put("/api/events/1", json=payload)

    # Hold a real seat lock so the buyer waits between reading the event and committing.
    blocker = SessionLocal()
    blocker.execute(select(Seat).where(Seat.id == 1).with_for_update())
    sql_event.listen(engine, "before_cursor_execute", reached_seat_query)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            buyer = pool.submit(reserve, client)
            try:
                assert buyer_reached_seats.wait(timeout=5)
                organizer = pool.submit(edit)
                deadline = time.monotonic() + 5
                while not organizer.done() and time.monotonic() < deadline:
                    with SessionLocal() as db:
                        waiting = db.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE wait_event_type = 'Lock' AND query LIKE '%FROM events%FOR UPDATE%'"
                            )
                        )
                    if waiting:
                        break
                    time.sleep(0.02)
            finally:
                blocker.rollback()
            assert buyer.result(timeout=5).status_code == 201
            assert organizer.result(timeout=5).status_code == 409
    finally:
        blocker.close()
        sql_event.remove(engine, "before_cursor_execute", reached_seat_query)


def test_event_closing_while_waiting_for_seats_rejects_hold(client, monkeypatch):
    import app.main as main

    with SessionLocal() as db:
        starts = db.get(Event, 1).starts_at
    moments = iter([starts - timedelta(seconds=1), starts + timedelta(seconds=1)])
    monkeypatch.setattr(main, "now", lambda: next(moments, starts + timedelta(seconds=1)))
    assert reserve(client).status_code == 409
