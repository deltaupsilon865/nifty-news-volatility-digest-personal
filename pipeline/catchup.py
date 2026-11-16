"""Decide the news window for a manual run: a normal daily digest, or a catch-up digest
when one or more sessions went by without a digest.

Rules:
- Normal ("daily"): news since the most recent session close; top 10 + more, up to 50 items.
- Catch-up: the previous digest was for a session before the one just ended (at least one
  session was missed). News since the previous digest's window end, capped at
  `catchup.max_lookback_days`; up to 100 items ranked by severity for the next open.
- Re-running for the same session keeps that session's window and mode.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from common import config
from common.market_calendar import collection_window, trading_days_between
from common.models import Digest


@dataclass(frozen=True)
class WindowPlan:
    target: date
    start: datetime
    end: datetime
    mode: str  # "daily" | "catchup"
    missed_sessions: int = 0

    @property
    def is_catchup(self) -> bool:
        return self.mode == "catchup"


def max_lookback_days() -> int:
    return int(config.settings().get("catchup", {}).get("max_lookback_days", 31))


def plan_window(now: datetime, hols: dict[date, str], previous: Digest | None,
                lookback_days: int | None = None) -> WindowPlan:
    target, normal_start, end = collection_window(now, hols)
    daily = WindowPlan(target, normal_start, end, "daily")
    if previous is None:
        return daily
    prev_target = date.fromisoformat(previous.trading_date)
    if prev_target == target:  # re-run for the same session
        if previous.mode == "catchup":
            return WindowPlan(target, min(previous.window_start, normal_start), end, "catchup",
                              previous.missed_sessions)
        return daily
    if prev_target > target:
        return daily
    missed = trading_days_between(prev_target, target, hols)
    if not missed:
        return daily
    floor = end - timedelta(days=lookback_days or max_lookback_days())
    start = min(max(previous.window_end, floor), normal_start)
    return WindowPlan(target, start, end, "catchup", len(missed))
