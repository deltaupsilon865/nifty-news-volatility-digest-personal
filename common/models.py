"""Shared data models for the pipeline and the digest JSON schema."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["bullish", "bearish", "mixed", "uncertain"]
Scope = Literal["single_stock", "sector", "index"]
Level = Literal["low", "medium", "high"]
CapBucket = Literal["Large", "Mid", "Small", "Unknown", "Index"]
EventType = Literal[
    "earnings",
    "corporate_action",
    "order_win",
    "management_change",
    "regulatory",
    "macro_data",
    "monetary_policy",
    "global_cues",
    "commodity_currency",
    "block_bulk_deal",
    "rating_change",
    "legal_penalty",
    "other",
]

EVENT_TYPE_LABELS: dict[str, str] = {
    "earnings": "Earnings",
    "corporate_action": "Corporate action",
    "order_win": "Order win",
    "management_change": "Management change",
    "regulatory": "Regulatory (SEBI/RBI)",
    "macro_data": "Macro data",
    "monetary_policy": "Monetary policy",
    "global_cues": "Global cues",
    "commodity_currency": "Commodity / currency",
    "block_bulk_deal": "Block / bulk deal",
    "rating_change": "Rating change",
    "legal_penalty": "Legal / penalty",
    "other": "Other",
}


def make_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


class NewsItem(BaseModel):
    """Normalised article. Only headline, short snippet, source and link are stored."""

    id: str
    title: str
    snippet: str = ""
    url: str
    source: str
    published_at: datetime  # timezone-aware, IST
    raw_tickers: list[str] = Field(default_factory=list)
    coverage_count: int = 1
    covered_by: list[dict[str, str]] = Field(default_factory=list)  # [{source, url}]


class AffectedCompany(BaseModel):
    name: str
    relation: Literal["direct", "indirect"] = "direct"


class Score(BaseModel):
    """LLM judgement for one news item (validated output of stage 3)."""

    id: str
    severity: int = Field(ge=1, le=10)
    direction: Direction
    scope: Scope
    event_type: EventType
    affected_companies: list[AffectedCompany] = Field(default_factory=list)
    affected_sectors: list[str] = Field(default_factory=list)
    surprise_factor: Level
    confidence: Level
    why_it_matters: str = Field(max_length=320)


class PricePoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float


class ExpectedRange(BaseModel):
    prev_close: float
    expected_low: float
    expected_high: float
    expected_move_pct: float  # full expected intraday range as % of prev close
    baseline_atr_pct: float
    multiplier: float
    history: list[PricePoint] = Field(default_factory=list)


class StockImpact(BaseModel):
    symbol: str  # NSE symbol, or index name such as "NIFTY 50"
    name: str
    relation: Literal["direct", "indirect"] = "direct"
    is_index: bool = False
    cap_bucket: CapBucket = "Unknown"
    cap_rank: int | None = None
    market_cap_cr: float | None = None
    is_penny: bool = False
    expected_range: ExpectedRange | None = None


class DigestItem(BaseModel):
    rank: int
    rank_score: float
    id: str
    title: str
    snippet: str
    url: str
    source: str
    published_at: datetime
    coverage_count: int
    covered_by: list[dict[str, str]]
    severity: int
    direction: Direction
    scope: Scope
    event_type: EventType
    surprise_factor: Level
    confidence: Level
    why_it_matters: str
    affected_sectors: list[str]
    stocks: list[StockImpact]
    unmapped_companies: list[str] = Field(default_factory=list)


class EventEntry(BaseModel):
    date: str
    name: str
    category: str = "other"
    importance: str = "medium"
    note: str | None = None


class Digest(BaseModel):
    schema_version: int = 1
    trading_date: str  # the session this digest is for (YYYY-MM-DD)
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    market_mood: list[str] = Field(default_factory=list)
    india_vix: float | None = None
    india_vix_change_pct: float | None = None
    nifty_prev_close: float | None = None
    events: list[EventEntry] = Field(default_factory=list)
    source_stats: dict[str, dict[str, int | str]] = Field(default_factory=dict)
    pipeline_stats: dict[str, float | int | str] = Field(default_factory=dict)
    items: list[DigestItem] = Field(default_factory=list)
