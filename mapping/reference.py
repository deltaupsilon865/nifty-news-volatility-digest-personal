"""Download and cache reference data: NSE equity master (EQUITY_L.csv) and the AMFI
average market-cap list. Cached copies are committed to the repo, so a blocked download
(common from cloud IPs) falls back to the last good file."""
from __future__ import annotations

import io
import time
from datetime import date
from pathlib import Path

import pandas as pd

from common import config
from common.http import make_session, timeout
from common.log import get_logger

log = get_logger("mapping.reference")


def _is_stale(path: Path, max_age_days: float) -> bool:
    return not path.exists() or (time.time() - path.stat().st_mtime) > max_age_days * 86400


def refresh_equity_master(force: bool = False) -> Path:
    ref = config.settings()["reference"]
    path = config.resolve(ref["equity_master_path"])
    if not force and not _is_stale(path, ref.get("max_age_days", 7)):
        return path
    try:
        s = make_session({"Referer": "https://www.nseindia.com/"}, retries=1)
        s.get("https://www.nseindia.com/", timeout=timeout())
        resp = s.get(ref["equity_master_url"], timeout=30)
        resp.raise_for_status()
        if b"SYMBOL" not in resp.content[:200]:
            raise ValueError("unexpected EQUITY_L.csv content")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        log.info("Refreshed NSE equity master (%d bytes)", len(resp.content))
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not refresh EQUITY_L.csv (%s); using cached copy", exc)
    return path


def amfi_candidate_urls(today: date | None = None) -> list[str]:
    ref = config.settings()["reference"]
    if ref.get("amfi_url"):
        return [ref["amfi_url"]]
    today = today or date.today()
    stamps: list[str] = []
    year = today.year
    for y in (year, year - 1, year - 2):
        stamps += [f"31Dec{y}", f"30Jun{y}"]
    tmpl = ref["amfi_url_template"]
    return [tmpl.format(stamp=s) for s in stamps]


def refresh_amfi(force: bool = False) -> Path:
    ref = config.settings()["reference"]
    path = config.resolve(ref["amfi_path"])
    if not force and not _is_stale(path, 30):
        return path
    s = make_session(retries=0)
    for url in amfi_candidate_urls():
        try:
            resp = s.get(url, timeout=30)
            if resp.status_code == 200 and "spreadsheet" in resp.headers.get("content-type", ""):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(resp.content)
                log.info("Refreshed AMFI market-cap list from %s", url)
                return path
        except Exception:  # noqa: BLE001
            continue
    log.warning("Could not refresh AMFI list; using cached copy at %s", path)
    if path.exists():
        path.touch()  # avoid retrying on every run for 30 days
    return path


def load_equity_master(path: Path | None = None) -> pd.DataFrame:
    path = path or config.resolve(config.settings()["reference"]["equity_master_path"])
    df = pd.read_csv(path)
    df.columns = [c.strip().upper() for c in df.columns]
    df = df.rename(columns={"NAME OF COMPANY": "NAME", "ISIN NUMBER": "ISIN"})
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    df["NAME"] = df["NAME"].astype(str).str.strip()
    return df[["SYMBOL", "NAME", "SERIES", "ISIN"]]


def load_amfi(path: Path | None = None) -> pd.DataFrame:
    """Return DataFrame with columns RANK, NAME, ISIN, NSE_SYMBOL, MCAP_CR, CATEGORY."""
    path = path or config.resolve(config.settings()["reference"]["amfi_path"])
    raw = pd.read_excel(path, header=None)
    header_row = next(i for i in range(10) if "ISIN" in [str(x).strip() for x in raw.iloc[i]])
    df = raw.iloc[header_row + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[header_row]]
    cols = {c.lower(): c for c in df.columns}

    def pick(*keys: str) -> str:
        for k in cols:
            if all(part in k for part in keys):
                return cols[k]
        raise KeyError(keys)

    out = pd.DataFrame({
        "RANK": pd.to_numeric(df[pick("sr")], errors="coerce"),
        "NAME": df[pick("company")].astype(str).str.strip(),
        "ISIN": df[pick("isin")].astype(str).str.strip(),
        "NSE_SYMBOL": df[pick("nse symbol")].astype(str).str.strip(),
        "MCAP_CR": pd.to_numeric(df[pick("average of all")], errors="coerce"),
        "CATEGORY": df[pick("categori")].astype(str).str.strip(),
    })
    out = out.dropna(subset=["RANK"])
    out["RANK"] = out["RANK"].astype(int)
    out.loc[out["NSE_SYMBOL"].isin(["-", "nan", ""]), "NSE_SYMBOL"] = None
    return out.reset_index(drop=True)


def amfi_period_label(path: Path | None = None) -> str:
    path = path or config.resolve(config.settings()["reference"]["amfi_path"])
    try:
        title = str(pd.read_excel(path, header=None, nrows=1).iloc[0, 0])
        return title.split("ended")[-1].strip() if "ended" in title else title
    except Exception:  # noqa: BLE001
        return "unknown"


def read_bytes_frame(content: bytes) -> pd.DataFrame:  # helper for tests
    return pd.read_csv(io.BytesIO(content))
