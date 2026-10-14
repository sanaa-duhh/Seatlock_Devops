import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .db import get_db
from .models import Audit, Event, Hold, Seat
from .schemas import EventInput, HoldCreate

app = FastAPI(title="SeatLock API", version="0.1.0")
logger = logging.getLogger("seatlock")
logging.basicConfig(level=logging.INFO, format="%(message)s")
REQUESTS = Counter("seatlock_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("seatlock_http_duration_seconds", "HTTP request duration", ["route"])
CONFLICTS = Counter("seatlock_seat_conflicts_total", "Rejected attempts to hold unavailable seats")
BOOKINGS = Counter("seatlock_bookings_confirmed_total", "Booking confirmations handled by this process")
COOKIE = "seatlock_session"
HOLD_SECONDS = int(os.getenv("HOLD_SECONDS", "300"))


def now():
    return datetime.now(UTC)


@app.middleware("http")
async def observe(request: Request, call_next):
    started = time.monotonic()
    request_id = uuid.uuid4().hex
    # A non-simple header blocks cross-site form attacks; no CORS origins are enabled.
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        if request.headers.get("x-seatlock-request") != "1":
            return Response(
                '{"detail":"Missing same-origin request header"}',
                status_code=403,
                media_type="application/json",
            )
        origin = request.headers.get("origin")
        allowed = os.getenv(
            "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173"
        ).split(",")
        if origin and origin not in allowed:
            return Response('{"detail":"Origin not allowed"}', status_code=403, media_type="application/json")
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "unmatched")
    duration = time.monotonic() - started
    if route not in {"/health", "/metrics"}:
        REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        LATENCY.labels(route).observe(duration)
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                }
            )
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def owner(request: Request):
    token = request.cookies.get(COOKIE)
    if not token or len(token) < 32 or len(token) > 128:
        raise HTTPException(401, "Start a browser session first")
    return hashlib.sha256(token.encode()).hexdigest()


