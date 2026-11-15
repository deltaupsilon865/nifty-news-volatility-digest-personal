"""Stage 1: collect news from every configured source in parallel."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from collectors.base import CollectResult, Collector
from collectors.bse import BSECollector
from collectors.gnews import GNewsCollector
from collectors.google_news import GoogleNewsCollector
from collectors.nse import NSECollector
from collectors.rss import RSSCollector
from collectors.sebi import SEBICollector
from common import config
from common.models import NewsItem


def build_collectors(window_start: datetime, window_end: datetime) -> list[Collector]:
    src = config.sources()
    cols: list[Collector] = []
    for feed in src.get("rss", []):
        if feed.get("enabled", True):
            cols.append(RSSCollector(window_start, window_end, feed["name"], feed["url"]))
    if src.get("google_news", {}).get("enabled"):
        cols.append(GoogleNewsCollector(window_start, window_end, src["google_news"]))
    if src.get("sebi", {}).get("enabled"):
        cols.append(SEBICollector(window_start, window_end, src["sebi"]))
    if src.get("bse", {}).get("enabled"):
        cols.append(BSECollector(window_start, window_end, src["bse"]))
    if src.get("nse", {}).get("enabled"):
        cols.append(NSECollector(window_start, window_end, src["nse"]))
    if src.get("gnews", {}).get("enabled") and config.env("GNEWS_API_KEY"):
        cols.append(GNewsCollector(window_start, window_end, src["gnews"]))
    return cols


def collect_all(window_start: datetime, window_end: datetime,
                max_workers: int = 8) -> tuple[list[NewsItem], list[CollectResult]]:
    collectors = build_collectors(window_start, window_end)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda c: c.run(), collectors))
    items = [it for r in results for it in r.items]
    return items, results
