"""Map company names to NSE symbols. Only symbols present in the NSE equity master are
ever returned; tickers suggested by the LLM are never trusted directly."""
from __future__ import annotations

import re
from dataclasses import dataclass

import yaml
from rapidfuzz import fuzz, process

from common import config

_SUFFIXES = {"limited", "ltd", "the", "co", "company", "corp", "corporation", "inc", "plc",
             "pvt", "private"}
_PAREN = re.compile(r"\([^)]*\)")
_NONWORD = re.compile(r"[^a-z0-9& ]+")


def normalise_company(name: str) -> str:
    n = name.lower().replace("’", "'").replace("'s", "s")
    n = _PAREN.sub(" ", n)
    n = n.replace(" and ", " & ").replace("&amp;", "&")
    n = _NONWORD.sub(" ", n)
    words = [w for w in n.split() if w not in _SUFFIXES]
    return " ".join(words)


@dataclass(frozen=True)
class SymbolMatch:
    symbol: str
    name: str
    isin: str
    method: str  # alias | symbol | isin | exact | prefix | fuzzy
    score: float


class SymbolMapper:
    def __init__(self, equity_df, market_cap=None, aliases: dict[str, str] | None = None,
                 fuzzy_threshold: float | None = None):
        eq = equity_df[equity_df["SERIES"].isin(["EQ", "BE", "BZ", "SM", "ST"])] \
            if "SERIES" in equity_df.columns else equity_df
        self.by_symbol: dict[str, tuple[str, str]] = {}
        self.by_isin: dict[str, str] = {}
        self.by_norm: dict[str, str] = {}
        for row in eq.itertuples(index=False):
            self.by_symbol[row.SYMBOL] = (row.NAME, row.ISIN)
            self.by_isin[row.ISIN] = row.SYMBOL
            self.by_norm.setdefault(normalise_company(row.NAME), row.SYMBOL)
        self.norm_names = list(self.by_norm.keys())
        self.market_cap = market_cap
        if aliases is None:
            try:
                with open(config.CONFIG_DIR / "aliases.yaml", encoding="utf-8") as fh:
                    aliases = (yaml.safe_load(fh) or {}).get("aliases", {})
            except OSError:
                aliases = {}
        self.aliases = {normalise_company(k): v for k, v in aliases.items() if v in self.by_symbol}
        self.fuzzy_threshold = fuzzy_threshold if fuzzy_threshold is not None else \
            float(config.settings().get("mapping", {}).get("fuzzy_threshold", 88))

    def _match(self, symbol: str, method: str, score: float = 100.0) -> SymbolMatch:
        name, isin = self.by_symbol[symbol]
        return SymbolMatch(symbol=symbol, name=name, isin=isin, method=method, score=score)

    def _rank(self, symbol: str) -> int:
        if self.market_cap is None:
            return 10**6
        info = self.market_cap.lookup(symbol=symbol)
        return info.rank if info.rank is not None else 10**6

    def from_isin(self, isin: str) -> SymbolMatch | None:
        sym = self.by_isin.get(isin)
        return self._match(sym, "isin") if sym else None

    def from_symbol(self, symbol: str) -> SymbolMatch | None:
        sym = symbol.strip().upper()
        return self._match(sym, "symbol") if sym in self.by_symbol else None

    def map_name(self, name: str) -> SymbolMatch | None:
        if not name or not name.strip():
            return None
        raw = name.strip()
        norm = normalise_company(raw)
        if not norm:
            return None
        if norm in self.aliases:
            return self._match(self.aliases[norm], "alias")
        # Looks like a ticker (e.g. "INFY", "BAJAJ-AUTO")
        if re.fullmatch(r"[A-Z0-9&\-]{2,20}", raw) and raw in self.by_symbol:
            return self._match(raw, "symbol")
        if norm in self.by_norm:
            return self._match(self.by_norm[norm], "exact")
        # Prefix: "Hindalco" -> "hindalco industries". Accept if unique, or pick the
        # largest company when the query has at least two words.
        if len(norm) >= 4:
            cands = [n for n in self.norm_names if n.startswith(norm + " ")]
            if len(cands) == 1 or (cands and len(norm.split()) >= 2):
                best = min(cands, key=lambda n: self._rank(self.by_norm[n]))
                return self._match(self.by_norm[best], "prefix", 95.0)
            if len(cands) > 1:
                ranked = sorted(cands, key=lambda n: self._rank(self.by_norm[n]))
                # single word but one candidate is clearly a large/mid cap
                if self._rank(self.by_norm[ranked[0]]) <= 250 and \
                        self._rank(self.by_norm[ranked[1]]) > 1000:
                    return self._match(self.by_norm[ranked[0]], "prefix", 90.0)
        hit = process.extractOne(norm, self.norm_names, scorer=fuzz.token_sort_ratio,
                                 score_cutoff=self.fuzzy_threshold)
        if hit:
            return self._match(self.by_norm[hit[0]], "fuzzy", float(hit[1]))
        return None

    def from_raw_tickers(self, tickers: list[str]) -> SymbolMatch | None:
        """Resolve exchange-provided identifiers (NSE:SYM, ISIN:..., NAME:...)."""
        for t in tickers:
            kind, _, value = t.partition(":")
            if kind == "ISIN" and (m := self.from_isin(value)):
                return m
        for t in tickers:
            kind, _, value = t.partition(":")
            if kind == "NSE" and (m := self.from_symbol(value)):
                return m
        for t in tickers:
            kind, _, value = t.partition(":")
            if kind == "NAME" and (m := self.map_name(value)):
                return m
        return None
