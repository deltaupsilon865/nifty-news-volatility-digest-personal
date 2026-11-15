import json
from datetime import date, datetime

from conftest import FIXTURES

from collectors.bse import parse_bse_rows
from collectors.nse import parse_nse_rows
from collectors.rss import parse_feed
from collectors.sebi import parse_sebi_listing
from common.market_calendar import IST


def test_rss_fixture_parses_and_normalises():
    items, undated = parse_feed((FIXTURES / "livemint_markets.xml").read_bytes(), "Livemint")
    assert items and undated == 0
    for it in items:
        assert it.source == "Livemint"
        assert it.published_at.tzinfo is not None
        assert it.published_at.utcoffset().total_seconds() == 5.5 * 3600
        assert len(it.snippet) <= 300
        assert "<" not in it.title


def test_bse_rows_parse_with_ticker_and_name():
    rows = json.loads((FIXTURES / "bse_announcements.json").read_text())
    items = parse_bse_rows(rows)
    assert len(items) == len(rows)
    assert all(any(t.startswith("BSE:") for t in it.raw_tickers) for it in items)
    assert all(it.source == "BSE Announcements" for it in items)


def test_nse_rows_parse_with_symbol_and_isin():
    rows = json.loads((FIXTURES / "nse_announcements.json").read_text())
    items = parse_nse_rows(rows)
    assert len(items) == len(rows)
    first = items[0]
    assert any(t.startswith("NSE:") for t in first.raw_tickers)
    assert any(t.startswith("ISIN:") for t in first.raw_tickers)


def test_sebi_listing_parses_date_rows():
    html = """<table><tr role='row'><th>Date</th><th>PR</th><th>Title</th></tr>
    <tr role='row'><td>Nov 12, 2026</td><td>71/2026</td><td>
    <a href="https://www.sebi.gov.in/x_1.html" title="SEBI board meeting">SEBI board meeting</a></td></tr></table>"""
    from datetime import time
    items = parse_sebi_listing(html, "press release", time(17, 0))
    assert len(items) == 1
    assert items[0].published_at == datetime(2026, 11, 12, 17, 0, tzinfo=IST)
    assert items[0].title.startswith("SEBI press release:")


def test_window_spans_weekend_and_holidays():
    from common.market_calendar import collection_window, events_for
    hols = {date(2026, 11, 24): "Gurpurb"}
    now = datetime(2026, 11, 15, 8, 0, tzinfo=IST)  # Sunday
    target, start, end = collection_window(now, hols)
    assert target == date(2026, 11, 16)
    assert start == datetime(2026, 11, 13, 15, 30, tzinfo=IST)
    # Tuesday 24 Nov is a holiday, so weekly expiry moves to Monday 23 Nov.
    now = datetime(2026, 11, 25, 8, 0, tzinfo=IST)
    target, start, _ = collection_window(now, hols)
    assert start == datetime(2026, 11, 23, 15, 30, tzinfo=IST)
