"""Compare earlier digests' expected ranges with what actually happened that session."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

from common import config
from common.log import get_logger
from common.models import Digest

log = get_logger("evaluation")

FIELDS = ["trading_date", "item_id", "rank", "symbol", "is_index", "cap_bucket", "severity",
          "direction", "prev_close", "expected_low", "expected_high", "expected_move_pct",
          "actual_open", "actual_high", "actual_low", "actual_close", "actual_range_pct",
          "within_range", "range_ratio", "actual_change_pct", "direction_hit"]


def eval_path(data_dir: Path | None = None) -> Path:
    return (data_dir or config.DATA_DIR) / "evaluation.csv"


def evaluated_dates(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as fh:
        return {row["trading_date"] for row in csv.DictReader(fh)}


def direction_hit(direction: str, change_pct: float) -> str:
    if direction == "bullish":
        return str(change_pct > 0)
    if direction == "bearish":
        return str(change_pct < 0)
    return ""  # mixed / uncertain: not scored


def evaluate_digest(digest: Digest, get_frame: Callable[[str, bool], pd.DataFrame | None]) -> list[dict]:
    """get_frame(symbol, is_index) -> daily OHLC frame indexed by date (may be None)."""
    rows: list[dict] = []
    day = pd.Timestamp(digest.trading_date)
    for it in digest.items:
        for s in it.stocks:
            er = s.expected_range
            if er is None:
                continue
            df = get_frame(s.symbol, s.is_index)
            if df is None or day not in df.index:
                continue
            bar = df.loc[day]
            o, h, l, c = (float(bar[k]) for k in ("Open", "High", "Low", "Close"))
            actual_range = (h - l) / er.prev_close * 100
            change = (c / er.prev_close - 1) * 100
            rows.append({
                "trading_date": digest.trading_date, "item_id": it.id, "rank": it.rank,
                "symbol": s.symbol, "is_index": s.is_index, "cap_bucket": s.cap_bucket,
                "severity": it.severity, "direction": it.direction,
                "prev_close": er.prev_close, "expected_low": er.expected_low,
                "expected_high": er.expected_high, "expected_move_pct": er.expected_move_pct,
                "actual_open": round(o, 2), "actual_high": round(h, 2), "actual_low": round(l, 2),
                "actual_close": round(c, 2), "actual_range_pct": round(actual_range, 2),
                "within_range": h <= er.expected_high and l >= er.expected_low,
                "range_ratio": round(actual_range / er.expected_move_pct, 3) if er.expected_move_pct else "",
                "actual_change_pct": round(change, 2),
                "direction_hit": direction_hit(it.direction, change),
            })
    return rows


def append_rows(rows: list[dict], path: Path) -> int:
    if not rows:
        return 0
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def pending_digests(digest_files: list[Path], today: date, done: set[str],
                    lookback: int = 10) -> list[Path]:
    """Digests for sessions that have already closed (strictly before today) and that are
    not in evaluation.csv yet."""
    out = [p for p in digest_files if p.stem < today.isoformat() and p.stem not in done]
    return sorted(out)[-lookback:]
