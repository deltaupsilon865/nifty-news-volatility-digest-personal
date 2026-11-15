"""Stage 6: one ranking function; every weight comes from settings.yaml -> ranking.weights."""
from __future__ import annotations

from datetime import datetime

from common import config
from common.models import NewsItem, Score, StockImpact

_CAP_ORDER = ["Large", "Index", "Mid", "Small", "Unknown"]


def weights() -> dict:
    return config.settings()["ranking"]["weights"]


def rank_score(score: Score, item: NewsItem, stocks: list[StockImpact],
               w: dict | None = None) -> float:
    """rank = severity * w_sev * scope_mult * confidence_mult
              + surprise_bonus + coverage_bonus + cap_bucket_bonus

    - scope_mult rewards index/sector-wide news (more of the market moves).
    - surprise_bonus: unexpected news moves prices more than priced-in news.
    - coverage_bonus: each extra outlet covering the story adds weight, capped.
    - cap_bucket_bonus: the best (largest) directly affected company or index, as a proxy
      for index weight / market cap.
    """
    w = w or weights()
    base = score.severity * float(w.get("severity", 1.0))
    base *= float(w["scope"].get(score.scope, 1.0))
    base *= float(w["confidence"].get(score.confidence, 1.0))
    surprise = float(w["surprise"].get(score.surprise_factor, 0.0))
    coverage = min(float(w.get("coverage_cap", 1.0)),
                   max(0, item.coverage_count - 1) * float(w.get("coverage_per_extra_source", 0.25)))
    direct = [s for s in stocks if s.relation == "direct"] or stocks
    buckets = [s.cap_bucket for s in direct if not s.is_penny or s.is_index]
    best = min(buckets, key=lambda b: _CAP_ORDER.index(b) if b in _CAP_ORDER else 99,
               default="Unknown")
    cap_bonus = float(w["cap_bucket"].get(best, 0.0))
    return round(base + surprise + coverage + cap_bonus, 4)


def select_top(entries: list[tuple[float, datetime, str]], max_items: int | None = None) -> list[str]:
    """entries = (rank_score, published_at, id). Highest score first; ties go to the most
    recent item. Returns ids."""
    max_items = max_items or int(config.settings()["ranking"]["max_items"])
    ordered = sorted(entries, key=lambda e: (-e[0], -e[1].timestamp(), e[2]))
    return [e[2] for e in ordered[:max_items]]
