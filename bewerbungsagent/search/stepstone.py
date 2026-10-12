"""StepStone-Provider: parse einzelne Stellenangebote direkt von der Jobbörse.

Kein API-Key nötig; nutzt die öffentliche HTML-Suche von StepStone
(``https://www.stepstone.de/jobs/<suchbegriff>/in-<ort>``) und extrahiert die
einzelnen Job-Karten (Titel, Firma, Ort, Detail-URL).
"""

from __future__ import annotations

import re

from .base import clean_html, fetch

BASE = "https://www.stepstone.de"

_TITLE_RE = re.compile(r'<a\s[^>]*data-at="job-item-title"[^>]*>')
_HREF_RE = re.compile(r'href="([^"]+)"')
_COMPANY_RE = re.compile(r'data-at="job-item-company-name"[^>]*>', re.DOTALL)
_LOCATION_RE = re.compile(r'data-at="job-item-location"[^>]*>', re.DOTALL)
_TEXT_SPAN_RE = re.compile(r'<span[^>]*data-genesis-element="TEXT"[^>]*>(.*?)</span>', re.DOTALL)
_STYLE_SVG_RE = re.compile(r'<(style|svg|script)\b.*?</\1>', re.DOTALL | re.IGNORECASE)


def _slug(text: str) -> str:
    """StepStone-Slug: kleinschreiben, Umlaute auflösen, Sonderzeichen -> Bindestrich."""
    t = text.lower().replace("ß", "ss")
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def _clean_title(raw: str) -> str:
    raw = _STYLE_SVG_RE.sub("", raw)
    return clean_html(raw)


def _next_text_span(html: str, pos: int) -> str:
    """Text des nächsten ``<span data-genesis-element="TEXT">`` nach ``pos``."""
    for m in _TEXT_SPAN_RE.finditer(html, pos):
        text = clean_html(m.group(1))
        if text:
            return text
    return ""


def search(query: str, location: str = "München", max_results: int = 8,
           timeout: int = 15, user_agent: str = "Mozilla/5.0") -> list[dict]:
    url = f"{BASE}/jobs/{_slug(query)}/in-{_slug(location)}"
    headers = {"User-Agent": user_agent, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
    resp = fetch(url, headers=headers, timeout=timeout)
    text = resp.text

    # Titel-Anker (nur echte Detail-Links).
    title_spans: list[tuple[int, int, str, str]] = []  # (start, end, href, title)
    for m in _TITLE_RE.finditer(text):
        href_m = _HREF_RE.search(m.group(0))
        href = href_m.group(1) if href_m else ""
        if "stellenangebote--" not in href:
            continue
        close = text.find("</a>", m.end())
        title = _clean_title(text[m.end():close])
        if not title or "box-sizing" in title or "{" in title:
            continue
        title_spans.append((m.start(), close, href, title))

    # Firma- und Ort-Text mit Positionen.
    company_hits = [(m.start(), _next_text_span(text, m.end())) for m in _COMPANY_RE.finditer(text)]
    location_hits = [(m.start(), _next_text_span(text, m.end())) for m in _LOCATION_RE.finditer(text)]

    results: list[dict] = []
    for pos, _, href, title in title_spans:
        firma = _nearest_after(company_hits, pos)
        ort = _nearest_after(location_hits, pos)
        full_url = href if href.startswith("http") else BASE + href
        results.append({
            "titel": title,
            "url": full_url,
            "firma": firma,
            "ort": ort,
            "snippet": "",
            "quelle": "StepStone",
        })
        if len(results) >= max_results:
            break
    return results


def _nearest_after(hits: list[tuple[int, str]], pos: int) -> str:
    best = ""
    for p, text in hits:
        if p > pos:
            best = text
            break
    return best
