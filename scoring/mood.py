"""Three-line market mood summary written by the LLM from the top-ranked items."""
from __future__ import annotations

import json

from common import config
from common.log import get_logger
from scoring.judge import Judge, _response_json
from scoring.schemas import MOOD_SCHEMA

log = get_logger("scoring.mood")


def market_mood(judge: Judge, context: str, top_items: list[dict]) -> list[str]:
    if not top_items:
        return ["Quiet morning: no high-impact news found since the last close."]
    try:
        prompt = (config.PROMPTS_DIR / "mood.md").read_text(encoding="utf-8")
        compact = [{k: it[k] for k in ("title", "severity", "direction", "scope", "why_it_matters")}
                   for it in top_items[:15]]
        resp = judge.client.messages.create(
            model=judge.model,
            max_tokens=2000,
            system=prompt,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": MOOD_SCHEMA}},
            messages=[{"role": "user", "content": f"{context}\n\nTop items:\n"
                       + json.dumps(compact, ensure_ascii=False)}],
        )
        judge.tracker.add(resp.usage)
        lines = [str(x).strip() for x in _response_json(resp).get("lines", []) if str(x).strip()]
        return lines[:3]
    except Exception as exc:  # noqa: BLE001 - the digest is still useful without the mood box
        log.warning("Market mood generation failed: %s", exc)
        return []
