from datetime import datetime, timedelta

from helpers import BASE_TIME, item

from common.market_calendar import IST
from common.text import canonical_url
from processing.dedupe import cap_items, dedupe, publisher_key
from processing.prefilter import prefilter
from processing.window import filter_window


def test_canonical_url_strips_tracking_and_amp():
    a = canonical_url("https://www.livemint.com/market/story-1.html?utm_source=x&utm_medium=y#top")
    b = canonical_url("https://livemint.com/market/story-1.html/amp/")
    assert a == canonical_url("https://livemint.com/market/story-1.html")
    assert b == a


def test_same_url_merged_and_coverage_counted():
    items = [
        item("RBI hikes repo rate by 25 bps", source="Livemint",
             url="https://www.livemint.com/a.html?utm_source=tw"),
        item("RBI hikes repo rate by 25 bps", source="Livemint", url="https://livemint.com/a.html"),
    ]
    out = dedupe(items)
    assert len(out) == 1
    assert out[0].coverage_count == 1  # same publisher twice is one source


def test_fuzzy_titles_cluster_and_keep_authoritative_earliest():
    items = [
        item("Infosys Q2 net profit rises 12% to Rs 7,000 crore, beats estimates",
             source="Moneycontrol.com (via Google News)", minutes=5),
        item("Infosys Q2 net profit rises 12% to Rs 7,000 crore; beats estimates",
             source="Economic Times", minutes=10),
        item("Infosys Q2 profit rises 12% to Rs 7,000 crore, beats street estimates",
             source="Business Standard", minutes=1),
        item("Tata Steel shares fall after weak Europe guidance", source="Livemint"),
    ]
    out = dedupe(items, threshold=85)
    assert len(out) == 2
    infy = next(o for o in out if "Infosys" in o.title)
    assert infy.coverage_count == 3
    # Business Standard and ET share priority 2; BS is earliest
    assert infy.source == "Business Standard"
    assert infy.published_at == BASE_TIME + timedelta(minutes=1)


def test_short_titles_do_not_overmerge():
    items = [item("Nifty ends higher"), item("Nifty ends lower", source="Livemint")]
    assert len(dedupe(items, threshold=85)) == 2


def test_publisher_key_normalises_google_news_names():
    assert publisher_key("The Economic Times (via Google News)") == publisher_key("Economic Times")
    assert publisher_key("Mint (via Google News)") == publisher_key("Livemint")


def test_window_filter():
    start = datetime(2026, 11, 13, 15, 30, tzinfo=IST)
    end = datetime(2026, 11, 14, 8, 0, tzinfo=IST)
    items = [item("old", minutes=-200), item("in window"), item("far future", minutes=60 * 24)]
    kept = filter_window(items, start, end)
    assert [k.title for k in kept] == ["in window"]


def test_prefilter_drops_irrelevant_and_routine_and_merges_filings():
    items = [
        item("IPL auction: Mumbai Indians buy star bowler"),
        item("Acme Ltd: Trading Window closure", source="NSE Announcements", tickers=["NSE:ACME"]),
        item("Acme Ltd: Bagging of order worth Rs 500 crore", source="NSE Announcements",
             tickers=["NSE:ACME"]),
        item("Acme Ltd - 500001 - Press Release", source="BSE Announcements",
             tickers=["NAME:Acme Ltd"]),
        item("Tiny Co: Credit rating reaffirmed", source="NSE Announcements", tickers=["NSE:TINY"]),
        item("Sensex falls 300 points on FII selling"),
    ]
    ranks = {"ACME": 300, "TINY": 4000}

    def resolve(it):
        sym = "ACME" if "Acme" in it.title else "TINY"
        return sym, ranks[sym]

    out, stats = prefilter(items, resolve)
    titles = [o.title for o in out]
    assert stats.irrelevant_dropped == 1
    assert stats.routine_dropped == 1
    assert stats.non_notable_dropped == 1  # Tiny Co: weak event, rank 4000
    assert any(t.startswith("Acme Ltd:") and "order" in t.lower() and "Press Release" in t for t in titles)
    assert "Sensex falls 300 points on FII selling" in titles
    assert len(out) == 2


def test_cap_items_prefers_coverage():
    a = item("A story")
    b = item("B story").model_copy(update={"coverage_count": 4})
    assert cap_items([a, b], 1)[0].title == "B story"
