"""Stage 5: expected intraday range from recent volatility (ATR%) scaled by news severity.

This is a statistical *expected range*, not a price prediction."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from common import config
from common.log import get_logger
from common.models import ExpectedRange, PricePoint

log = get_logger("volatility")


def vcfg() -> dict:
    return config.settings()["volatility"]


def yahoo_ticker(symbol: str, is_index: bool = False) -> str:
    if is_index:
        idx = config.settings().get("indices", {}).get(symbol)
        return idx["yahoo"] if idx else symbol
    return f"{symbol}.NS"


def severity_multiplier(severity: int) -> float:
    for lo, hi, mult in vcfg()["severity_multipliers"]:
        if lo <= severity <= hi:
            return float(mult)
    return 1.0


def atr_pct(df: pd.DataFrame, window: int | None = None) -> float | None:
    """Average true range over the last `window` sessions as % of the last close."""
    window = window or int(vcfg()["atr_window"])
    df = df.dropna(subset=["High", "Low", "Close"])
    if len(df) < max(5, window // 2) + 1:
        return None
    prev = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()],
                   axis=1).max(axis=1).iloc[1:]
    atr = tr.tail(window).mean()
    last = float(df["Close"].iloc[-1])
    return float(atr / last * 100) if last > 0 else None


def range_from_baseline(prev_close: float, base_atr_pct: float, severity: int,
                        direction: str) -> tuple[float, float, float, float]:
    """Return (low, high, move_pct, multiplier). The move is split around the previous
    close according to direction_skew (share of the range placed above the close)."""
    mult = severity_multiplier(severity)
    move = base_atr_pct * mult
    up = float(vcfg()["direction_skew"].get(direction, 0.5))
    high = prev_close * (1 + move * up / 100)
    low = prev_close * (1 - move * (1 - up) / 100)
    return low, high, move, mult


def expected_range(df: pd.DataFrame, severity: int, direction: str) -> ExpectedRange | None:
    base = atr_pct(df)
    if base is None:
        return None
    clean = df.dropna(subset=["Open", "High", "Low", "Close"])
    prev_close = float(clean["Close"].iloc[-1])
    low, high, move, mult = range_from_baseline(prev_close, base, severity, direction)
    n = int(vcfg().get("chart_sessions", 20))
    hist = [PricePoint(date=pd.Timestamp(idx).strftime("%Y-%m-%d"), open=round(float(r.Open), 2),
                       high=round(float(r.High), 2), low=round(float(r.Low), 2),
                       close=round(float(r.Close), 2))
            for idx, r in clean.tail(n).iterrows()]
    return ExpectedRange(prev_close=round(prev_close, 2), expected_low=round(low, 2),
                         expected_high=round(high, 2), expected_move_pct=round(move, 2),
                         baseline_atr_pct=round(base, 2), multiplier=mult, history=hist)


class PriceStore:
    """Batched yfinance download with a same-day disk cache."""

    def __init__(self, cache_dir: Path | None = None, today: date | None = None):
        self.cache_dir = cache_dir or config.DATA_DIR / "cache" / "prices"
        self.today = today or date.today()
        self.frames: dict[str, pd.DataFrame] = {}
        self.failed: set[str] = set()
        self._load_cache()

    @property
    def _cache_file(self) -> Path:
        return self.cache_dir / f"{self.today:%Y-%m-%d}.json"

    def _load_cache(self) -> None:
        try:
            raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for t, recs in raw.items():
            df = pd.DataFrame(recs)
            if not df.empty:
                df.index = pd.to_datetime(df.pop("Date"))
                self.frames[t] = df

    def _save_cache(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            out = {}
            for t, df in self.frames.items():
                d = df.copy()
                d.insert(0, "Date", d.index.strftime("%Y-%m-%d"))
                out[t] = d.to_dict(orient="records")
            self._cache_file.write_text(json.dumps(out), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - cache is best effort
            log.debug("Price cache save failed: %s", exc)

    def fetch(self, tickers: list[str]) -> None:
        need = [t for t in dict.fromkeys(tickers) if t not in self.frames and t not in self.failed]
        if not need:
            return
        import yfinance as yf

        days = int(vcfg()["history_days"])
        period = f"{max(3, days // 20 + 1)}mo"
        for i in range(0, len(need), 50):
            chunk = need[i:i + 50]
            try:
                data = yf.download(chunk, period=period, interval="1d", group_by="ticker",
                                   auto_adjust=False, threads=True, progress=False)
            except Exception as exc:  # noqa: BLE001
                log.warning("yfinance download failed for %d tickers: %s", len(chunk), exc)
                self.failed.update(chunk)
                continue
            for t in chunk:
                try:
                    df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                    df = df[["Open", "High", "Low", "Close"]].dropna().tail(days)
                except (KeyError, TypeError):
                    df = pd.DataFrame()
                if df.empty:
                    self.failed.add(t)
                else:
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    self.frames[t] = df.astype(float)
        if self.failed:
            log.info("No price data for %d tickers (e.g. %s)", len(self.failed),
                     sorted(self.failed)[:5])
        self._save_cache()

    def get(self, ticker: str) -> pd.DataFrame | None:
        return self.frames.get(ticker)

    def last_close_change(self, ticker: str) -> tuple[float | None, float | None]:
        df = self.get(ticker)
        if df is None or len(df) < 2:
            return None, None
        last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
        return round(last, 2), round((last / prev - 1) * 100, 2)
