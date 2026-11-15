"""Text and URL helpers."""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "ref", "src", "from", "cmpid", "ocid")
_WS = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return _WS.sub(" ", html.unescape(text)).strip()


def truncate(text: str, max_chars: int = 300) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:-") + "…"


def canonical_url(url: str) -> str:
    """Normalise a URL for dedupe: lowercase host, drop www/amp/tracking params/fragment."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    path = re.sub(r"/amp/?$", "", parts.path)
    path = re.sub(r"^/amp/", "/", path)
    path = path.rstrip("/") or "/"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith(_TRACKING_PREFIXES)]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def normalise_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9%₹$ ]+", " ", t)
    return _WS.sub(" ", t).strip()
