"""NSE trading calendar: trading days, collection window and scheduled events."""
from __future__ import annotations

import calendar as _cal
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from common import config
from common.models import EventEntry

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


def holidays() -> dict[date, str]:
    raw = config.holidays_config().get("holidays") or {}
    out: dict[date, str] = {}
    for k, v in raw.items():
        d = k if isinstance(k, date) else date.fromisoformat(str(k))
        out[d] = str(v)
    return out


def is_trading_day(d: date, hols: dict[date, str] | None = None) -> bool:
    hols = holidays() if hols is None else hols
    return d.weekday() < 5 and d not in hols


def previous_trading_day(d: date, hols: dict[date, str] | None = None) -> date:
    hols = holidays() if hols is None else hols
    cur = d - timedelta(days=1)
    while not is_trading_day(cur, hols):
        cur -= timedelta(days=1)
    return cur


def next_trading_day(d: date, hols: dict[date, str] | None = None) -> date:
    hols = holidays() if hols is None else hols
    cur = d + timedelta(days=1)
    while not is_trading_day(cur, hols):
        cur += timedelta(days=1)
    return cur


def _close_time() -> time:
    hh, mm = config.settings().get("market_close_time", "15:30").split(":")
    return time(int(hh), int(mm))


def target_trading_date(now: datetime | None = None, hols: dict[date, str] | None = None) -> date:
    """The session the digest is for: today if it is a trading day and the market hasn't
    closed yet, otherwise the next trading day."""
    now = (now or now_ist()).astimezone(IST)
    hols = holidays() if hols is None else hols
    today = now.date()
    if is_trading_day(today, hols) and now.time() < _close_time():
        return today
    return next_trading_day(today, hols)


def collection_window(now: datetime | None = None,
                      hols: dict[date, str] | None = None) -> tuple[date, datetime, datetime]:
    """Return (target_date, window_start, window_end). Window starts at the close of the
    trading day before the target session."""
    now = (now or now_ist()).astimezone(IST)
    hols = holidays() if hols is None else hols
    target = target_trading_date(now, hols)
    prev = previous_trading_day(target, hols)
    start = datetime.combine(prev, _close_time(), tzinfo=IST)
    return target, start, now


def weekly_expiry(d: date, hols: dict[date, str] | None = None) -> date | None:
    """NIFTY weekly expiry for the week containing d (moved earlier on holidays)."""
    hols = holidays() if hols is None else hols
    wd = int(config.settings().get("calendar", {}).get("weekly_expiry_weekday", 1))
    expiry = d - timedelta(days=d.weekday()) + timedelta(days=wd)
    while not is_trading_day(expiry, hols):
        expiry -= timedelta(days=1)
    return expiry


def monthly_expiry(year: int, month: int, hols: dict[date, str] | None = None) -> date:
    hols = holidays() if hols is None else hols
    wd = int(config.settings().get("calendar", {}).get("weekly_expiry_weekday", 1))
    last_day = date(year, month, _cal.monthrange(year, month)[1])
    cur = last_day - timedelta(days=(last_day.weekday() - wd) % 7)
    while not is_trading_day(cur, hols):
        cur -= timedelta(days=1)
    return cur


def events_for(d: date, hols: dict[date, str] | None = None) -> list[EventEntry]:
    """Scheduled events on date d: configured ones plus computed recurring ones."""
    hols = holidays() if hols is None else hols
    out: list[EventEntry] = []
    for ev in config.events_config().get("events") or []:
        ev_date = ev["date"] if isinstance(ev["date"], date) else date.fromisoformat(str(ev["date"]))
        if ev_date == d:
            out.append(EventEntry(**{**ev, "date": ev_date.isoformat()}))

    if weekly_expiry(d, hols) == d:
        if monthly_expiry(d.year, d.month, hols) == d:
            out.append(EventEntry(date=d.isoformat(), name="NIFTY monthly F&O expiry",
                                  category="expiry", importance="high"))
        else:
            out.append(EventEntry(date=d.isoformat(), name="NIFTY weekly F&O expiry",
                                  category="expiry", importance="medium"))

    cpi_day = int(config.settings().get("calendar", {}).get("cpi_release_day", 12))
    cpi = date(d.year, d.month, cpi_day)
    while cpi.weekday() >= 5 or cpi in hols:
        cpi += timedelta(days=1)
    if cpi == d:
        out.append(EventEntry(date=d.isoformat(), name="India CPI inflation data (16:00 IST)",
                              category="macro_data", importance="high"))
    if d in hols:
        out.append(EventEntry(date=d.isoformat(), name=f"NSE holiday: {hols[d]}",
                              category="other", importance="high"))
    return out
