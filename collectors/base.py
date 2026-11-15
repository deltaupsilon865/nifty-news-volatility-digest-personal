"""Base collector: every source is isolated and reports its own stats."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from common import config
from common.log import get_logger
from common.market_calendar import IST
from common.models import NewsItem, make_id
from common.text import canonical_url, strip_html, truncate

log = get_logger("collectors")


@dataclass
class CollectResult:
    name: str
    items: list[NewsItem] = field(default_factory=list)
    status: str = "ok"          # ok | empty | error | skipped
    error: str = ""
    seconds: float = 0.0

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {"count": len(self.items), "status": self.status,
                               "seconds": round(self.seconds, 1)}
        if self.error:
            out["error"] = self.error[:200]
        return out


class Collector(ABC):
    name: str = "base"

    def __init__(self, window_start: datetime, window_end: datetime):
        self.window_start = window_start
        self.window_end = window_end

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        ...

    def run(self) -> CollectResult:
        """Run the collector, never raising."""
        t0 = time.monotonic()
        res = CollectResult(name=self.name)
        try:
            res.items = self.fetch()
            res.status = "ok" if res.items else "empty"
        except Exception as exc:  # noqa: BLE001 - a source must never break the run
            res.status = "error"
            res.error = f"{type(exc).__name__}: {exc}"
            log.warning("Source %s failed: %s", self.name, res.error)
        res.seconds = time.monotonic() - t0
        log.info("Source %-40s %-6s %4d items (%.1fs)", self.name, res.status, len(res.items), res.seconds)
        return res


def build_item(*, title: str, url: str, source: str, published_at: datetime,
               snippet: str = "", raw_tickers: list[str] | None = None) -> NewsItem | None:
    title = strip_html(title)
    if not title or not url:
        return None
    max_chars = int(config.settings().get("prefilter", {}).get("snippet_max_chars", 300))
    snippet = truncate(strip_html(snippet), max_chars)
    if snippet.lower() == title.lower():
        snippet = ""
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=IST)
    return NewsItem(
        id=make_id(canonical_url(url) or title),
        title=truncate(title, 300),
        snippet=snippet,
        url=url.strip(),
        source=source,
        published_at=published_at.astimezone(IST),
        raw_tickers=raw_tickers or [],
        covered_by=[{"source": source, "url": url.strip()}],
    )
