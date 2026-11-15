"""Expected-range maths, ranking formula, evaluation and digest JSON schema."""
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from helpers import BASE_TIME, item

from common.models import Digest, DigestItem, ExpectedRange, Score, StockImpact
from pipeline.evaluation import direction_hit, evaluate_digest, pending_digests
from pipeline.output import list_digest_dates, load_digest, write_digest
from ranking.rank import rank_score, select_top
from volatility.ranges import atr_pct, expected_range, range_from_baseline, severity_multiplier


def frame(n=30, close=100.0, hl=2.0):
    idx = pd.bdate_range("2026-10-01", periods=n)
    c = np.full(n, close)
    return pd.DataFrame({"Open": c, "High": c + hl / 2, "Low": c - hl / 2, "Close": c}, index=idx)


@pytest.mark.parametrize("sev,mult", [(1, 1.0), (3, 1.0), (4, 1.3), (6, 1.3), (7, 1.7), (8, 1.7),
                                      (9, 2.2), (10, 2.2)])
def test_severity_multiplier(sev, mult):
    assert severity_multiplier(sev) == mult


def test_atr_pct_constant_range():
    assert atr_pct(frame(hl=2.0), window=20) == pytest.approx(2.0)


def test_atr_uses_gaps():
    df = frame(hl=2.0)
    df.iloc[-1] = [110, 111, 109, 110]  # gap up of 10 from close 100
    # last TR = max(2, |111-100|, |109-100|) = 11 ; mean of 19*2 + 11 over 20
    assert atr_pct(df, window=20) == pytest.approx((19 * 2 + 11) / 20 / 110 * 100)


def test_atr_needs_history():
    assert atr_pct(frame(n=5), window=20) is None


def test_range_skew_bullish_bearish():
    lo, hi, move, mult = range_from_baseline(100.0, 2.0, 7, "bullish")
    assert mult == 1.7 and move == pytest.approx(3.4)
    assert hi == pytest.approx(100 + 3.4 * 0.65) and lo == pytest.approx(100 - 3.4 * 0.35)
    lo, hi, _, _ = range_from_baseline(100.0, 2.0, 7, "bearish")
    assert (100 - lo) > (hi - 100)
    lo, hi, _, _ = range_from_baseline(100.0, 2.0, 2, "uncertain")
    assert hi - 100 == pytest.approx(100 - lo) == pytest.approx(1.0)


def test_expected_range_object():
    er = expected_range(frame(), 5, "mixed")
    assert er.prev_close == 100.0 and er.multiplier == 1.3
    assert er.expected_high - er.expected_low == pytest.approx(2.6, abs=0.02)
    assert len(er.history) == 20


def _score(**kw):
    base = dict(id="x", severity=6, direction="bullish", scope="single_stock", event_type="earnings",
                surprise_factor="low", confidence="medium", why_it_matters="t")
    base.update(kw)
    return Score(**base)


W = {"severity": 1.0, "scope": {"index": 1.25, "sector": 1.1, "single_stock": 1.0},
     "surprise": {"low": 0, "medium": 0.4, "high": 0.9},
     "confidence": {"low": 0.85, "medium": 1.0, "high": 1.05},
     "coverage_per_extra_source": 0.25, "coverage_cap": 1.0,
     "cap_bucket": {"Large": 0.5, "Mid": 0.25, "Small": 0, "Unknown": 0, "Index": 0.5}}


def test_rank_score_components():
    it = item("x")
    assert rank_score(_score(), it, [], W) == 6.0
    assert rank_score(_score(scope="index"), it, [], W) == 7.5
    assert rank_score(_score(surprise_factor="high"), it, [], W) == 6.9
    it.coverage_count = 3
    assert rank_score(_score(), it, [], W) == 6.5
    it.coverage_count = 20  # capped
    assert rank_score(_score(), it, [], W) == 7.0


def test_rank_cap_bonus_uses_direct_and_ignores_penny():
    it = item("x")
    large_indirect = StockImpact(symbol="A", name="A", relation="indirect", cap_bucket="Large")
    mid_direct = StockImpact(symbol="B", name="B", relation="direct", cap_bucket="Mid")
    assert rank_score(_score(), it, [large_indirect, mid_direct], W) == 6.25
    penny = StockImpact(symbol="C", name="C", relation="direct", cap_bucket="Large", is_penny=True)
    assert rank_score(_score(), it, [penny], W) == 6.0


def test_select_top_tiebreak_recency():
    t = BASE_TIME
    entries = [(5.0, t, "old"), (5.0, t + timedelta(hours=1), "new"), (9.0, t, "best"), (1.0, t, "low")]
    assert select_top(entries, 3) == ["best", "new", "old"]


def _digest(day="2026-11-16"):
    er = ExpectedRange(prev_close=100, expected_low=98, expected_high=103, expected_move_pct=5,
                       baseline_atr_pct=2.9, multiplier=1.7)
    st = StockImpact(symbol="TATASTEEL", name="Tata Steel", cap_bucket="Large", expected_range=er)
    it = DigestItem(rank=1, rank_score=7.0, id="abc", title="t", snippet="s", url="https://x.y",
                    source="ET", published_at=BASE_TIME, coverage_count=1, covered_by=[],
                    severity=7, direction="bullish", scope="single_stock", event_type="earnings",
                    surprise_factor="high", confidence="high", why_it_matters="w",
                    affected_sectors=["Metals & Mining"], stocks=[st])
    return Digest(trading_date=day, generated_at=BASE_TIME, window_start=BASE_TIME,
                  window_end=BASE_TIME, items=[it])


def test_evaluation_rows():
    day = pd.Timestamp("2026-11-16")
    df = pd.DataFrame({"Open": [101], "High": [102.5], "Low": [99], "Close": [102]}, index=[day])
    rows = evaluate_digest(_digest(), lambda s, i: df)
    assert len(rows) == 1
    r = rows[0]
    assert r["within_range"] is True and r["direction_hit"] == "True"
    assert r["actual_range_pct"] == 3.5 and r["range_ratio"] == 0.7
    assert direction_hit("mixed", 1.0) == "" and direction_hit("bearish", 1.0) == "False"


def test_pending_digests_only_closed_sessions(tmp_path):
    files = [tmp_path / f"2026-11-{d}.json" for d in (12, 13, 16)]
    out = pending_digests(files, date(2026, 11, 16), done={"2026-11-12"})
    assert [p.stem for p in out] == ["2026-11-13"]


def test_digest_roundtrip_and_schema(tmp_path):
    d = _digest()
    day_path, latest = write_digest(d, data_dir=tmp_path)
    assert day_path.name == "2026-11-16.json" and latest.exists()
    raw = json.loads(latest.read_text(encoding="utf-8"))
    for key in ("trading_date", "generated_at", "market_mood", "items", "source_stats", "events"):
        assert key in raw
    item0 = raw["items"][0]
    for key in ("title", "snippet", "url", "source", "severity", "direction", "stocks", "why_it_matters"):
        assert key in item0
    assert "content" not in item0 and "body" not in item0  # never full article text
    assert load_digest(day_path) == d
    assert list_digest_dates(tmp_path) == ["2026-11-16"]
