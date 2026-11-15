"""Scoring tests use a fake Anthropic client (no live calls)."""
import json
from types import SimpleNamespace

from helpers import item

from scoring.cost import CostTracker
from scoring.judge import Judge
from scoring.schemas import validate_scores


def _score(i, **kw):
    base = {"id": i, "severity": 5, "direction": "bullish", "scope": "single_stock",
            "event_type": "order_win", "affected_companies": [{"name": "Acme", "relation": "direct"}],
            "affected_sectors": ["Capital Goods & Infra"], "surprise_factor": "medium",
            "confidence": "high", "why_it_matters": "Big order."}
    base.update(kw)
    return base


class FakeClient:
    """Returns scripted replies; records calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500,
                                  cache_read_input_tokens=2000, cache_creation_input_tokens=0),
        )


def test_validate_clamps_and_dedupes():
    payload = {"scores": [_score("a", severity=14, affected_companies=[
        {"name": "Acme", "relation": "direct"}, {"name": "acme", "relation": "direct"}],
        why_it_matters="x" * 400), _score("zzz")]}
    scores, problems = validate_scores(payload, {"a", "b"})
    assert scores["a"].severity == 10
    assert len(scores["a"].affected_companies) == 1
    assert len(scores["a"].why_it_matters) <= 320
    assert any("unexpected id" in p for p in problems)
    assert any("missing 1" in p for p in problems)


def test_validate_rejects_bad_enum():
    scores, problems = validate_scores({"scores": [_score("a", direction="sideways")]}, {"a"})
    assert scores == {} and problems


def test_judge_retries_malformed_and_missing_items():
    items = [item("Acme wins order"), item("Beta results")]
    ids = [it.id for it in items]
    client = FakeClient([
        "not json at all",                       # attempt 1: malformed
        {"scores": [_score(ids[0])]},             # attempt 2: one missing
        {"scores": [_score(ids[1], severity=3)]}, # attempt 3: the missing one
    ])
    judge = Judge(client=client, model="claude-haiku-5-5", tracker=CostTracker("claude-haiku-5-5"))
    out = judge.score(items, context="ctx")
    assert set(out) == set(ids)
    assert out[ids[1]].severity == 3
    assert len(client.calls) == 3
    # second retry only re-sends the missing item
    assert ids[0] not in client.calls[2]["messages"][0]["content"]
    # rubric is cached
    assert client.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_cost_tracker_math():
    t = CostTracker("claude-haiku-5-5")
    t.add(SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000,
                          cache_read_input_tokens=0, cache_creation_input_tokens=0))
    assert abs(t.usd - 0.60) < 1e-9
