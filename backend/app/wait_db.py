"""Bounded database readiness for the single migration Job."""

import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .db import engine

for attempt in range(30):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        break
    except OperationalError:
        if attempt == 29:
            raise SystemExit("Database not ready after bounded migration wait") from None
        time.sleep(2)
