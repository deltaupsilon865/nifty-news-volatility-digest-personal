"""Drop items published outside the collection window."""
from __future__ import annotations

from datetime import datetime, timedelta

from common.models import NewsItem


def filter_window(items: list[NewsItem], start: datetime, end: datetime,
                  future_tolerance: timedelta = timedelta(minutes=30)) -> list[NewsItem]:
    """Keep items with start <= published_at <= end (+ small tolerance for clock skew)."""
    return [it for it in items if start <= it.published_at <= end + future_tolerance]
