"""Gemeinsame Helfer für die Such-Provider (HTTP + Titel/Firma-Heuristik)."""

from __future__ import annotations

import html
import re

import requests

COMPANY_SUFFIX = (
    "gmbh", "ag", "se", "kg", "group", "technologies", "engineering", "robotics",
    "systems", "inc", "ltd", "llc", "space", "mobility", "aerospace", "defence",
    "defense", "electronics", "technik", "consulting", "consultants", "solutions",
    "scientific", "semiconductor",
)

# Ganzwort-Treffer, damit z. B. „se" nicht in „Sensorik" oder „space" nicht in „dSPACE" matcht.
_SUFFIX_RE = re.compile(r"\b(" + "|".join(COMPANY_SUFFIX) + r")\b")


def fetch(url: str, params: dict | None = None, headers: dict | None = None,
          timeout: int = 15) -> requests.Response:
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


def clean_html(fragment: str) -> str:
    """Entfernt Tags und dekodiert HTML-Entities aus einem HTML-Schnipsel."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def split_title_firma(title: str) -> tuple[str, str]:
    """Best-Effort-Aufteilung eines Ergebnistitels in (Stellentitel, Firma).

    Übliche Muster: ``"Titel - Firma"``, ``"Firma - Titel"``, ``"Titel bei Firma"``.
    """
    t = (title or "").strip()
    if not t:
        return "", ""

    if " bei " in t:
        head, _, rest = t.partition(" bei ")
        return head.strip(), _trim_location(rest)

    parts = re.split(r"\s+[-–—|]\s+", t)
    if len(parts) >= 2:
        # Segment mit Firmen-Suffix gewinnt als Firma.
        for i, part in enumerate(parts):
            if _SUFFIX_RE.search(part.lower()):
                firma = part.strip()
                titel = " - ".join(p for j, p in enumerate(parts) if j != i).strip()
                return titel, firma
        # Fallback: letztes Segment als Firma (häufiges "Titel - Firma"-Muster).
        return " - ".join(parts[:-1]).strip(), parts[-1].strip()

    return t, ""


def _trim_location(rest: str) -> str:
    return re.split(r"\s+[-–|(]", rest.strip())[0].strip()
