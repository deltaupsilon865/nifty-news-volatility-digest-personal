"""Cheap, deterministic filtering before any LLM call.

* Generic news: drop clearly irrelevant topics (sports, lifestyle, ...).
* Exchange filings (NSE/BSE): drop routine compliance filings, keep material ones, keep
  results/updates only for notable companies (AMFI rank <= notable_rank), and merge all
  filings of one company into a single item (this also merges NSE and BSE copies).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from common import config
from common.models import NewsItem
from common.text import truncate

EXCHANGE_SOURCES = {"NSE Announcements", "BSE Announcements"}

MATERIAL_PATTERNS = [
    r"\border\b", r"\borders\b", r"contract", r"\bloa\b", r"letter of award", r"acquisition", r"acquire",
    r"merger", r"amalgamation", r"demerger", r"scheme of arrangement", r"buy ?back", r"bonus",
    r"stock split", r"sub-division", r"dividend", r"credit rating", r"\brating\b", r"resign",
    r"appointment of (?:md|ceo|cfo|managing director|chief)", r"cessation", r"\bceo\b", r"fraud",
    r"default", r"arrest", r"litigation", r"penalty", r"show cause", r"\bsearch\b", r"\braid\b",
    r"insolvency", r"\bnclt\b", r"\bqip\b", r"preferential", r"rights issue", r"offer for sale",
    r"\bofs\b", r"block deal", r"pledge", r"takeover", r"open offer", r"delist", r"strike",
    r"lockout", r"\bfire\b", r"shutdown", r"usfda", r"warning letter", r"import alert",
    r"eir\b", r"establishment inspection", r"joint venture", r"strategic partnership",
    r"definitive agreement", r"guidance", r"clarification", r"fund ?rais", r"divest",
    r"stake sale", r"sale or disposal", r"capacity expansion", r"commission(?:ed|ing)",
]
_MATERIAL_RE = re.compile("|".join(MATERIAL_PATTERNS), re.I)

# Events that can move even a tiny stock sharply; anything else from a company outside the
# top `material_max_rank` is dropped.
STRONG_PATTERNS = [
    r"fraud", r"default", r"insolvency", r"nclt", r"arrest", r"raid", r"search",
    r"usfda", r"warning letter", r"import alert", r"open offer", r"takeover", r"delist",
    r"merger", r"amalgamation", r"demerger", r"acquisition", r"buy ?back",
]
_STRONG_RE = re.compile("|".join(STRONG_PATTERNS), re.I)


@dataclass
class PrefilterStats:
    input: int = 0
    irrelevant_dropped: int = 0
    routine_dropped: int = 0
    non_notable_dropped: int = 0
    exchange_groups: int = 0
    output: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items() if isinstance(v, int)}


def _compile_words(words: list[str]) -> re.Pattern | None:
    if not words:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.I)


def is_exchange(item: NewsItem) -> bool:
    return item.source in EXCHANGE_SOURCES


def is_material(text: str) -> bool:
    return bool(_MATERIAL_RE.search(text))


def is_strong(text: str) -> bool:
    return bool(_STRONG_RE.search(text))


def prefilter(items: list[NewsItem],
              resolve: Callable[[NewsItem], tuple[str | None, int | None]] | None = None,
              notable_rank: int = 500,
              material_max_rank: int = 1500) -> tuple[list[NewsItem], PrefilterStats]:
    """resolve(item) -> (symbol, amfi_rank) for exchange filings; optional."""
    src = config.sources()
    irrelevant_re = _compile_words(src.get("irrelevant_keywords", []))
    routine = [p.lower() for p in src.get("routine_announcement_phrases", [])]
    stats = PrefilterStats(input=len(items))
    news: list[NewsItem] = []
    groups: dict[str, list[tuple[NewsItem, bool]]] = defaultdict(list)

    for it in items:
        if irrelevant_re and irrelevant_re.search(it.title):
            stats.irrelevant_dropped += 1
            continue
        if not is_exchange(it):
            news.append(it)
            continue
        text = f"{it.title} {it.snippet}".lower()
        if any(p in text for p in routine):
            stats.routine_dropped += 1
            continue
        symbol, rank = resolve(it) if resolve else (None, None)
        notable = rank is not None and rank <= notable_rank
        in_universe = rank is not None and rank <= material_max_rank
        material = is_material(text) and (in_universe or is_strong(text) or resolve is None)
        if not material and not notable:
            stats.non_notable_dropped += 1
            continue
        key = symbol or it.title.split(":")[0].strip().lower()
        if symbol and f"NSE:{symbol}" not in it.raw_tickers:
            it = it.model_copy(update={"raw_tickers": [*it.raw_tickers, f"NSE:{symbol}"]})
        groups[key].append((it, material))

    for key, members in groups.items():
        news.append(_merge_filings(members))
    stats.exchange_groups = len(groups)
    stats.output = len(news)
    return news, stats


def _merge_filings(members: list[tuple[NewsItem, bool]]) -> NewsItem:
    """Merge all filings of one company into one item, material ones first."""
    members = sorted(members, key=lambda m: (not m[1], m[0].published_at))
    head = members[0][0]
    if len(members) == 1:
        return head
    company = head.title.split(":")[0].strip() if ":" in head.title else head.title
    subjects: list[str] = []
    for it, _ in members:
        subj = it.title.split(":", 1)[-1].strip() if ":" in it.title else it.title
        subj = re.sub(r"^.*? - \d{6} - ", "", subj)  # strip BSE "Company - 500325 - " prefix
        if subj and subj.lower() not in (s.lower() for s in subjects):
            subjects.append(subj)
    snippets: list[str] = []
    for it, _ in members:
        if it.snippet and it.snippet not in snippets:
            snippets.append(it.snippet)
    tickers = list(dict.fromkeys(t for it, _ in members for t in it.raw_tickers))
    covered = list({c["url"]: c for it, _ in members for c in it.covered_by}.values())
    max_chars = int(config.settings().get("prefilter", {}).get("snippet_max_chars", 300))
    return head.model_copy(update={
        "title": truncate(f"{company}: " + "; ".join(subjects[:4]), 300),
        "snippet": truncate(" | ".join(snippets), max_chars),
        "raw_tickers": tickers,
        "published_at": min(it.published_at for it, _ in members),
        "covered_by": covered,
        "source": "NSE Announcements" if any(it.source == "NSE Announcements" for it, _ in members)
        else head.source,
    })
