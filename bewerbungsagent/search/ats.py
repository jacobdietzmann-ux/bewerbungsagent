"""Stellen direkt aus den Bewerber-Systemen (ATS) der Zielunternehmen.

Warum das nötig ist: die Jobbörsen liefern nur, was sie indexiert haben, und die
allgemeinen Suchmaschinen sind für diesen Zweck unbrauchbar geworden — live
geprüft: DuckDuckGo 0 Treffer, Bing nur ``bing.com/ck/a``-Redirects zu
branchenfremden Firmen, Mojeek ein Captcha. Die Karriereseiten selbst haben
dagegen **öffentliche JSON-Endpunkte**: kein Scraping, keine Blockade, und der
vollständige Anzeigentext kommt mit — der Browser-Fetch entfällt für diese
Stellen.

Live verifiziert sind Greenhouse, Lever und Ashby. Weitere Systeme (Personio,
SmartRecruiters, …) sind bewusst nicht implementiert, solange ihr
Antwortformat nicht mit echten Daten geprüft wurde.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from ..commute import is_near_munich
from ..profile import normalize
from .base import clean_html

# Ab dieser Länge gilt ein Beschreibungstext als brauchbar. Kürzere „Inhalte"
# sind meist nur ein Satz Verweis und würden das Scoring verfälschen.
_MIN_DESCRIPTION = 200

_TIMEOUT = 25


def _ua(user_agent: str | None) -> dict[str, str]:
    return {"User-Agent": user_agent or "Bewerbungsagent/1.0 "
            "(+https://github.com/jacobdietzmann-ux/bewerbungsagent)"}


def _texts(html_or_text: str | None) -> str:
    """Beschreibung als Klartext (HTML wird von Tags befreit)."""
    text = clean_html(html_or_text or "")
    return re.sub(r"\s+", " ", text).strip()


def _job(firma: str, titel: str, ort: str, url: str, beschreibung: str) -> dict:
    desc = _texts(beschreibung)
    return {
        "titel": (titel or "").strip(),
        "firma": firma,
        "ort": (ort or "").strip(),
        "url": (url or "").strip(),
        "quelle": "ATS",
        "snippet": desc[:400],
        # Der Volltext ersetzt hier den Browser-Fetch: ``fetch_descriptions``
        # überspringt Stellen, die schon eine Beschreibung haben.
        "beschreibung": desc if len(desc) >= _MIN_DESCRIPTION else "",
    }


# --------------------------------------------------------------------------
# Systeme
# --------------------------------------------------------------------------

def greenhouse(board: str, firma: str, user_agent: str | None = None) -> list[dict]:
    """Greenhouse: ``content=true`` liefert die Anzeige gleich mit."""
    r = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
        params={"content": "true"}, headers=_ua(user_agent), timeout=_TIMEOUT,
    )
    r.raise_for_status()
    jobs = []
    for raw in (r.json() or {}).get("jobs") or []:
        jobs.append(_job(
            firma=firma,
            titel=raw.get("title") or "",
            ort=(raw.get("location") or {}).get("name") or "",
            url=raw.get("absolute_url") or "",
            beschreibung=raw.get("content") or "",
        ))
    return jobs


def lever(board: str, firma: str, user_agent: str | None = None) -> list[dict]:
    """Lever: eine Liste von Postings, ``descriptionPlain`` ist bereits Text."""
    r = requests.get(
        f"https://api.lever.co/v0/postings/{board}",
        params={"mode": "json"}, headers=_ua(user_agent), timeout=_TIMEOUT,
    )
    r.raise_for_status()
    jobs = []
    for raw in r.json() or []:
        categories = raw.get("categories") or {}
        jobs.append(_job(
            firma=firma,
            titel=raw.get("text") or "",
            ort=categories.get("location") or "",
            url=raw.get("hostedUrl") or "",
            beschreibung=raw.get("descriptionPlain") or raw.get("description") or "",
        ))
    return jobs


def ashby(board: str, firma: str, user_agent: str | None = None) -> list[dict]:
    """Ashby: ``{"jobs": [...]}`` mit ``descriptionPlain`` und ``jobUrl``."""
    r = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{board}",
        headers=_ua(user_agent), timeout=_TIMEOUT,
    )
    r.raise_for_status()
    jobs = []
    for raw in (r.json() or {}).get("jobs") or []:
        if raw.get("isListed") is False:
            continue
        jobs.append(_job(
            firma=firma,
            titel=raw.get("title") or "",
            ort=raw.get("location") or "",
            url=raw.get("jobUrl") or raw.get("applyUrl") or "",
            beschreibung=raw.get("descriptionPlain") or raw.get("descriptionHtml") or "",
        ))
    return jobs


BOARDS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


# --------------------------------------------------------------------------
# Board aus einer vorhandenen Anzeigen-URL ableiten
# --------------------------------------------------------------------------

# Host-Muster -> (System, Regex für den Board-Namen im Pfad). Damit braucht eine
# Firma, die schon mit einer Anzeige im Bestand ist, keinen Konfigurationseintrag:
# aus ``job-boards.eu.greenhouse.io/skdse/jobs/4988…`` wird ``greenhouse:skdse``.
_BOARD_PATTERNS: tuple[tuple[re.Pattern[str], str, re.Pattern[str]], ...] = (
    (re.compile(r"(^|\.)greenhouse\.io$"), "greenhouse", re.compile(r"^/([^/]+)")),
    (re.compile(r"(^|\.)lever\.co$"), "lever", re.compile(r"^/([^/]+)")),
    (re.compile(r"(^|\.)ashbyhq\.com$"), "ashby", re.compile(r"^/([^/]+)")),
)


def detect_board(url: str) -> tuple[str, str] | None:
    """``(ats, board)`` aus einer Anzeigen-URL, sonst ``None``."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    for host_re, ats, path_re in _BOARD_PATTERNS:
        if not host_re.search(host):
            continue
        match = path_re.search(path)
        if match:
            return ats, match.group(1)
    return None


