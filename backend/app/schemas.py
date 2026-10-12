import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class HoldCreate(BaseModel):
    event_id: int = Field(gt=0)
    seat_ids: list[int] = Field(min_length=1, max_length=6)

    @field_validator("seat_ids")
    @classmethod
    def distinct_seats(cls, value):
        if len(set(value)) != len(value) or any(seat <= 0 for seat in value):
            raise ValueError("Choose distinct, valid seats")
        return value


class EventInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    slug: str = Field(min_length=3, max_length=100)
    category: Literal["Music", "Comedy", "Theatre", "Talks"]
    venue: str = Field(min_length=2, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    starts_at: datetime
    description: str = Field(min_length=10, max_length=2000)
    theme: Literal["violet", "orange", "green", "blue"] = "violet"
    price_paise: int = Field(ge=0, le=10_000_000)
    published: bool = True

    @field_validator("slug")
    @classmethod
    def safe_slug(cls, value):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("Use lowercase letters, numbers and hyphens")
        return value

    @field_validator("starts_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Include a timezone")
        return value
