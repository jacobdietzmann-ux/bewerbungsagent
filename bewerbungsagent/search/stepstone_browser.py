"""StepStone über den echten Browser.

StepStone beantwortet einfache HTTP-Abfragen seit Ende Oktober zunehmend mit
einer **leeren 200-Antwort** (Bot-Abwehr) — der HTTP-Provider lieferte dadurch
13 statt 120 Treffer und gar keine Anzeigentexte. Im Browser lädt die
Trefferliste normal (48 Treffer für „Testingenieur" in München, 25 Karten pro
Seite).

Der Provider liefert bewusst **keine** Beschreibung: Die Detailseiten lädt der
``fetch``-Schritt des Tageslaufs im selben Browser-Verfahren nach. So bleibt die
Suche schnell (eine Sitzung für alle Begriffe) und der Text kommt dort her, wo
er ohnehin gebraucht wird.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .base import split_title_firma
from .browser import browser_page, dismiss_consent

BASE = "https://www.stepstone.de"
_CONSENT_LABELS = ("Alle akzeptieren", "Akzeptieren", "Zustimmen", "Accept all")

# Schrittweise mehr Treffer: StepStone zeigt 25 pro Seite, „Mehr anzeigen"
# lädt nach.
_MAX_SEITEN = 3


def _slug(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "jobs"


def search_url(term: str, location: str = "München", radius: int = 30) -> str:
    """Such-URL mit Umkreis; StepStone erwartet Slugs im Pfad."""
    return f"{BASE}/jobs/{_slug(term)}/in-{_slug(location)}?radius={int(radius)}"


def available() -> bool:
    from .browser import available as _available

    return _available()


def _karten(page) -> list[dict]:
    """Trefferliste aus der DOM lesen (Titel, Firma, Ort, Detail-URL)."""
    return page.evaluate(
        """() => {
        const out = [];
        for (const art of document.querySelectorAll('article[data-at="job-item"]')) {
            const titelEl = art.querySelector('[data-at="job-item-title"]');
            const firmaEl = art.querySelector('[data-at="job-item-company-name"]');
            const ortEl = art.querySelector('[data-at="job-item-location"]');
            const links = [...art.querySelectorAll('a')]
                .map(a => a.getAttribute('href') || '')
                .filter(h => h.includes('stellenangebote--') || h.includes('/job/'));
            out.push({
                titel: titelEl ? titelEl.textContent.trim() : '',
                firma: firmaEl ? firmaEl.textContent.trim() : '',
                ort: ortEl ? ortEl.textContent.trim() : '',
                href: links.length ? links[links.length - 1] : '',
            });
        }
        return out;
    }"""
    )


def _mehr_anzeigen(page) -> bool:
    """„Mehr anzeigen" drücken; False, wenn es nichts mehr gibt."""
    try:
        knopf = page.get_by_role("button", name=re.compile("mehr anzeigen|weitere", re.I))
        if not knopf.count():
            return False
        vorher = len(_karten(page))
        knopf.first.click(timeout=6000)
        page.wait_for_timeout(2200)
        return len(_karten(page)) > vorher
    except Exception:
        return False


def search(terms: str | list[str], location: str = "München", *,
           max_results: int = 40, with_description: bool = False,
           headed: bool = False) -> list[dict]:
    """StepStone-Treffer über den Browser (eine Sitzung für alle Begriffe)."""
    begriffe = [terms] if isinstance(terms, str) else list(terms or [])
    begriffe = [b.strip() for b in begriffe if b and b.strip()]
    if not begriffe:
        return []

    gesammelt: dict[str, dict] = {}
    with browser_page(headed=headed) as page:
        consent_erledigt = False
        for begriff in begriffe:
            page.goto(search_url(begriff, location), timeout=45000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            if not consent_erledigt:
                consent_erledigt = dismiss_consent(page, _CONSENT_LABELS)

            for _seite in range(_MAX_SEITEN):
                for karte in _karten(page):
                    href = (karte.get("href") or "").strip()
                    if not href or not karte.get("titel"):
                        continue
                    url = href if href.startswith("http") else f"{BASE}{href}"
                    if url in gesammelt:
                        continue
                    firma = karte.get("firma") or ""
                    if not firma:
                        firma = split_title_firma(karte["titel"])[1]
                    gesammelt[url] = {
                        "titel": karte["titel"],
                        "firma": firma,
                        "ort": karte.get("ort") or location,
                        "url": url,
                    }
                if len(gesammelt) >= max_results:
                    break
                if not _mehr_anzeigen(page):
                    break
            if len(gesammelt) >= max_results:
                break

    return [{"titel": j["titel"], "firma": j["firma"], "ort": j["ort"],
             "url": j["url"], "beschreibung": "", "quelle": "StepStone"}
            for j in list(gesammelt.values())[:max_results]]
