"""Glassdoor (DE) — Browser-Provider; die Seite blockt jeden einfachen HTTP-Client.

Live vermessen am 27.10.2026 (Chromium 141, headless, de-DE):

- **HTTP geht nicht.** ``requests`` bekommt auf jede Such-URL HTTP 403 mit
  Captcha-Seite (12 kB HTML, 0 Treffer). Auch ``web_extract``-artige Abrufe
  scheitern. Nur ein echter Browser rendert die Liste.
- **Kein JSON-Endpunkt.** Der Netzwerk-Mitschnitt beim Laden liefert **0**
  XHR-/Fetch-Antworten mit Job-Daten — die Liste kommt server-gerendert.
- **Keine Paginierung.** 30 Karten je Seite, kein Pager, kein „Show more",
  Scrollen (auch im Listen-Container) lädt nichts nach. Die Trefferzahl in der
  Überschrift („49 Jobs") ist größer als das, was je Seite erreichbar ist.
- **Fremde Query-Parameter zerstören die Seite:** ``?page=2``, ``?pageNum=2``,
  ``?p=2``, ``?offset=30`` … liefern **0 Karten**. Erlaubt sind nur
  ``radius``, ``minSalary``, ``maxSalary``, ``sortBy``, ``fromAge``.
- **Ein Kontext = eine Anfrage.** Nach der ersten Suche schaltet Glassdoor auf
  „Nur einen Moment…" (Bot-Check); das löst sich auch nach 20 s Warten nicht.
  Detailseiten im selben Kontext sind sofort geblockt. Deshalb: **je Anfrage
  ein frischer Browser-Kontext**, und Beschreibungen werden nicht nachgeladen.
- **Die fehlenden Treffer bekommt man über Varianten:** andere ``sortBy``-
  Werte und Radien liefern jeweils eine andere 30er-Teilmenge derselben
  Ergebnismenge. Die Vereinigung deckt die Liste ab (im Test: 72 eindeutige
  Stellen aus 20 Varianten für eine Suche mit 49 Treffern).
- **Selektoren:** ``li[data-jobid]`` (ID in ``data-jobid``), Titel-Link
  ``a[href*="job-listing"]``, Firma ``span[class*="compactEmployerName"]``.
  ``data-testid``-Attribute gibt es auf der DE-Seite **nicht** (anders als
  bei XING) — die Klassen sind CSS-Module-Hashes.
- **Kartentext** (Zeilen): Firma, Bewertung, Titel, Ort, Snippet,
  „Kenntnisse und Fähigkeiten: …", „Anzeige", Alter.

Die Detailspalte (Karte anklicken) liefert nur Kopf und „Auf Website des
Arbeitgebers bewerben" (158 Zeichen) — der Anzeigentext bleibt aus. Der
``beschreibung``-Wert ist deshalb der Karten-Snippet, kein Volltext.
"""

from __future__ import annotations

import random
import re
import time
from urllib.parse import quote

from .browser import browser_page, dismiss_consent

BASE = "https://www.glassdoor.de"
JOBS = f"{BASE}/Job"

# Glassdoor-interne Orts-IDs (aus den Links der Trefferseite abgelesen).
CITY_IDS = {
    "münchen": 4990924, "muenchen": 4990924, "munich": 4990924,
    "garching b.münchen": 4991443, "garching": 4991443,
    "oberschleißheim": 4991443, "unterschleißheim": 4991443,
    "ismaning": 4990924, "freising": 4990924,
}

_CONSENT_LABELS = ("Alle akzeptieren", "Akzeptieren", "Einverstanden", "Accept all")

_BLOCK_MARKER = re.compile(r"nur einen moment|just a moment|verify you are human|captcha", re.I)

_MIN_SNIPPET = 80

# Varianten, die jeweils eine andere 30er-Teilmenge derselben Suche liefern.
# (radius, sort) — sortBy-Werte sind die, die Glassdoor akzeptiert.
_VARIANTEN = [
    (None, None), (None, "date_desc"), (None, "date_asc"),
    (10, None), (16, None), (16, "date_desc"), (20, None), (20, "date_desc"),
    (25, None), (30, None),
]

_ZEILEN_UNINTERESSANT = {"anzeige", "einfach bewerben", "easy apply", "30t+", "dringend gesucht"}


def seo_url(term: str, location: str = "München", loc_id: int | None = None) -> str:
    """Glassdoor-SEO-URL bauen: ``<ort>-<begriff>-jobs-SRCH_IL.0,<l>_IC<id>_KO<s>,<e>.htm``.

    ``IL`` ist der Spannen-Index des Ortes im Slug, ``KO`` der des Begriffs —
    beide müssen zeichengenau stimmen, sonst rendert die Seite leer.
    """
    ort = location.strip().lower().replace(" ", "-")
    begriff = term.strip().lower().replace(" ", "-")
    n = len(ort)
    return (f"{JOBS}/{quote(ort)}-{quote(begriff)}-jobs-"
            f"SRCH_IL.0,{n}_IC{loc_id or CITY_IDS.get(location.strip().lower(), 4990924)}"
            f"_KO{n + 1},{n + 1 + len(begriff)}.htm")


def search_url(term: str, location: str = "München", *, radius: int | None = None,
               min_salary: int | None = None, max_salary: int | None = None,
               sort: str | None = None, loc_id: int | None = None) -> str:
    """Such-URL inklusive der erlaubten Filter-Parameter."""
    url = seo_url(term, location, loc_id)
    params = []
    if radius is not None:
        params.append(f"radius={radius}")
    if min_salary is not None:
        params.append(f"minSalary={min_salary}")
    if max_salary is not None:
        params.append(f"maxSalary={max_salary}")
    if sort:
        params.append(f"sortBy={sort}")
    return url + ("?" + "&".join(params) if params else "")