def admin(request: Request):
    expected = os.getenv("ADMIN_TOKEN", "")
    supplied = request.headers.get("x-admin-token", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(403, "Organizer access required")


def event_or_404(db, event_id, lock=False):
    # Shared event locks allow concurrent buyers but serialize organizer edits.
    event = (
        db.scalar(select(Event).where(Event.id == event_id).with_for_update(read=True))
        if lock
        else db.get(Event, event_id)
    )
    if not event or not event.published:
        raise HTTPException(404, "Event not found")
    return event


def event_dict(event):
    return {
        name: getattr(event, name)
        for name in (
            "id",
            "slug",
            "title",
            "category",
            "venue",
            "city",
            "starts_at",
            "description",
            "theme",
            "price_paise",
        )
    }


def hold_dict(hold, event):
    state = "expired" if hold.status == "active" and hold.expires_at <= now() else hold.status
    return {
        "id": hold.id,
        "status": state,
        "expires_at": hold.expires_at,
        "created_at": hold.created_at,
        "reference": hold.reference,
        "total_paise": hold.total_paise,
        "seats": hold.seat_labels.split(","),
        "event": event_dict(event),
    }


def owned_hold(db, hold_id, identity):
    hold = db.scalar(select(Hold).where(Hold.id == hold_id, Hold.owner == identity).with_for_update())
    if not hold:
        raise HTTPException(404, "Reservation not found")
    return hold


def audit(db, hold, action):
    db.add(Audit(hold_id=hold.id, action=action, created_at=now()))


@app.get("/health")
def health():
    return {"status": "ok", "service": "seatlock", "version": os.getenv("APP_VERSION", "local")}


# Public through the Ingress (/api), so CI can confirm which commit is live after a GitOps sync.
@app.get("/api/version")
def version():
    return {"version": os.getenv("APP_VERSION", "local")}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SET LOCAL statement_timeout = '2000ms'"))
        db.execute(select(Event.id).limit(1))
        return {"status": "ready"}
    except SQLAlchemyError:
        raise HTTPException(503, "Database or schema unavailable") from None


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


@app.get("/api/session")
def session(request: Request, response: Response):
    existing = request.cookies.get(COOKIE, "")
    if not 32 <= len(existing) <= 128:
        response.set_cookie(
            COOKIE,
            secrets.token_urlsafe(32),
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
            samesite="strict",
            max_age=60 * 60 * 24 * 30,
        )
    return {"mode": "guest", "hold_seconds": HOLD_SECONDS, "checkout": "simulation"}


@app.get("/api/events")
def events(db: Session = Depends(get_db)):
    return [
        event_dict(e)
        for e in db.scalars(
            select(Event).where(Event.published.is_(True)).order_by(Event.starts_at).limit(100)
        )
    ]


@app.get("/api/events/{event_id}")
def event_detail(event_id: int, db: Session = Depends(get_db)):
    return event_dict(event_or_404(db, event_id))


@app.get("/api/events/{event_id}/seats")
def seats(event_id: int, request: Request, db: Session = Depends(get_db)):
    event_or_404(db, event_id)
    identity = hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()
    rows = db.execute(
        select(Seat, Hold)
        .outerjoin(Hold, Seat.hold_id == Hold.id)
        .where(Seat.event_id == event_id)
        .order_by(Seat.row, Seat.number)
    ).all()
    moment = now()
    result = []
    for seat, hold in rows:
        state = "available"
        if hold and hold.status == "confirmed":
            state = "booked"
        elif hold and hold.status == "active" and hold.expires_at > moment:
            state = "yours" if hold.owner == identity else "held"
        result.append(
            {
                "id": seat.id,
                "row": seat.row,
                "number": seat.number,
                "label": f"{seat.row}{seat.number}",
                "status": state,
            }
        )
    return {"seats": result, "server_time": moment}


@app.post("/api/holds", status_code=201)
def create_hold(payload: HoldCreate, identity: str = Depends(owner), db: Session = Depends(get_db)):
    event = event_or_404(db, payload.event_id, lock=True)
    if event.starts_at <= now():
        raise HTTPException(409, "Bookings have closed for this event")
    # All competing transactions lock seat rows in a stable order. PostgreSQL is required.
    locked = list(
        db.scalars(
            select(Seat)
            .where(Seat.event_id == event.id, Seat.id.in_(payload.seat_ids))
            .order_by(Seat.id)
            .with_for_update()
        )
    )
    if len(locked) != len(payload.seat_ids):
        raise HTTPException(422, "One or more seats do not belong to this event")
    moment = now()  # Evaluate expiration AFTER acquiring the locks.
    if event.starts_at <= moment:
        raise HTTPException(409, "Bookings have closed for this event")
    for seat in locked:
        prior = db.get(Hold, seat.hold_id) if seat.hold_id else None
        if prior and (
            prior.status == "confirmed" or (prior.status == "active" and prior.expires_at > moment)
        ):
            CONFLICTS.inc()
            raise HTTPException(409, "A selected seat was just taken. Choose another seat.")
    hold = Hold(
        id=str(uuid.uuid4()),
        event_id=event.id,
        owner=identity,
        status="active",
        created_at=moment,
        expires_at=moment + timedelta(seconds=HOLD_SECONDS),
        total_paise=event.price_paise * len(locked),
        seat_labels=",".join(f"{s.row}{s.number}" for s in locked),
    )
    db.add(hold)
    db.flush()
    for seat in locked:
        seat.hold_id = hold.id
    audit(db, hold, "held")
    db.commit()
    return hold_dict(hold, event)


@app.get("/api/holds/{hold_id}")
def get_hold(hold_id: str, identity: str = Depends(owner), db: Session = Depends(get_db)):
    hold = owned_hold(db, hold_id, identity)
    return hold_dict(hold, db.get(Event, hold.event_id))


@app.post("/api/holds/{hold_id}/confirm")
def confirm(hold_id: str, identity: str = Depends(owner), db: Session = Depends(get_db)):
    hold = owned_hold(db, hold_id, identity)
    if hold.status == "confirmed":  # Retry-safe confirmation.
        return hold_dict(hold, db.get(Event, hold.event_id))
    allocated = list(
        db.scalars(select(Seat).where(Seat.hold_id == hold.id).order_by(Seat.id).with_for_update())
    )
    if (
        hold.status != "active"
        or hold.expires_at <= now()
        or len(allocated) != len(hold.seat_labels.split(","))
    ):
        raise HTTPException(409, "This hold is no longer active. Please choose seats again.")
    hold.status = "confirmed"
    hold.confirmed_at = now()
    hold.reference = "SL-" + secrets.token_hex(6).upper()
    audit(db, hold, "confirmed")
    db.commit()
    BOOKINGS.inc()
    return hold_dict(hold, db.get(Event, hold.event_id))


@app.delete("/api/holds/{hold_id}", status_code=204)
def release(hold_id: str, identity: str = Depends(owner), db: Session = Depends(get_db)):
    hold = owned_hold(db, hold_id, identity)
    if hold.status == "confirmed":
        raise HTTPException(409, "Use booking cancellation for a confirmed ticket")
    if hold.status == "active":
        allocated = list(
            db.scalars(select(Seat).where(Seat.hold_id == hold.id).order_by(Seat.id).with_for_update())
        )
        for seat in allocated:
            seat.hold_id = None
        hold.status = "released"
        audit(db, hold, "released")
        db.commit()


@app.get("/api/bookings")
def bookings(identity: str = Depends(owner), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Hold, Event)
        .join(Event, Hold.event_id == Event.id)
        .where(Hold.owner == identity, Hold.status.in_(["confirmed", "cancelled"]))
        .order_by(Hold.created_at.desc())
        .limit(100)
    )
    return [hold_dict(hold, event) for hold, event in rows]


