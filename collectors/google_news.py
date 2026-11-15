"""Google News RSS search (free, no key)."""
from __future__ import annotations

import feedparser

from collectors.base import Collector, build_item
from collectors.rss import entry_datetime
from common.http import make_session, timeout
from common.models import NewsItem


class GoogleNewsCollector(Collector):
    def __init__(self, window_start, window_end, cfg: dict):
        super().__init__(window_start, window_end)
        self.cfg = cfg
        self.name = "Google News"

    def _query(self, session, query: str) -> list[NewsItem]:
        hours = max(1, int((self.window_end - self.window_start).total_seconds() // 3600) + 1)
        when = f"when:{hours}h" if hours <= 72 else f"when:{(hours // 24) + 1}d"
        params = {"q": f"{query} {when}", **self.cfg.get("params", {})}
        resp = session.get(self.cfg["base_url"], params=params, timeout=timeout())
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        out: list[NewsItem] = []
        for e in feed.entries[: int(self.cfg.get("max_items_per_query", 25))]:
            published = entry_datetime(e)
            if published is None:
                continue
            title = e.get("title", "")
            publisher = (e.get("source") or {}).get("title", "") if isinstance(e.get("source"), dict) else ""
            if publisher and title.endswith(f" - {publisher}"):
                title = title[: -len(publisher) - 3]
            item = build_item(
                title=title,
                url=e.get("link", ""),
                source=f"{publisher or 'Unknown'} (via Google News)",
                published_at=published,
                snippet="",  # Google's description just repeats the title as a link
            )
            if item:
                out.append(item)
        return out

    def fetch(self) -> list[NewsItem]:
        session = make_session()
        items: list[NewsItem] = []
        errors = 0
        queries = self.cfg.get("queries", [])
        for q in queries:
            try:
                items.extend(self._query(session, q))
            except Exception:  # noqa: BLE001 - one query failing is fine
                errors += 1
        if errors == len(queries) and queries:
            raise RuntimeError("all Google News queries failed")
        return items
