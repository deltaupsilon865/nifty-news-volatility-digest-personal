"""Stage 7: write the digest JSON files the web dashboard reads."""
from __future__ import annotations

import json
from pathlib import Path

from common import config
from common.models import Digest


def digests_dir() -> Path:
    return config.DATA_DIR / "digests"


def write_digest(digest: Digest, data_dir: Path | None = None) -> tuple[Path, Path]:
    data_dir = data_dir or config.DATA_DIR
    ddir = data_dir / "digests"
    ddir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(digest.model_dump(mode="json"), ensure_ascii=False, indent=1)
    day_path = ddir / f"{digest.trading_date}.json"
    latest = data_dir / "latest.json"
    day_path.write_text(text + "\n", encoding="utf-8")
    latest.write_text(text + "\n", encoding="utf-8")
    return day_path, latest


def load_digest(path: Path) -> Digest:
    return Digest.model_validate_json(path.read_text(encoding="utf-8"))


def list_digest_dates(data_dir: Path | None = None) -> list[str]:
    ddir = (data_dir or config.DATA_DIR) / "digests"
    return sorted((p.stem for p in ddir.glob("????-??-??.json")), reverse=True)


def latest_published_digest(on_or_before: str, data_dir: Path | None = None) -> Digest | None:
    """The newest digest with at least one item for a session on or before `on_or_before`.
    Empty or unreadable digests (failed runs) are skipped."""
    ddir = (data_dir or config.DATA_DIR) / "digests"
    for d in list_digest_dates(data_dir):
        if d > on_or_before:
            continue
        try:
            digest = load_digest(ddir / f"{d}.json")
        except Exception:  # noqa: BLE001
            continue
        if digest.items:
            return digest
    return None
