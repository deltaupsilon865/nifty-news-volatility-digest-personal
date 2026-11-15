"""Logging setup shared by the pipeline."""
from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str | None = None) -> None:
    level = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    for noisy in ("httpx", "urllib3", "yfinance", "peewee", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
