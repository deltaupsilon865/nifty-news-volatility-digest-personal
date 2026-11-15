"""NSE corporate announcements. NSE often blocks scripts and cloud IPs, so this uses a
cookie warm-up, browser headers and retries, and gives up quietly on failure."""
from __future__ import annotations

import time

from dateutil import parser as dtparser

from collectors.base import Collector, build_item
from common.http import make_session, timeout
from common.market_calendar import IST
from common.models import NewsItem


def parse_nse_rows(rows: list[dict]) -> list[NewsItem]:
    out: list[NewsItem] = []
    for r in rows:
        raw_dt = r.get("an_dt") or r.get("sort_date")
        if not raw_dt:
            continue
        try:
            published = dtparser.parse(raw_dt, dayfirst=True).replace(tzinfo=IST)
        except (ValueError, OverflowError):
            continue
        symbol = (r.get("symbol") or "").strip()
        company = (r.get("sm_name") or symbol).strip()
        desc = (r.get("desc") or "").strip()
        url = (r.get("attchmntFile") or "").strip() or \
            f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"
        tickers = [f"NSE:{symbol}"] if symbol else []
        if r.get("sm_isin"):
            tickers.append(f"ISIN:{r['sm_isin']}")
        item = build_item(title=f"{company}: {desc}", url=url, source="NSE Announcements",
                          published_at=published, snippet=r.get("attchmntText") or "",
                          raw_tickers=tickers)
        if item:
            out.append(item)
    return out


class NSECollector(Collector):
    def __init__(self, window_start, window_end, cfg: dict):
        super().__init__(window_start, window_end)
        self.cfg = cfg
        self.name = "NSE Announcements"

    def fetch(self) -> list[NewsItem]:
        session = make_session({"Referer": self.cfg["warmup_url"]}, retries=1)
        # Warm-up: NSE sets the cookies its API requires on these pages.
        session.get(self.cfg["home_url"], timeout=timeout())
        time.sleep(1.0)
        session.get(self.cfg["warmup_url"], timeout=timeout())
        params = {"index": "equities",
                  "from_date": self.window_start.strftime("%d-%m-%Y"),
                  "to_date": self.window_end.strftime("%d-%m-%Y")}
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = session.get(self.cfg["api_url"], params=params, timeout=timeout(),
                                   headers={"Accept": "application/json, text/plain, */*",
                                            "X-Requested-With": "XMLHttpRequest"})
                resp.raise_for_status()
                data = resp.json()
                rows = data if isinstance(data, list) else data.get("data", [])
                return parse_nse_rows(rows)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(2 * (attempt + 1))
                session.get(self.cfg["home_url"], timeout=timeout())
        raise RuntimeError(f"NSE blocked or unavailable: {last_exc}")
