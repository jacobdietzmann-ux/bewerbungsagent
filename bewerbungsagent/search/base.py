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
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.exceptions.RequestException as exc:
        # StepStone beantwortet curl zuverlässig (200 in <1 s), während
        # ``requests`` in einen ReadTimeout läuft — vermutlich TLS/HTTP2-
        # Fingerprint. Ohne Fallback lieferte der Provider nur noch 13 statt
        # 120 Treffer pro Lauf und gar keine Anzeigentexte.
        ersatz = _fetch_curl(url, params, headers, timeout)
        if ersatz is None:
            raise exc
        return ersatz


class _CurlResponse:
    """Minimaler Response-Ersatz für den curl-Fallback (nur was Provider nutzen)."""

    def __init__(self, status_code: int, inhalt: bytes):
        self.status_code = status_code
        self.content = inhalt
        self.encoding = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    def json(self):
        import json

        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _fetch_curl(url: str, params: dict | None, headers: dict | None,
                timeout: int) -> "_CurlResponse | None":
    import shutil
    import subprocess
    from urllib.parse import urlencode

    if not shutil.which("curl"):
        return None
    ziel = f"{url}?{urlencode(params)}" if params else url
    befehl = ["curl", "-sS", "--compressed", "--max-time", str(max(5, timeout)),
              "-o", "-", "-w", "\\n%{http_code}"]
    for name, wert in (headers or {}).items():
        befehl += ["-H", f"{name}: {wert}"]
    befehl.append(ziel)
    try:
        lauf = subprocess.run(befehl, capture_output=True, timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError):
        return None
    if lauf.returncode != 0:
        return None
    roh = lauf.stdout
    kopf, _, status = roh.rpartition(b"\n")
    if not status.strip().isdigit():
        return None
    return _CurlResponse(int(status.strip()), kopf)


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
