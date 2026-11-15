"""Market-cap buckets (AMFI rank) and the configurable penny-stock rule."""
from __future__ import annotations

from dataclasses import dataclass

from common import config


@dataclass(frozen=True)
class CapInfo:
    rank: int | None
    market_cap_cr: float | None
    bucket: str  # Large | Mid | Small | Unknown


def bucket_for_rank(rank: int | None, large_max: int | None = None, mid_max: int | None = None) -> str:
    cfg = config.settings().get("cap_buckets", {})
    large_max = large_max if large_max is not None else int(cfg.get("large_max_rank", 100))
    mid_max = mid_max if mid_max is not None else int(cfg.get("mid_max_rank", 250))
    if rank is None:
        return "Unknown"
    if rank <= large_max:
        return "Large"
    if rank <= mid_max:
        return "Mid"
    return "Small"


def is_penny(last_close: float | None, market_cap_cr: float | None,
             max_price: float | None = None, max_mcap_cr: float | None = None) -> bool:
    """Penny = last close below max_price OR market cap below max_mcap_cr (either may be
    unknown). Defaults come from settings.yaml -> penny."""
    cfg = config.settings().get("penny", {})
    max_price = float(cfg.get("max_price", 20)) if max_price is None else max_price
    max_mcap_cr = float(cfg.get("max_market_cap_cr", 500)) if max_mcap_cr is None else max_mcap_cr
    price_hit = last_close is not None and last_close < max_price
    mcap_hit = market_cap_cr is not None and market_cap_cr < max_mcap_cr
    return price_hit or mcap_hit


class MarketCapTable:
    def __init__(self, amfi_df):
        self._by_symbol: dict[str, CapInfo] = {}
        self._by_isin: dict[str, CapInfo] = {}
        for row in amfi_df.itertuples(index=False):
            info = CapInfo(rank=int(row.RANK), market_cap_cr=None if row.MCAP_CR != row.MCAP_CR else float(row.MCAP_CR),
                           bucket=bucket_for_rank(int(row.RANK)))
            if row.NSE_SYMBOL:
                self._by_symbol.setdefault(str(row.NSE_SYMBOL), info)
            if row.ISIN:
                self._by_isin.setdefault(str(row.ISIN), info)

    def lookup(self, symbol: str | None = None, isin: str | None = None) -> CapInfo:
        if symbol and symbol in self._by_symbol:
            return self._by_symbol[symbol]
        if isin and isin in self._by_isin:
            return self._by_isin[isin]
        return CapInfo(rank=None, market_cap_cr=None, bucket="Unknown")
