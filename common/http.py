"""HTTP session with browser-like headers, retries and timeouts."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common import config


def make_session(extra_headers: dict[str, str] | None = None, retries: int = 2) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.settings()["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    })
    if extra_headers:
        s.headers.update(extra_headers)
    retry = Retry(total=retries, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def timeout() -> float:
    return float(config.settings().get("http_timeout_seconds", 15))
