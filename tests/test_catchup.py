from datetime import date, datetime, timedelta

from common.market_calendar import IST, collection_window, last_close_before, target_trading_date
from common.models import Digest
from pipeline.catchup import plan_window

HOLS = {date(2026, 11, 24): "Gurpurb"}


def _digest(trading_date: str, start: datetime, end: datetime, mode: str = "daily",
            missed: int = 0) -> Digest:
    return Digest(trading_date=trading_date, mode=mode, missed_sessions=missed,
                  generated_at=end, window_start=start, window_end=end)


def _at(d: int, hh: int, mm: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, d, hh, mm, tzinfo=IST)


def test_target_moves_to_next_session_once_market_opens():
    assert target_trading_date(_at(16, 9, 0), HOLS) == date(2026, 11, 16)   # Mon pre-open
    assert target_trading_date(_at(16, 12, 0), HOLS) == date(2026, 11, 17)  # Mon mid-session
    assert target_trading_date(_at(23, 18, 0), HOLS) == date(2026, 11, 25)  # skips holiday


def test_last_close_before():
    assert last_close_before(_at(16, 12, 0), HOLS) == _at(13, 15, 30)  # Mon midday -> Fri
    assert last_close_before(_at(16, 16, 0), HOLS) == _at(16, 15, 30)  # Mon evening -> Mon
    assert last_close_before(_at(25, 8, 0), HOLS) == _at(23, 15, 30)   # after holiday


def test_no_previous_digest_is_daily():
    plan = plan_window(_at(17, 8, 0), HOLS, None)
    assert plan.mode == "daily" and plan.start == _at(16, 15, 30)


def test_next_session_is_daily():
    prev = _digest("2026-11-16", _at(13, 15, 30), _at(16, 8, 0))
    plan = plan_window(_at(17, 8, 0), HOLS, prev)
    assert plan.mode == "daily"
    assert plan.target == date(2026, 11, 17) and plan.start == _at(16, 15, 30)


def test_one_missed_session_is_catchup_from_last_run():
    prev = _digest("2026-11-16", _at(13, 15, 30), _at(16, 8, 0))
    plan = plan_window(_at(18, 8, 0), HOLS, prev)  # Tue 17 had no digest
    assert plan.mode == "catchup" and plan.missed_sessions == 1
    assert plan.start == _at(16, 8, 0) and plan.target == date(2026, 11, 18)


def test_weekend_and_holiday_are_not_missed_sessions():
    prev = _digest("2026-11-23", _at(20, 15, 30), _at(23, 8, 0))
    plan = plan_window(_at(25, 8, 0), HOLS, prev)  # Tue 24 is a holiday
    assert plan.mode == "daily"
    prev = _digest("2026-11-20", _at(19, 15, 30), _at(20, 8, 0))
    assert plan_window(_at(23, 8, 0), HOLS, prev).mode == "daily"  # Fri -> Mon


def test_long_gap_is_capped_at_lookback():
    prev = _digest("2026-10-01", _at(30, 15, 30, month=9), _at(1, 8, 0, month=10))
    now = _at(16, 8, 0)
    plan = plan_window(now, HOLS, prev, lookback_days=31)
    assert plan.mode == "catchup" and plan.missed_sessions > 20
    assert plan.start == now - timedelta(days=31)


def test_rerun_same_session_keeps_catchup_window():
    prev = _digest("2026-11-18", _at(16, 8, 0), _at(18, 8, 0), mode="catchup", missed=1)
    plan = plan_window(_at(18, 8, 45), HOLS, prev)
    assert plan.mode == "catchup" and plan.start == _at(16, 8, 0) and plan.missed_sessions == 1
    prev = _digest("2026-11-18", _at(17, 15, 30), _at(18, 8, 0))
    assert plan_window(_at(18, 8, 45), HOLS, prev).mode == "daily"


def test_collection_window_unchanged_for_morning_runs():
    target, start, _ = collection_window(_at(15, 8, 0), HOLS)  # Sunday
    assert target == date(2026, 11, 16) and start == _at(13, 15, 30)
