"""BSE corporate announcements (public JSON API used by bseindia.com)."""
from __future__ import annotations

from datetime import datetime

from datetime import timedelta

from dateutil import parser as dtparser

from collectors.base import Collector, build_item
from common.http import make_session, timeout
from common.market_calendar import IST
from common.models import NewsItem

ATTACH_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"


def parse_bse_rows(rows: list[dict]) -> list[NewsItem]:
    out: list[NewsItem] = []
    for r in rows:
        raw_dt = r.get("DT_TM") or r.get("NEWS_DT")
        if not raw_dt:
            continue
        try:
            published = dtparser.parse(raw_dt).replace(tzinfo=IST)
        except (ValueError, OverflowError):
            continue
        company = (r.get("SLONGNAME") or "").strip()
        subject = (r.get("NEWSSUB") or r.get("HEADLINE") or "").strip()
        attachment = (r.get("ATTACHMENTNAME") or "").strip()
        url = (ATTACH_BASE + attachment) if attachment else (r.get("NSURL") or "")
        if not url:
            url = f"https://www.bseindia.com/stock-share-price/x/x/{r.get('SCRIP_CD', '')}/corp-announcements/"
        title = subject if company and company.lower()[:12] in subject.lower() else f"{company}: {subject}"
        tickers = [f"BSE:{r['SCRIP_CD']}"] if r.get("SCRIP_CD") else []
        if company:
            tickers.append(f"NAME:{company}")
        category = (r.get("CATEGORYNAME") or "").strip()
        snippet = (r.get("HEADLINE") or "").strip()
        if category:
            snippet = f"[{category}] {snippet}"
        item = build_item(title=title, url=url, source="BSE Announcements",
                          published_at=published, snippet=snippet, raw_tickers=tickers)
        if item:
            out.append(item)
    return out


class BSECollector(Collector):
    def __init__(self, window_start, window_end, cfg: dict):
        super().__init__(window_start, window_end)
        self.cfg = cfg
        self.name = "BSE Announcements"

    def fetch(self) -> list[NewsItem]:
        session = make_session({
            "Referer": "https://www.bseindia.com/",
            "Origin": "https://www.bseindia.com",
            "Accept": "application/json, text/plain, */*",
        })
        # The API returns {} for multi-day ranges, so query one calendar day at a time.
        items: list[NewsItem] = []
        day = self.window_start.date()
        while day <= self.window_end.date():
            stamp = day.strftime("%Y%m%d")
            for page in range(1, int(self.cfg.get("max_pages", 8)) + 1):
                params = {"pageno": page, "strCat": -1, "strPrevDate": stamp, "strScrip": "",
                          "strSearch": "P", "strToDate": stamp, "strType": "C", "subcategory": -1}
                resp = session.get(self.cfg["url"], params=params, timeout=timeout())
                resp.raise_for_status()
                rows = (resp.json() or {}).get("Table") or []
                if not rows:
                    break
                items.extend(parse_bse_rows(rows))
                if len(rows) < 50:
                    break
            day += timedelta(days=1)
        return items


def _unused(_: datetime) -> None:  # keeps type-checkers quiet about datetime import
    return None
