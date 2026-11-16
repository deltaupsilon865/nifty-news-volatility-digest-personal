"""Daily pipeline: collect -> filter/dedupe -> LLM judge -> map -> ranges -> rank -> write JSON.

Usage:
    python run_pipeline.py            # skips NSE holidays and weekends
    python run_pipeline.py --force    # run anyway (e.g. manual test on a weekend)
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime

from common import config
from common.log import get_logger, setup_logging
from common.market_calendar import collection_window, events_for, holidays, is_trading_day, now_ist
from common.models import Digest, DigestItem, NewsItem

log = get_logger("pipeline")


class Deadline:
    def __init__(self, seconds: float):
        self.start = time.monotonic()
        self.seconds = seconds

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def remaining(self) -> float:
        return self.seconds - self.elapsed

    def ok(self, needed: float = 0.0) -> bool:
        return self.remaining() > needed


def already_generated_today(trading_date: str, now: datetime) -> bool:
    """True if data/digests/<trading_date>.json exists and was generated on today's IST date."""
    from pipeline.output import digests_dir, load_digest
    path = digests_dir() / f"{trading_date}.json"
    if not path.exists():
        return False
    try:
        generated = load_digest(path).generated_at
    except Exception:  # unreadable file: regenerate it
        return False
    if generated.tzinfo is not None and now.tzinfo is not None:
        generated = generated.astimezone(now.tzinfo)
    return generated.date() == now.date()


