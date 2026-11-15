"""Token accounting and spend estimate for the daily LLM budget."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from common import config


@dataclass
class CostTracker:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, usage) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
            self.cache_read_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            self.cache_write_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

    def prices(self) -> dict[str, float]:
        table = config.settings()["scoring"]["pricing"]
        if self.model in table:
            return table[self.model]
        # Unknown model: assume Sonnet-level prices so the estimate errs high.
        return table.get("claude-sonnet-5-5", {"input": 2.0, "output": 10.0,
                                               "cache_read": 0.1, "cache_write": 2.5})

    @property
    def usd(self) -> float:
        p = self.prices()
        return (self.input_tokens * p["input"] + self.output_tokens * p["output"]
                + self.cache_read_tokens * p.get("cache_read", p["input"] * 0.1)
                + self.cache_write_tokens * p.get("cache_write", p["input"] * 1.25)) / 1_000_000

    def summary(self) -> dict[str, float | int | str]:
        return {"model": self.model, "llm_calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "cache_read_tokens": self.cache_read_tokens,
                "cache_write_tokens": self.cache_write_tokens, "llm_cost_usd": round(self.usd, 4)}


def max_daily_usd() -> float:
    sc = config.settings()["scoring"]
    return float(config.env(sc.get("max_daily_usd_env", "MAX_DAILY_LLM_USD"),
                            str(sc.get("default_max_daily_usd", 1.0))))
