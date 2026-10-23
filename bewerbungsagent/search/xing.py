"""XING-Jobsuche über einen echten Browser (die Seite rendert nur per JS).

Live verifiziert am 23.10.2026:

- ``GET /jobs/search?keywords=<Begriff>&location=<Ort>`` liefert per HTTP 200
  eine reine JS-Hülle (**0** Anzeigen im HTML). Es gibt kein RSS, keine offene
  JSON-API, und ``POST /graphql`` antwortet nur „Visual GraphQL tools are not
  available in the production environment". Mit Browser: 89 Treffer für
  „Test Engineer" in München.
- Treffer sind ``article[data-testid="job-search-result"]``; der Link steht im
  ersten ``a[href*="/jobs/"]`` (Slug ``/jobs/<ort>-<titel>-<id>``).
- Firmenname: das Logo-``img`` trägt ihn in ``title``/``aria-label``. Fehlt das
  Logo, steht er als zweite Zeile im Kartentext.
- Der Anzeigentext liegt in ``[data-testid="expandable-content"]`` und ist
  **sofort vollständig** (6410 Zeichen im Test) — der „Show more"-Knopf ändert
  die Länge nicht, er steuert nur die Anzeige.
- Paginierung: Knopf „Show more", je Klick 20 weitere Treffer. Nach dem Klick
  auf „Alle akzeptieren" (Consent) ist der Knopf klickbar.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .browser import browser_page, dismiss_consent

BASE = "https://www.xing.com"
_MIN_DESCRIPTION = 200
_JOBS_PER_KLICK = 20
_MAX_KLICKS = 5

_CONSENT_LABELS = ("Alle akzeptieren", "Accept all", "Akzeptieren", "Einverstanden")

# Badge-Texte, die im Kartentext **vor** dem Titel stehen und nicht als Firma
# oder Ort missverstanden werden dürfen.
_BADGES = {"urgently hiring", "dringend gesucht", "zu den ersten gehörigen"}

# Der Kartentext hat eine feste Zeilenfolge: Badge?, Titel, Firma, Ort, …


def search_url(term: str, location: str = "München") -> str:
    """Such-URL für einen Begriff und einen Ort."""
    params = f"keywords={quote(term, safe='')}"
    if location:
        params += f"&location={quote(location, safe='')}"
    return f"{BASE}/jobs/search?{params}"


def available() -> bool:
    """True, wenn Playwright samt Chromium nutzbar ist."""
    from .browser import available as _available
    return _available()


def _karten(page) -> list[dict]:
    """Alle aktuell geladenen Treffer aus der DOM lesen.

    Firma und Ort werden **relativ zum Titel** gelesen: im Kartentext steht
    zuerst optional ein Badge („Urgently hiring"), dann Titel, Firma, Ort. Eine
    Suche nach „erste Zeile in Title-Case" greift dagegen den Badge ab — im Test
    landete „Dringend gesucht" als Ort im Datensatz.
    """
    return page.evaluate(
        """() => {
        const out = [];
        for (const art of document.querySelectorAll('article[data-testid="job-search-result"]')) {
            const link = art.querySelector('a[href*="/jobs/"]');
            const titelEl = art.querySelector('[data-testid="job-teaser-list-title"]');
            const titel = ((titelEl ? titelEl.textContent : '') || '').trim();
            const zeilen = (art.innerText || '').split('\\n').map(z => z.trim()).filter(Boolean);
            const i = zeilen.findIndex(z => z === titel);
            out.push({
                href: link ? link.getAttribute('href') : '',
                titel,
                firma: i >= 0 ? (zeilen[i + 1] || '') : '',
                ort: i >= 0 ? (zeilen[i + 2] || '') : '',
            });
        }
        return out;
    }"""
    )


def search(terms: str | list[str], location: str = "München", *,
           max_results: int = 30, with_description: bool = True,
           headed: bool = False) -> list[dict]:
    """XING-Treffer samt Anzeigentext.

    ``terms`` darf eine Liste sein: alle Begriffe laufen in **einer**
    Browsersitzung, weil jeder Browserstart teuer ist.
    """
    begriffe = [terms] if isinstance(terms, str) else list(terms or [])
    begriffe = [b.strip() for b in begriffe if b and b.strip()]
    if not begriffe:
        return []

    gesammelt: dict[str, dict] = {}

    with browser_page(headed=headed) as page:
        consent_erledigt = False
        for begriff in begriffe:
            page.goto(search_url(begriff), timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            if not consent_erledigt:
                consent_erledigt = dismiss_consent(page, _CONSENT_LABELS)

            for _klick in range(_MAX_KLICKS + 1):
                for karte in _karten(page):
                    href = (karte.get("href") or "").strip()
                    if not href:
                        continue
                    url = href if href.startswith("http") else f"{BASE}{href}"
                    if url in gesammelt:
                        continue
                    if not karte.get("titel"):
                        continue
                    gesammelt[url] = {
                        "titel": karte["titel"],
                        "firma": karte["firma"],
                        "ort": karte["ort"] or location,
                        "url": url,
                    }
                if len(gesammelt) >= max_results:
                    break
                if not _mehr_klicken(page):
                    break

            if len(gesammelt) >= max_results:
                break

        ergebnis = list(gesammelt.values())[:max_results]

        if with_description:
            for eintrag in ergebnis:
                eintrag["beschreibung"] = _beschreibung(page, eintrag["url"])

    return [_job(e) for e in ergebnis]


def _mehr_klicken(page) -> bool:
    """„Show more" drücken; ``False``, wenn es nichts mehr gibt."""
    try:
        knopf = page.get_by_role("button", name=re.compile("show more|mehr", re.I))
        if not knopf.count():
            return False
        vorher = len(_karten(page))
        knopf.first.click(timeout=6000)
        page.wait_for_timeout(2200)
        return len(_karten(page)) > vorher
    except Exception:
        return False


def _beschreibung(page, url: str) -> str:
    """Anzeigentext der Detailseite (``expandable-content``)."""
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)
        text = page.evaluate(
            """() => {
            const el = document.querySelector('[data-testid="expandable-content"]');
            return el ? el.innerText : '';
        }"""
        )
    except Exception:
        return ""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) >= _MIN_DESCRIPTION else ""


def _job(eintrag: dict) -> dict:
    text = eintrag.get("beschreibung") or ""
    return {
        "titel": eintrag.get("titel", ""),
        "firma": eintrag.get("firma", ""),
        "ort": eintrag.get("ort", ""),
        "url": eintrag.get("url", ""),
        "quelle": "XING",
        "snippet": text[:400],
        "beschreibung": text,
    }