def run(force: bool = False, now: datetime | None = None) -> int:
    now = now or now_ist()
    hols = holidays()
    if not force and not is_trading_day(now.date(), hols):
        log.info("%s is not an NSE trading day (%s) - nothing to do.", now.date(),
                 hols.get(now.date(), "weekend"))
        return 0

    settings = config.settings()
    deadline = Deadline(float(settings.get("max_run_seconds", 900)))
    target, ws, we = collection_window(now, hols)
    log.info("Digest for %s; news window %s -> %s", target, ws.strftime("%a %d %b %H:%M"),
             we.strftime("%a %d %b %H:%M"))
    stats: dict[str, float | int | str] = {}

    # The workflow has backup cron slots in case GitHub drops a scheduled trigger; a later
    # slot does nothing (and spends nothing) if this morning's digest is already published.
    if not force and already_generated_today(target.isoformat(), now):
        log.info("Digest for %s was already generated today - nothing to do.", target)
        return 0

    # Reference data (best effort; falls back to the committed copies)
    from mapping.market_cap import MarketCapTable, is_penny
    from mapping.reference import amfi_period_label, load_amfi, load_equity_master, \
        refresh_amfi, refresh_equity_master
    from mapping.symbols import SymbolMapper
    for fn in (refresh_equity_master, refresh_amfi):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("Reference refresh %s failed (%s); using cached copy", fn.__name__, exc)
    caps = MarketCapTable(load_amfi())
    mapper = SymbolMapper(load_equity_master(), caps)
    stats["amfi_period"] = amfi_period_label()

    # Stage 1: collect
    from collectors import collect_all
    items, results = collect_all(ws, we)
    source_stats = {r.name: r.stats() for r in results}
    stats["collected"] = len(items)

    # Stage 2: window, prefilter, dedupe
    from processing.dedupe import cap_items, dedupe
    from processing.prefilter import prefilter
    from processing.window import filter_window
    items = filter_window(items, ws, we)
    stats["in_window"] = len(items)

    def resolve(it: NewsItem):
        m = mapper.from_raw_tickers(it.raw_tickers)
        return (m.symbol, caps.lookup(symbol=m.symbol, isin=m.isin).rank) if m else (None, None)

    items, pstats = prefilter(items, resolve)
    stats.update({f"prefilter_{k}": v for k, v in pstats.as_dict().items()})
    items = dedupe(items)
    stats["deduped"] = len(items)
    items = cap_items(items, int(settings["prefilter"]["max_items_to_llm"]))
    stats["sent_to_llm"] = len(items)

    # Stage 3: LLM judge
    from scoring.judge import Judge, day_context
    from volatility.ranges import PriceStore, expected_range, yahoo_ticker
    prices = PriceStore(today=now.date())
    vix_t = settings.get("vix_ticker", "^INDIAVIX")
    nifty_t = yahoo_ticker(settings["mapping"]["index_symbol"], is_index=True)
    prices.fetch([vix_t, nifty_t])
    vix, vix_chg = prices.last_close_change(vix_t)
    nifty_close, _ = prices.last_close_change(nifty_t)
    events = events_for(target, hols)
    context = day_context(target, events, vix)
    hints = {}
    for it in items:
        m = mapper.from_raw_tickers(it.raw_tickers)
        if m:
            hints[it.id] = f"{m.name} (NSE: {m.symbol})"
    judge = Judge()
    scores = judge.score(items, context, hints)
    min_sev = int(settings["scoring"].get("min_severity_to_keep", 2))
    stats["scored"] = len(scores)
    by_id = {it.id: it for it in items}
    scored = [(by_id[sid], s) for sid, s in scores.items() if s.severity >= min_sev]
    stats["kept_after_scoring"] = len(scored)
    stats["severity_histogram"] = str(dict(sorted(Counter(s.severity for s in scores.values()).items())))

    # Stage 4: mapping
    from mapping.impacts import ImpactBuilder
    from ranking.rank import rank_score, select_top
    builder = ImpactBuilder(mapper, caps)
    mapped = {}
    for it, s in scored:
        stocks, unmapped = builder.build(it, s)
        mapped[it.id] = (it, s, stocks, unmapped)

    # Preliminary ranking (before prices) decides which items get price data.
    prelim = [(rank_score(s, it, st), it.published_at, it.id) for it, s, st, _ in mapped.values()]
    keep_ids = select_top(prelim, int(settings["ranking"]["max_items"]) + 20)

    # Stage 5: expected ranges
    vcfg = settings["volatility"]
    tickers: list[str] = []
    for iid in keep_ids:
        for st in mapped[iid][2]:
            tickers.append(yahoo_ticker(st.symbol, st.is_index))
    tickers = list(dict.fromkeys(tickers))[: int(vcfg.get("max_stocks_per_run", 150))]
    if deadline.ok(60):
        prices.fetch(tickers)
    else:
        log.warning("Run-time limit near; skipping price download")
    ranged = 0
    for iid in keep_ids:
        it, s, stocks, _ = mapped[iid]
        for st in stocks:
            df = prices.get(yahoo_ticker(st.symbol, st.is_index))
            if df is None:
                continue
            st.expected_range = expected_range(df, s.severity, s.direction)
            if st.expected_range:
                ranged += 1
            if not st.is_index:
                st.is_penny = is_penny(float(df["Close"].iloc[-1]), st.market_cap_cr)
    stats["stocks_with_range"] = ranged

    # Stage 6: final ranking
    final = [(rank_score(mapped[i][1], mapped[i][0], mapped[i][2]), mapped[i][0].published_at, i)
             for i in keep_ids]
    score_of = {e[2]: e[0] for e in final}
    top_ids = select_top(final)
    digest_items: list[DigestItem] = []
    for rank, iid in enumerate(top_ids, start=1):
        it, s, stocks, unmapped = mapped[iid]
        digest_items.append(DigestItem(
            rank=rank, rank_score=score_of[iid], id=it.id, title=it.title, snippet=it.snippet,
            url=it.url, source=it.source, published_at=it.published_at,
            coverage_count=it.coverage_count, covered_by=it.covered_by, severity=s.severity,
            direction=s.direction, scope=s.scope, event_type=s.event_type,
            surprise_factor=s.surprise_factor, confidence=s.confidence,
            why_it_matters=s.why_it_matters, affected_sectors=s.affected_sectors,
            stocks=stocks, unmapped_companies=unmapped))

    # Market mood (3 lines) from the top items
    from scoring.mood import market_mood
    mood: list[str] = []
    if deadline.ok(30):
        mood = market_mood(judge, context, [d.model_dump(mode="json") for d in digest_items])

    # Evaluate earlier digests against realised prices
    try:
        evaluated = evaluate_previous(now, prices)
        stats["evaluation_rows_added"] = evaluated
    except Exception as exc:  # noqa: BLE001 - evaluation must not block the digest
        log.warning("Evaluation failed: %s", exc)

    stats.update(judge.tracker.summary())
    stats["run_seconds"] = round(deadline.elapsed, 1)
    digest = Digest(trading_date=target.isoformat(), generated_at=now_ist(), window_start=ws,
                    window_end=we, market_mood=mood, india_vix=vix, india_vix_change_pct=vix_chg,
                    nifty_prev_close=nifty_close, events=events, source_stats=source_stats,
                    pipeline_stats=stats, items=digest_items)
    from pipeline.output import write_digest
    day_path, latest = write_digest(digest)
    log.info("Wrote %s and %s (%d items)", day_path.name, latest.name, len(digest_items))
    log.info("LLM spend estimate: $%.4f (%d calls, %d in / %d out / %d cache-read tokens)",
             judge.tracker.usd, judge.tracker.calls, judge.tracker.input_tokens,
             judge.tracker.output_tokens, judge.tracker.cache_read_tokens)
    log.info("Per-source counts: %s", {k: v["count"] for k, v in source_stats.items()})
    log.info("Pipeline stats: %s", stats)
    return 0


def evaluate_previous(now: datetime, prices) -> int:
    from pipeline.evaluation import append_rows, eval_path, evaluate_digest, evaluated_dates, \
        pending_digests
    from pipeline.output import digests_dir, load_digest
    from volatility.ranges import yahoo_ticker
    path = eval_path()
    pending = pending_digests(list(digests_dir().glob("????-??-??.json")), now.date(),
                              evaluated_dates(path))
    total = 0
    for p in pending:
        d = load_digest(p)
        tickers = [yahoo_ticker(s.symbol, s.is_index) for it in d.items for s in it.stocks
                   if s.expected_range]
        prices.fetch(tickers)
        rows = evaluate_digest(d, lambda sym, idx: prices.get(yahoo_ticker(sym, idx)))
        total += append_rows(rows, path)
        log.info("Evaluated digest %s: %d stock rows", d.trading_date, len(rows))
    return total


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="run even on weekends/holidays")
    args = ap.parse_args()
    setup_logging()
    return run(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
