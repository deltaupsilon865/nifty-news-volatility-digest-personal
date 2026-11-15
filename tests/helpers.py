from datetime import datetime, timedelta

from common.market_calendar import IST
from common.models import NewsItem, make_id

BASE_TIME = datetime(2026, 11, 13, 18, 0, tzinfo=IST)


def item(title: str, source: str = "Economic Times", url: str | None = None,
         minutes: int = 0, snippet: str = "", tickers: list[str] | None = None) -> NewsItem:
    url = url or f"https://example.com/{make_id(title + source)}"
    return NewsItem(id=make_id(url), title=title, snippet=snippet, url=url, source=source,
                    published_at=BASE_TIME + timedelta(minutes=minutes),
                    raw_tickers=tickers or [], covered_by=[{"source": source, "url": url}])