def available() -> bool:
    """True, wenn Playwright samt Chromium nutzbar ist."""
    from .browser import available as _available
    return _available()


def _blockiert(page) -> bool:
    try:
        return bool(_BLOCK_MARKER.search(page.title() or ""))
    except Exception:
        return False


def _karten(page) -> list[dict]:
    """Alle Karten der aktuellen Seite als Rohdaten (ohne Interpretation)."""
    return page.evaluate(
        """() => {
        const out = [];
        for (const li of document.querySelectorAll('li[data-jobid]')) {
            const a = li.querySelector('a[href*="job-listing"]');
            const firmaEl = li.querySelector('span[class*="compactEmployerName"]');
            out.push({
                id: li.dataset.jobid || '',
                titel: a ? (a.innerText || '').trim() : '',
                url: a ? a.href : '',
                firma: firmaEl ? (firmaEl.innerText || '').trim() : '',
                zeilen: (li.innerText || '').split('\\n').map(z => z.trim()).filter(Boolean),
            });
        }
        return out;
    }"""
    )


def _parse(karte: dict, location: str) -> dict | None:
    """Kartentext in Felder zerlegen.

    Die Zeilenfolge ist stabil: Firma?, Bewertung?, Titel, Ort, Snippet,
    „Kenntnisse und Fähigkeiten: …", „Anzeige", Alter. Gesucht wird relativ zum
    Titel, weil davor Badges und Bewertungen stehen können.
    """
    titel = (karte.get("titel") or "").strip()
    if not titel:
        return None
    zeilen = karte.get("zeilen") or []
    try:
        i = next(n for n, z in enumerate(zeilen) if z == titel)
    except StopIteration:
        i = -1

    ort = ""
    snippet = ""
    skills = ""
    gehalt = ""
    if i >= 0:
        rest = [z for z in zeilen[i + 1:] if z.lower() not in _ZEILEN_UNINTERESSANT]
        if rest:
            ort = rest[0]
        # Die Gehaltszeile steht direkt unter dem Ort und ist kein Snippet.
        for z in rest[1:]:
            if "€" in z and not gehalt:
                gehalt = z
            elif not snippet and "kenntnisse und fähigkeiten" not in z.lower():
                snippet = z
            if "kenntnisse und fähigkeiten" in z.lower() or z.lower().startswith("skills"):
                skills = z.split(":", 1)[-1].strip()

    firma = (karte.get("firma") or "").strip()
    if not firma:
        # Fallback: erste Zeile vor dem Titel, die keine Bewertung/Badge ist.
        for z in reversed(zeilen[:max(i, 0)]):
            if not re.fullmatch(r"\d,\d", z) and z.lower() not in _ZEILEN_UNINTERESSANT:
                firma = z
                break

    beschreibung = snippet if len(snippet) >= _MIN_SNIPPET else ""
    if skills:
        beschreibung = (beschreibung + " " + f"Kenntnisse und Fähigkeiten: {skills}").strip()

    return {
        "titel": titel,
        "firma": firma,
        "ort": ort or location,
        "url": karte.get("url", ""),
        "quelle": "Glassdoor",
        "snippet": snippet[:400],
        "beschreibung": beschreibung,
        "gehalt": gehalt,
        "extern_id": karte.get("id", ""),
    }


def _eine_seite(term: str, location: str, *, radius, min_salary, max_salary, sort,
                loc_id, headed: bool) -> list[dict]:
    """Eine Such-URL in einem frischen Kontext abrufen (mehr geht nicht, siehe Modul-Docstring)."""
    url = search_url(term, location, radius=radius, min_salary=min_salary,
                     max_salary=max_salary, sort=sort, loc_id=loc_id)
    with browser_page(headed=headed) as page:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2800)
        if dismiss_consent(page, _CONSENT_LABELS):
            page.wait_for_timeout(1500)
        if _blockiert(page):
            return []
        return _karten(page)


def search(terms: str | list[str], location: str = "München", *,
           max_results: int = 30, with_description: bool = True,
           headed: bool = False, radius: int | None = None,
           min_salary: int | None = None, max_salary: int | None = None,
           variants: bool = True) -> list[dict]:
    """Glassdoor-Treffer für einen oder mehrere Begriffe.

    Je Begriff werden die Varianten (Sortierung × Radius) in eigenen Kontexten
    abgefragt, bis ``max_results`` erreicht ist. ``with_description`` wird
    ignoriert: Volltexte sind ohne Block nicht erreichbar (siehe Modul-Docstring),
    der Snippet dient als Beschreibung.
    """
    if isinstance(terms, str):
        terms = [terms]

    gesammelt: dict[str, dict] = {}
    for term in [t for t in terms if t.strip()]:
        for r, sort in (_VARIANTEN if variants else [(None, None)]):
            if len(gesammelt) >= max_results:
                break
            try:
                roh = _eine_seite(term, location, radius=r if r is not None else radius,
                                  min_salary=min_salary, max_salary=max_salary,
                                  sort=sort, loc_id=None, headed=headed)
            except Exception:
                roh = []
            for karte in roh:
                if karte["id"] in gesammelt:
                    continue
                job = _parse(karte, location)
                if job:
                    gesammelt[karte["id"]] = job
            # Höflichkeitspause — Glassdoor blockt schnelle Folgen sofort.
            time.sleep(1.2 + random.random())

    return list(gesammelt.values())[:max_results]
