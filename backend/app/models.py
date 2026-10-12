from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(30))
    venue: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(String(2000))
    theme: Mapped[str] = mapped_column(String(20), default="violet")
    price_paise: Mapped[int]
    published: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (CheckConstraint("price_paise >= 0", name="event_price_positive"),)


class Hold(Base):
    __tablename__ = "holds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reference: Mapped[str | None] = mapped_column(String(20), unique=True)
    total_paise: Mapped[int]
    seat_labels: Mapped[str] = mapped_column(String(100))
    __table_args__ = (
        CheckConstraint("status IN ('active', 'confirmed', 'released', 'cancelled')", name="hold_status"),
        CheckConstraint("total_paise >= 0", name="hold_price_positive"),
    )


class Seat(Base):
    __tablename__ = "seats"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    row: Mapped[str] = mapped_column(String(2))
    number: Mapped[int]
    hold_id: Mapped[str | None] = mapped_column(ForeignKey("holds.id"))
    __table_args__ = (
        UniqueConstraint("event_id", "row", "number", name="unique_event_seat"),
        Index("seat_hold_idx", "hold_id"),
    )


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    hold_id: Mapped[str] = mapped_column(ForeignKey("holds.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
