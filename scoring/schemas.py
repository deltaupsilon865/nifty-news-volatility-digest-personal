"""JSON schema sent to the model (structured outputs) and Pydantic validation of replies."""
from __future__ import annotations

from typing import get_args

from pydantic import BaseModel, ValidationError

from common.models import AffectedCompany, Direction, EventType, Level, Score, Scope

_DIRECTIONS = list(get_args(Direction))
_SCOPES = list(get_args(Scope))
_EVENT_TYPES = list(get_args(EventType))
_LEVELS = list(get_args(Level))

SCORE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "integer"},
                    "direction": {"type": "string", "enum": _DIRECTIONS},
                    "scope": {"type": "string", "enum": _SCOPES},
                    "event_type": {"type": "string", "enum": _EVENT_TYPES},
                    "affected_companies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "relation": {"type": "string", "enum": ["direct", "indirect"]},
                            },
                            "required": ["name", "relation"],
                            "additionalProperties": False,
                        },
                    },
                    "affected_sectors": {"type": "array", "items": {"type": "string"}},
                    "surprise_factor": {"type": "string", "enum": _LEVELS},
                    "confidence": {"type": "string", "enum": _LEVELS},
                    "why_it_matters": {"type": "string"},
                },
                "required": ["id", "severity", "direction", "scope", "event_type",
                             "affected_companies", "affected_sectors", "surprise_factor",
                             "confidence", "why_it_matters"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scores"],
    "additionalProperties": False,
}

MOOD_SCHEMA: dict = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
    "required": ["lines"],
    "additionalProperties": False,
}


class BatchScores(BaseModel):
    scores: list[dict]


def validate_scores(payload: dict, expected_ids: set[str]) -> tuple[dict[str, Score], list[str]]:
    """Validate a model reply. Returns (valid scores by id, list of problems).
    Out-of-range numbers are clamped and over-long text trimmed rather than rejected."""
    problems: list[str] = []
    out: dict[str, Score] = {}
    try:
        batch = BatchScores.model_validate(payload)
    except ValidationError as exc:
        return {}, [f"bad envelope: {exc.errors()[:1]}"]
    for raw in batch.scores:
        sid = str(raw.get("id", ""))
        if sid not in expected_ids:
            problems.append(f"unexpected id {sid!r}")
            continue
        fixed = dict(raw)
        try:
            fixed["severity"] = max(1, min(10, int(fixed.get("severity", 1))))
        except (TypeError, ValueError):
            problems.append(f"{sid}: bad severity")
            continue
        why = str(fixed.get("why_it_matters", "")).strip()
        fixed["why_it_matters"] = why[:317] + "..." if len(why) > 320 else why
        companies = []
        seen: set[str] = set()
        for c in fixed.get("affected_companies") or []:
            try:
                ac = AffectedCompany.model_validate(c)
            except ValidationError:
                continue
            key = ac.name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                companies.append(ac)
        fixed["affected_companies"] = companies
        fixed["affected_sectors"] = list(dict.fromkeys(
            s.strip() for s in (fixed.get("affected_sectors") or []) if str(s).strip()))
        try:
            out[sid] = Score.model_validate(fixed)
        except ValidationError as exc:
            problems.append(f"{sid}: {exc.errors()[:1]}")
    missing = expected_ids - set(out)
    if missing:
        problems.append(f"missing {len(missing)} ids")
    return out, problems