@app.post("/api/bookings/{hold_id}/cancel")
def cancel(hold_id: str, identity: str = Depends(owner), db: Session = Depends(get_db)):
    hold = owned_hold(db, hold_id, identity)
    event = db.get(Event, hold.event_id)
    if hold.status == "cancelled":
        return hold_dict(hold, event)
    if hold.status != "confirmed" or event.starts_at <= now():
        raise HTTPException(409, "This booking cannot be cancelled")
    allocated = list(
        db.scalars(select(Seat).where(Seat.hold_id == hold.id).order_by(Seat.id).with_for_update())
    )
    for seat in allocated:
        seat.hold_id = None
    hold.status = "cancelled"
    audit(db, hold, "cancelled")
    db.commit()
    return hold_dict(hold, event)


@app.post("/api/events", status_code=201, dependencies=[Depends(admin)])
def create_event(payload: EventInput, db: Session = Depends(get_db)):
    event = Event(**payload.model_dump())
    db.add(event)
    try:
        db.flush()
        for row in "ABCDEF":
            for number in range(1, 13):
                db.add(Seat(event_id=event.id, row=row, number=number))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An event with this slug already exists") from None
    return event_dict(event)


@app.put("/api/events/{event_id}", dependencies=[Depends(admin)])
def update_event(event_id: int, payload: EventInput, db: Session = Depends(get_db)):
    event = db.scalar(select(Event).where(Event.id == event_id).with_for_update())
    if not event:
        raise HTTPException(404, "Event not found")
    # Existing holds retain their price snapshot. Event identity/date are immutable once reserved.
    has_holds = db.scalar(select(func.count()).select_from(Hold).where(Hold.event_id == event_id))
    if has_holds and (payload.starts_at != event.starts_at or payload.title != event.title):
        raise HTTPException(409, "An event with reservations cannot be renamed or rescheduled")
    for key, value in payload.model_dump().items():
        setattr(event, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An event with this slug already exists") from None
    return event_dict(event)
