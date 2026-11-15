"""Generic RSS/Atom collector (publisher feeds, RBI, SEBI)."""
from __future__ import annotations

import calendar
from datetime import datetime, timezone

import feedparser
from dateutil import parser as dtparser

from collectors.base import Collector, build_item, log
from common.http import make_session, timeout
from common.market_calendar import IST
from common.models import NewsItem


def entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc).astimezone(IST)
    for key in ("published", "updated", "pubDate"):
        raw = entry.get(key)
        if raw:
            try:
                dt = dtparser.parse(raw)
                return (dt if dt.tzinfo else dt.replace(tzinfo=IST)).astimezone(IST)
            except (ValueError, OverflowError):
                continue
    return None


def parse_feed(content: bytes, source: str) -> tuple[list[NewsItem], int]:
    """Parse feed bytes into items. Returns (items, undated_count)."""
    feed = feedparser.parse(content)
    items: list[NewsItem] = []
    undated = 0
    for e in feed.entries:
        published = entry_datetime(e)
        if published is None:
            undated += 1
            continue
        item = build_item(
            title=e.get("title", ""),
            url=e.get("link", ""),
            source=source,
            published_at=published,
            snippet=e.get("summary", "") or e.get("description", ""),
        )
        if item:
            items.append(item)
    return items, undated


class RSSCollector(Collector):
    def __init__(self, window_start, window_end, source_name: str, url: str):
        super().__init__(window_start, window_end)
        self.source_name = source_name
        self.url = url
        self.name = f"{source_name} RSS ({'/'.join(url.split('/')[3:5])[:30]})"

    def fetch(self) -> list[NewsItem]:
        session = make_session()
        resp = session.get(self.url, timeout=timeout())
        resp.raise_for_status()
        items, undated = parse_feed(resp.content, self.source_name)
        if undated:
            log.debug("%s: skipped %d undated entries", self.name, undated)
        return items
