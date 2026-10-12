"""Create explicitly fictional upcoming events; safe to run more than once."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from .db import SessionLocal
from .models import Event, Seat

EVENTS = [
    (
        "after-hours",
        "After Hours",
        "Music",
        "The Courtyard",
        "Bengaluru",
        14,
        149900,
        "violet",
        "An intimate evening of indie sounds, late-night grooves, and a room full of people who get it. Find your spot and let the city fade out.",
    ),
    (
        "funny-business",
        "Funny Business",
        "Comedy",
        "Studio 12",
        "Bengaluru",
        18,
        79900,
        "orange",
        "Big laughs. Small room. An unfiltered stand-up showcase featuring fresh voices and unexpected punchlines.",
    ),
    (
        "the-last-act",
        "The Last Act",
        "Theatre",
        "Rangashala",
        "Mumbai",
        21,
        99900,
        "green",
        "One stage, four strangers, and an evening that changes everything. A contemporary play about the stories we choose to tell.",
    ),
    (
        "ideas-after-dark",
        "Ideas After Dark",
        "Talks",
        "The Assembly",
        "Bengaluru",
        25,
        49900,
        "blue",
        "Curious people. Unexpected conversations. An evening of short talks on design, technology, and the things in between.",
    ),
]


def seed():
    with SessionLocal.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(734812)"))
        for slug, title, category, venue, city, days, price, theme, description in EVENTS:
            if db.scalar(select(Event.id).where(Event.slug == slug)):
                continue
            date = (datetime.now(UTC) + timedelta(days=days)).replace(
                hour=13, minute=30, second=0, microsecond=0
            )
            event = Event(
                slug=slug,
                title=title,
                category=category,
                venue=venue,
                city=city,
                starts_at=date,
                price_paise=price,
                theme=theme,
                description=description,
                published=True,
            )
            db.add(event)
            db.flush()
            db.add_all([Seat(event_id=event.id, row=row, number=n) for row in "ABCDEF" for n in range(1, 13)])


if __name__ == "__main__":
    seed()
