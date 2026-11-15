"""Optional GNews API (free tier: 100 requests/day). Skipped when GNEWS_API_KEY is unset."""
from __future__ import annotations

import json
from datetime import timezone

from dateutil import parser as dtparser

from collectors.base import Collector, build_item
from common import config
from common.http import make_session, timeout
from common.market_calendar import IST, now_ist
from common.models import NewsItem

USAGE_FILE = config.DATA_DIR / "cache" / "gnews_usage.json"


def _load_usage() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_usage(usage: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(usage), encoding="utf-8")


class GNewsCollector(Collector):
    def __init__(self, window_start, window_end, cfg: dict):
        super().__init__(window_start, window_end)
        self.cfg = cfg
        self.name = "GNews API"

    def fetch(self) -> list[NewsItem]:
        key = config.env("GNEWS_API_KEY")
        if not key:
            return []
        today = now_ist().date().isoformat()
        usage = _load_usage()
        used = int(usage.get(today, 0))
        budget = min(int(self.cfg.get("max_requests_per_run", 8)),
                     int(self.cfg.get("daily_request_limit", 100)) - used)
        session = make_session()
        items: list[NewsItem] = []
        frm = self.window_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for q in self.cfg.get("queries", [])[: max(0, budget)]:
            resp = session.get(self.cfg["url"], timeout=timeout(), params={
                "q": q, "lang": "en", "country": "in", "from": frm, "max": 10, "apikey": key})
            used += 1
            if resp.status_code in (401, 403, 429):
                raise RuntimeError(f"GNews HTTP {resp.status_code}")
            resp.raise_for_status()
            for a in resp.json().get("articles", []):
                published = dtparser.parse(a["publishedAt"]).astimezone(IST)
                publisher = (a.get("source") or {}).get("name", "GNews")
                item = build_item(title=a.get("title", ""), url=a.get("url", ""),
                                  source=f"{publisher} (via GNews)", published_at=published,
                                  snippet=a.get("description", ""))
                if item:
                    items.append(item)
        usage = {today: used}
        _save_usage(usage)
        return items
