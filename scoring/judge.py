"""Stage 3: LLM judge. Scores news items in batches with a strict JSON schema."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any

from common import config
from common.log import get_logger
from common.models import EventEntry, NewsItem, Score
from scoring.cost import CostTracker, max_daily_usd
from scoring.schemas import SCORE_SCHEMA, validate_scores

log = get_logger("scoring")


class BudgetExceeded(RuntimeError):
    pass


def scoring_model() -> str:
    sc = config.settings()["scoring"]
    return config.env(sc.get("model_env", "SCORING_MODEL"), sc["default_model"])


def make_client():
    import anthropic

    key = config.env("ANTHROPIC_API_KEY")
    if not key:  # an unset GitHub secret arrives as "", which the SDK would accept
        raise RuntimeError("ANTHROPIC_API_KEY is not set (add it as a GitHub Actions secret)")
    return anthropic.Anthropic(api_key=key, max_retries=4, timeout=120.0)


def _rubric() -> str:
    return (config.PROMPTS_DIR / "scoring.md").read_text(encoding="utf-8")


def day_context(trading_date: date, events: list[EventEntry], vix: float | None = None,
                catchup: tuple[datetime, datetime, int] | None = None) -> str:
    lines = [f"## Today's context\n\nTrading session: {trading_date:%A %d %B %Y} (NSE). "
             "Score every item for its likely impact from this session's open."]
    if catchup:
        start, end, missed = catchup
        lines.append(
            f"CATCH-UP DIGEST: no digest was produced for {missed} trading session(s), so the items "
            f"span {start:%a %d %b %H:%M} to {end:%a %d %b %H:%M} IST. Each item's published_at "
            "shows its age. Still score severity for the upcoming session's open: news that "
            "markets have already traded through in later sessions is largely priced in and "
            "should be scored lower, unless it is still developing, has a pending trigger "
            "(record date, vote, deadline, results, policy action) or keeps driving the trend.")
    if vix is not None:
        lines.append(f"India VIX at last close: {vix:.2f}.")
    if events:
        lines.append("Scheduled events today:")
        lines += [f"- {e.name} ({e.importance} importance)" for e in events]
    else:
        lines.append("No major scheduled events today.")
    return "\n".join(lines)


def _item_payload(it: NewsItem, exchange_company: str | None) -> dict[str, Any]:
    d: dict[str, Any] = {"id": it.id, "title": it.title, "snippet": it.snippet,
                         "source": it.source,
                         "published_at": it.published_at.strftime("%Y-%m-%d %H:%M"),
                         "coverage_count": it.coverage_count}
    if exchange_company:
        d["exchange_company"] = exchange_company
    return d


def _response_json(resp) -> dict:
    if resp.stop_reason == "refusal":
        raise ValueError("model refused this batch")
    if resp.stop_reason == "max_tokens":
        raise ValueError("reply truncated at max_tokens")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    return json.loads(text)


class Judge:
    def __init__(self, client=None, model: str | None = None, tracker: CostTracker | None = None):
        self.client = client or make_client()
        self.model = model or scoring_model()
        self.tracker = tracker or CostTracker(self.model)
        sc = config.settings()["scoring"]
        self.batch_size = int(sc.get("batch_size", 15))
        self.max_retries = int(sc.get("max_retries", 3))
        self.effort = sc.get("effort", "low")
        self.max_tokens = int(sc.get("max_tokens", 8000))
        self.budget = max_daily_usd()

    def _system(self, context: str) -> list[dict]:
        # Rubric first (identical every call -> cached), day context second (cached per run).
        return [
            {"type": "text", "text": _rubric(), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
        ]

    def _call(self, system: list[dict], items: list[NewsItem],
              hints: dict[str, str]) -> dict:
        if self.tracker.usd >= self.budget:
            raise BudgetExceeded(f"LLM spend ${self.tracker.usd:.3f} reached cap ${self.budget:.2f}")
        payload = [_item_payload(it, hints.get(it.id)) for it in items]
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            output_config={"effort": self.effort,
                           "format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
            messages=[{"role": "user", "content":
                       "Score these news items:\n" + json.dumps(payload, ensure_ascii=False)}],
        )
        self.tracker.add(resp.usage)
        return _response_json(resp)

    def score_batch(self, system: list[dict], items: list[NewsItem],
                    hints: dict[str, str]) -> dict[str, Score]:
        pending = {it.id: it for it in items}
        results: dict[str, Score] = {}
        for attempt in range(1, self.max_retries + 1):
            if not pending:
                break
            try:
                payload = self._call(system, list(pending.values()), hints)
                scores, problems = validate_scores(payload, set(pending))
                results.update(scores)
                for sid in scores:
                    pending.pop(sid, None)
                if problems:
                    log.debug("Batch attempt %d problems: %s", attempt, problems[:3])
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - retry malformed output / transient errors
                log.warning("Scoring attempt %d failed: %s", attempt, exc)
        if pending:
            log.warning("Gave up scoring %d items after %d attempts", len(pending), self.max_retries)
        return results

    def score(self, items: list[NewsItem], context: str,
              hints: dict[str, str] | None = None, workers: int = 4) -> dict[str, Score]:
        hints = hints or {}
        system = self._system(context)
        batches = [items[i:i + self.batch_size] for i in range(0, len(items), self.batch_size)]
        log.info("Scoring %d items in %d batches with %s", len(items), len(batches), self.model)
        results: dict[str, Score] = {}
        if not batches:
            return results
        # First batch alone so later parallel calls hit the prompt cache.
        results.update(self.score_batch(system, batches[0], hints))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self.score_batch, system, b, hints) for b in batches[1:]]
            for f in futures:
                try:
                    results.update(f.result())
                except BudgetExceeded as exc:
                    log.error("%s - remaining batches skipped", exc)
        log.info("Scored %d/%d items; spend so far $%.4f", len(results), len(items), self.tracker.usd)
        return results