def boards_from_jobs(jobs: list[dict]) -> list[dict]:
    """Board-Liste aus vorhandenen Anzeigen ableiten (dedupliziert, sortiert).

    Liefert ``[{"firma": …, "ats": …, "board": …}, …]``. Das ist der Weg, ohne
    Pflegeaufwand an die Karriereseiten der Firmen zu kommen, die bereits im
    Bestand sind.
    """
    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for job in jobs:
        found = detect_board(job.get("url") or "")
        if not found:
            continue
        ats, board = found
        if (ats, board) in seen:
            continue
        seen.add((ats, board))
        result.append({"firma": job.get("firma") or board, "ats": ats, "board": board})
    return sorted(result, key=lambda b: (b["ats"], b["board"]))


# --------------------------------------------------------------------------
# Abfrage
# --------------------------------------------------------------------------

def search(boards: list[dict], *, user_agent: str | None = None,
           only_near_munich: bool = True) -> tuple[list[dict], list[str]]:
    """Fragt alle konfigurierten Boards ab.

    ``only_near_munich`` filtert direkt nach der Abfrage: eine Firma mit 141
    Stellen weltweit würde sonst 141 Geocoding-Aufrufe kosten, nur um danach
    festzustellen, dass 130 zu weit entfernt sind.

    Rückgabe: ``(jobs, fehler)`` — ein defektes Board stoppt die anderen nicht.
    """
    jobs: list[dict] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for entry in boards or []:
        ats = str(entry.get("ats") or "").strip().lower()
        board = str(entry.get("board") or "").strip()
        firma = str(entry.get("firma") or board).strip()
        fetch = BOARDS.get(ats)
        if not fetch or not board:
            errors.append(f"ats ({ats or '?'}:{board or '?'}): unbekanntes System")
            continue
        try:
            found = fetch(board, firma, user_agent=user_agent)
        except requests.RequestException as exc:
            errors.append(f"ats ({firma}): {type(exc).__name__}")
            continue
        kept = 0
        for job in found:
            if not job.get("titel") or not job.get("url"):
                continue
            identity = (normalize(job["firma"]), normalize(job["titel"]))
            if identity in seen:
                continue
            if only_near_munich and not is_near_munich(job.get("ort") or ""):
                continue
            seen.add(identity)
            jobs.append(job)
            kept += 1
        errors.append(f"ats ({firma}): {len(found)} gefunden, {kept} im Umkreis")
    return jobs, errors
