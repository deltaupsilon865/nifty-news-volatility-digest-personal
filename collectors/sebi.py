"""SEBI press releases and circulars, read from the public listing pages
(SEBI's RSS feed is frequently empty). Listings only carry a date, so items are
stamped at a configurable time of day (default 17:00 IST)."""
from __future__ import annotations

import re
from datetime import datetime, time

from bs4 import BeautifulSoup

from collectors.base import Collector, build_item
from common.http import make_session, timeout
from common.market_calendar import IST
from common.models import NewsItem


def parse_sebi_listing(html_text: str, label: str, stamp_time: time) -> list[NewsItem]:
    soup = BeautifulSoup(html_text, "html.parser")
    out: list[NewsItem] = []
    for row in soup.select("tr"):
        cells = row.find_all("td")
        link = row.find("a", href=True)
        if len(cells) < 2 or link is None:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        try:
            day = datetime.strptime(date_text, "%b %d, %Y").date()
        except ValueError:
            continue
        title = re.sub(r"\s+", " ", link.get("title") or link.get_text(" ", strip=True))
        item = build_item(title=f"SEBI {label}: {title}", url=link["href"], source="SEBI",
                          published_at=datetime.combine(day, stamp_time, tzinfo=IST))
        if item:
            out.append(item)
    return out


class SEBICollector(Collector):
    def __init__(self, window_start, window_end, cfg: dict):
        super().__init__(window_start, window_end)
        self.cfg = cfg
        self.name = "SEBI (press releases & circulars)"

    def fetch(self) -> list[NewsItem]:
        session = make_session()
        hh, mm = str(self.cfg.get("stamp_time", "17:00")).split(":")
        stamp = time(int(hh), int(mm))
        items: list[NewsItem] = []
        for page in self.cfg.get("pages", []):
            resp = session.get(page["url"], timeout=timeout())
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            items.extend(parse_sebi_listing(resp.text, page["label"], stamp))
        return items
