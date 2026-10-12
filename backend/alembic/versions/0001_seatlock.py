"""Seat inventory, timed reservations, and an auditable booking lifecycle."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade():
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("venue", sa.String(160), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("theme", sa.String(20), nullable=False),
        sa.Column("price_paise", sa.Integer, nullable=False),
        sa.Column("published", sa.Boolean, nullable=False),
        sa.CheckConstraint("price_paise >= 0", name="event_price_positive"),
    )
    op.create_table(
        "holds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id"), nullable=False, index=True),
        sa.Column("owner", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("reference", sa.String(20), unique=True),
        sa.Column("total_paise", sa.Integer, nullable=False),
        sa.Column("seat_labels", sa.String(100), nullable=False),
        sa.CheckConstraint("status IN ('active', 'confirmed', 'released', 'cancelled')", name="hold_status"),
        sa.CheckConstraint("total_paise >= 0", name="hold_price_positive"),
    )
    op.create_table(
        "seats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id"), nullable=False, index=True),
        sa.Column("row", sa.String(2), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("hold_id", sa.String(36), sa.ForeignKey("holds.id")),
        sa.UniqueConstraint("event_id", "row", "number", name="unique_event_seat"),
    )
    op.create_index("seat_hold_idx", "seats", ["hold_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hold_id", sa.String(36), sa.ForeignKey("holds.id"), nullable=False, index=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for table in ["audit_events", "seats", "holds", "events"]:
        op.drop_table(table)
