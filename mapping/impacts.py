"""Stage 4: turn the LLM's company/sector names into validated NSE stock and index impacts."""
from __future__ import annotations

from common import config
from common.models import NewsItem, Score, StockImpact
from mapping.market_cap import MarketCapTable, is_penny
from mapping.symbols import SymbolMapper


def index_config() -> dict[str, dict]:
    return config.settings().get("indices", {})


def sector_to_index() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, cfg in index_config().items():
        for s in cfg.get("sectors", []):
            out.setdefault(s.strip().lower(), name)
    return out


def index_impact(name: str, relation: str = "indirect") -> StockImpact:
    return StockImpact(symbol=name, name=name, relation=relation, is_index=True, cap_bucket="Index")


class ImpactBuilder:
    def __init__(self, mapper: SymbolMapper, caps: MarketCapTable):
        self.mapper = mapper
        self.caps = caps
        s = config.settings()
        self.max_stocks = int(s.get("max_stocks_per_item", 6))
        self.max_sector_idx = int(s.get("max_sector_indices_per_item", 2))
        self.broad = s.get("mapping", {}).get("index_symbol", "NIFTY 50")
        self.sector_map = sector_to_index()

    def _stock(self, symbol: str, name: str, isin: str, relation: str) -> StockImpact:
        cap = self.caps.lookup(symbol=symbol, isin=isin)
        return StockImpact(symbol=symbol, name=name, relation=relation, cap_bucket=cap.bucket,
                           cap_rank=cap.rank, market_cap_cr=cap.market_cap_cr,
                           is_penny=is_penny(None, cap.market_cap_cr))

    def build(self, item: NewsItem, score: Score) -> tuple[list[StockImpact], list[str]]:
        """Return (stock/index impacts, company names that could not be mapped).
        Only symbols present in the NSE master are returned."""
        stocks: list[StockImpact] = []
        unmapped: list[str] = []
        seen: set[str] = set()

        def add(imp: StockImpact) -> None:
            if imp.symbol not in seen:
                seen.add(imp.symbol)
                stocks.append(imp)

        # Exchange filings carry an authoritative ISIN / symbol: that company is direct.
        exch = self.mapper.from_raw_tickers(item.raw_tickers)
        if exch:
            add(self._stock(exch.symbol, exch.name, exch.isin, "direct"))
        companies = sorted(score.affected_companies, key=lambda c: c.relation != "direct")
        for c in companies:
            if sum(not s.is_index for s in stocks) >= self.max_stocks:
                break
            m = self.mapper.map_name(c.name)
            if m is None:
                unmapped.append(c.name)
                continue
            add(self._stock(m.symbol, m.name, m.isin, c.relation))

        has_stock = any(not s.is_index for s in stocks)
        sectors = {x.strip().lower() for x in score.affected_sectors}
        if score.scope == "index" or (not has_stock and "broad market" in sectors):
            add(index_impact(self.broad, "direct"))
        if score.scope in ("index", "sector") or not has_stock:
            n = 0
            for sec in score.affected_sectors:
                idx = self.sector_map.get(sec.strip().lower())
                if idx and idx != self.broad and idx not in seen and n < self.max_sector_idx:
                    add(index_impact(idx, "direct" if score.scope == "sector" else "indirect"))
                    n += 1
        return stocks, unmapped
