"""Symbol mapping, cap buckets, penny rule and impact building (synthetic reference data)."""
import pandas as pd
import pytest
from helpers import item

from common.models import AffectedCompany, Score
from mapping.impacts import ImpactBuilder
from mapping.market_cap import MarketCapTable, bucket_for_rank, is_penny
from mapping.symbols import SymbolMapper, normalise_company

EQUITY = pd.DataFrame([
    ("RELIANCE", "Reliance Industries Limited", "EQ", "INE002A01018"),
    ("HDFCBANK", "HDFC Bank Limited", "EQ", "INE040A01034"),
    ("TATASTEEL", "Tata Steel Limited", "EQ", "INE081A01020"),
    ("TATAMOTORS", "Tata Motors Limited", "EQ", "INE155A01022"),
    ("PRICOLLTD", "Pricol Limited", "EQ", "INE726V01018"),
    ("TINYCO", "Tiny Penny Company Limited", "BE", "INE999Z01011"),
    ("SBIN", "State Bank of India", "EQ", "INE062A01020"),
], columns=["SYMBOL", "NAME", "SERIES", "ISIN"])

AMFI = pd.DataFrame([
    (1, "Reliance Industries", "INE002A01018", "RELIANCE", 1900000.0, "Large Cap"),
    (2, "HDFC Bank", "INE040A01034", "HDFCBANK", 1400000.0, "Large Cap"),
    (40, "Tata Steel", "INE081A01020", "TATASTEEL", 190000.0, "Large Cap"),
    (60, "Tata Motors", "INE155A01022", "TATAMOTORS", 150000.0, "Large Cap"),
    (180, "Pricol", "INE726V01018", "PRICOLLTD", 6000.0, "Mid Cap"),
    (4000, "Tiny Penny", "INE999Z01011", "TINYCO", 120.0, "Small Cap"),
    (5, "State Bank of India", "INE062A01020", "SBIN", 700000.0, "Large Cap"),
], columns=["RANK", "NAME", "ISIN", "NSE_SYMBOL", "MCAP_CR", "CATEGORY"])


@pytest.fixture
def caps():
    return MarketCapTable(AMFI)


@pytest.fixture
def mapper(caps):
    return SymbolMapper(EQUITY, caps, aliases={"SBI": "SBIN", "RIL": "RELIANCE"}, fuzzy_threshold=88)


def _score(**kw):
    base = dict(id="x", severity=6, direction="bullish", scope="single_stock", event_type="earnings",
                affected_companies=[], affected_sectors=[], surprise_factor="medium",
                confidence="high", why_it_matters="test")
    base.update(kw)
    return Score(**base)


def test_bucket_boundaries():
    assert bucket_for_rank(1, 100, 250) == "Large"
    assert bucket_for_rank(100, 100, 250) == "Large"
    assert bucket_for_rank(101, 100, 250) == "Mid"
    assert bucket_for_rank(250, 100, 250) == "Mid"
    assert bucket_for_rank(251, 100, 250) == "Small"
    assert bucket_for_rank(None) == "Unknown"


def test_penny_rule_is_price_or_mcap():
    assert is_penny(15.0, 5000.0, 20, 500)       # low price
    assert is_penny(150.0, 300.0, 20, 500)       # low market cap
    assert not is_penny(150.0, 5000.0, 20, 500)
    assert not is_penny(None, None, 20, 500)     # unknown -> not flagged


def test_normalise_company():
    assert normalise_company("Reliance Industries Ltd.") == "reliance industries"
    assert normalise_company("Larsen and Toubro Limited") == "larsen & toubro"


@pytest.mark.parametrize("name,expected,method", [
    ("SBI", "SBIN", "alias"),
    ("RELIANCE", "RELIANCE", "symbol"),
    ("HDFC Bank Ltd", "HDFCBANK", "exact"),
    ("Pricol", "PRICOLLTD", "exact"),
    ("Tata Steel", "TATASTEEL", "exact"),
    ("Reliance", "RELIANCE", "prefix"),
    ("Reliance Industris", "RELIANCE", "fuzzy"),
])
def test_map_name(mapper, name, expected, method):
    m = mapper.map_name(name)
    assert m is not None and m.symbol == expected and m.method == method


def test_unknown_and_foreign_names_not_mapped(mapper):
    assert mapper.map_name("Nvidia") is None
    assert mapper.map_name("") is None


def test_llm_ticker_not_in_master_is_rejected(mapper):
    assert mapper.map_name("FAKETICKER") is None


def test_raw_tickers_prefer_isin(mapper):
    m = mapper.from_raw_tickers(["NAME:Something Else", "ISIN:INE081A01020"])
    assert m.symbol == "TATASTEEL" and m.method == "isin"


def test_impacts_single_stock_with_caps(mapper, caps):
    b = ImpactBuilder(mapper, caps)
    s = _score(affected_companies=[AffectedCompany(name="Tata Steel", relation="direct"),
                                   AffectedCompany(name="Tiny Penny Company", relation="indirect"),
                                   AffectedCompany(name="Nvidia", relation="indirect")])
    stocks, unmapped = b.build(item("Tata Steel results"), s)
    assert [x.symbol for x in stocks] == ["TATASTEEL", "TINYCO"]
    assert stocks[0].cap_bucket == "Large" and stocks[0].relation == "direct"
    assert stocks[1].cap_bucket == "Small" and stocks[1].is_penny  # mcap 120 cr
    assert unmapped == ["Nvidia"]


def test_impacts_exchange_filing_is_direct(mapper, caps):
    b = ImpactBuilder(mapper, caps)
    it = item("Pricol: press release", source="NSE Announcements",
              tickers=["NSE:PRICOLLTD", "ISIN:INE726V01018"])
    stocks, _ = b.build(it, _score())
    assert stocks[0].symbol == "PRICOLLTD" and stocks[0].cap_bucket == "Mid"


def test_broad_market_maps_to_nifty_and_sector_index(mapper, caps):
    b = ImpactBuilder(mapper, caps)
    s = _score(scope="index", direction="bearish", event_type="macro_data",
               affected_sectors=["Broad Market", "Banks", "IT", "Auto"])
    stocks, _ = b.build(item("CPI hits 2-year high"), s)
    syms = [x.symbol for x in stocks]
    assert syms[0] == "NIFTY 50"
    assert "NIFTY BANK" in syms and "NIFTY IT" in syms
    assert len(syms) == 3  # max 2 sector indices
    assert all(x.is_index and x.cap_bucket == "Index" for x in stocks)
