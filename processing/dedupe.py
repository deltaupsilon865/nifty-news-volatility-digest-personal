"""Deduplicate stories: first by canonical URL, then by fuzzy title similarity.
The kept item is the most authoritative source (earliest on ties); coverage_count is the
number of distinct publishers that carried the story."""
from __future__ import annotations

import re

import numpy as np
from rapidfuzz import fuzz, process

from common import config
from common.models import NewsItem
from common.text import canonical_url, normalise_title


def publisher_key(source: str) -> str:
    s = re.sub(r"\s*\(via [^)]*\)\s*$", "", source).strip().lower()
    s = re.sub(r"^the\s+", "", s).replace(".com", "").strip()
    return {"mint": "livemint", "businessline": "hindu businessline"}.get(s, s)


def source_priority(source: str) -> int:
    table: dict[str, int] = config.settings().get("dedupe", {}).get("source_priority", {})
    if source in table:
        return int(table[source])
    if "(via GNews)" in source:
        return int(table.get("GNews", 4))
    if "(via Google News)" in source:
        return int(table.get("Google News", 5))
    return 3


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _merge(cluster: list[NewsItem]) -> NewsItem:
    best = min(cluster, key=lambda it: (source_priority(it.source), it.published_at))
    covered: dict[str, dict[str, str]] = {}
    for it in sorted(cluster, key=lambda it: (source_priority(it.source), it.published_at)):
        for c in it.covered_by or [{"source": it.source, "url": it.url}]:
            covered.setdefault(publisher_key(c["source"]), c)
    snippet = best.snippet or next((it.snippet for it in cluster if it.snippet), "")
    tickers = list(dict.fromkeys(t for it in cluster for t in it.raw_tickers))
    return best.model_copy(update={
        "snippet": snippet,
        "raw_tickers": tickers,
        "published_at": min(it.published_at for it in cluster),
        "coverage_count": len(covered),
        "covered_by": list(covered.values()),
    })


def title_similarity(a: str, b: str) -> float:
    """token_set_ratio is good for re-worded headlines but too lenient on very short ones."""
    if min(len(a.split()), len(b.split())) >= 6:
        return fuzz.token_set_ratio(a, b)
    return fuzz.token_sort_ratio(a, b)


def dedupe(items: list[NewsItem], threshold: float | None = None) -> list[NewsItem]:
    if not items:
        return []
    threshold = threshold if threshold is not None else \
        float(config.settings().get("dedupe", {}).get("title_similarity_threshold", 85))

    # 1) canonical URL
    by_url: dict[str, list[NewsItem]] = {}
    for it in items:
        by_url.setdefault(canonical_url(it.url) or it.id, []).append(it)
    stage1 = [_merge(group) for group in by_url.values()]

    # 2) fuzzy title
    titles = [normalise_title(it.title) for it in stage1]
    n = len(titles)
    uf = _UnionFind(n)
    long_mask = np.array([len(t.split()) >= 6 for t in titles])
    set_scores = process.cdist(titles, titles, scorer=fuzz.token_set_ratio, workers=-1)
    sort_scores = process.cdist(titles, titles, scorer=fuzz.token_sort_ratio, workers=-1)
    both_long = np.logical_and.outer(long_mask, long_mask)
    scores = np.where(both_long, set_scores, sort_scores)
    ii, jj = np.where(np.triu(scores >= threshold, k=1))
    for i, j in zip(ii.tolist(), jj.tolist()):
        if titles[i] and titles[j]:
            uf.union(i, j)
    clusters: dict[int, list[NewsItem]] = {}
    for idx, it in enumerate(stage1):
        clusters.setdefault(uf.find(idx), []).append(it)
    merged = [_merge(c) for c in clusters.values()]
    merged.sort(key=lambda it: it.published_at, reverse=True)
    return merged


def cap_items(items: list[NewsItem], max_items: int) -> list[NewsItem]:
    """Safety cap before the LLM: prefer wide coverage, authoritative sources, recency."""
    if len(items) <= max_items:
        return items
    ranked = sorted(items, key=lambda it: (-it.coverage_count, source_priority(it.source),
                                           -it.published_at.timestamp()))
    return ranked[:max_items]
