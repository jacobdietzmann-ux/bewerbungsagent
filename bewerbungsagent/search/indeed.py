"""Indeed über einen echten Browser (Cloudflare blockt alles andere).

Live verifiziert am 23.10.2026:

- ``GET de.indeed.com/jobs?...`` antwortet auf einfache HTTP-Anfragen mit
  **HTTP 403** und der Seite „Security Check - Indeed.com". Das gilt auch für
  die alte RSS-Schnittstelle (``/rss?q=…``) und für ``python-jobspy``
  („JobSpy:Indeed - Indeed response status code 403").
- Im Browser lädt die Trefferliste normal („Testingenieur Jobs in München |
  Jetzt 50 offene Stellen finden"). Der Consent-Hinweis muss weggeklickt
  werden, sonst bleibt die Seite leer.
- Treffer sind ``div.job_seen_beacon`` mit ``h3.jobTitle a[data-jk]``,
  ``[data-testid="company-name"]`` und ``[data-testid="text-location"]``.
  Die Trefferliste enthält **keinen** Anzeigentext (kein Snippet).
- Die kanonische URL ist ``https://de.indeed.com/viewjob?jk=<jk>``. Sie
  funktioniert **nicht** per HTTP (403), im Browser aber schon — und liefert
  den Volltext in ``div.simple-job-description-html`` (5688 Zeichen im Test).

Ohne Anzeigentext wäre der Fit auf den Titel beschränkt und alle Treffer
fielen unter die Ausblende-Grenze — deshalb wird die Detailseite mitgeladen.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .browser import browser_page, dismiss_consent

BASE = "https://de.indeed.com"
_MIN_DESCRIPTION = 200

_CONSENT_LABELS = ("Alle Cookies akzeptieren", "Accept all", "Akzeptieren",
                   "Alle akzeptieren")

# „Hybrides Arbeiten in 80634 München" → „München" wäre falsch geraten; der Ort
# bleibt wie angegeben, ``is_near_munich`` erkennt „München" darin.
_PLZ_RE = re.compile(r"^\d{5}\s+")


def search_url(term: str, location: str = "München") -> str:
    params = f"q={quote(term, safe='')}"
    if location:
        params += f"&l={quote(location, safe='')}"
    return f"{BASE}/jobs?{params}"


def available() -> bool:
    """True, wenn Playwright samt Chromium nutzbar ist."""
    from .browser import available as _available
    return _available()


def _karten(page) -> list[dict]:
    return page.evaluate(
        """() => {
        const out = [];
        for (const card of document.querySelectorAll('div.job_seen_beacon')) {
            const link = card.querySelector('h3.jobTitle a[data-jk]');
            const jk = link ? link.getAttribute('data-jk') : '';
            const titelEl = card.querySelector('h3.jobTitle');
            const firmaEl = card.querySelector('[data-testid="company-name"]');
            const ortEl = card.querySelector('[data-testid="text-location"]');
            out.push({
                jk,
                titel: titelEl ? titelEl.innerText.trim() : '',
                firma: firmaEl ? firmaEl.innerText.trim() : '',
                ort: ortEl ? ortEl.innerText.trim() : '',
            });
        }
        return out;
    }"""
    )


def search(terms: str | list[str], location: str = "München", *,
           max_results: int = 30, with_description: bool = True,
           headed: bool = False) -> list[dict]:
    """Indeed-Treffer samt Anzeigentext.

    ``terms`` darf eine Liste sein — alle Begriffe laufen in **einer**
    Browsersitzung.

    Der Text wird über den **Klick auf den Titel** geholt, nicht über
    ``/viewjob?jk=…``: Direkte Aufrufe der Detailseite enden nach wenigen
    Anfragen in „Sign In | Indeed Accounts" oder im Cloudflare-Check (im Test
    0 von 3 Stellen). Der Klick öffnet die Master-Detail-Ansicht
    (``…&vjk=<jk>``), die auf der Trefferliste bleibt — im Test 3 von 3 mit
    Volltext, und ohne zusätzliche Seitenaufrufe.
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

            for index, karte in enumerate(_karten(page)):
                jk = (karte.get("jk") or "").strip()
                if not jk or not karte.get("titel"):
                    continue
                url = f"{BASE}/viewjob?jk={jk}"
                if url in gesammelt:
                    continue
                gesammelt[url] = {
                    "titel": karte["titel"],
                    "firma": karte["firma"],
                    "ort": _PLZ_RE.sub("", karte.get("ort") or "").strip() or location,
                    "url": url,
                }
                if with_description:
                    gesammelt[url]["beschreibung"] = _beschreibung_per_klick(page, index)
                if len(gesammelt) >= max_results:
                    break

            if len(gesammelt) >= max_results:
                break

    return [_job(e) for e in list(gesammelt.values())[:max_results]]


def _beschreibung_per_klick(page, index: int) -> str:
    """Volltext der ``index``-ten Karte über die Master-Detail-Ansicht.

    Der Klick auf den Titel setzt ``vjk=<jk>`` in der URL und zeigt die
    Beschreibung im rechten Bereich — die Trefferliste bleibt geladen, deshalb
    ist das je Stelle deutlich billiger als eine eigene Detailseite.
    """
    try:
        karte = page.locator("div.job_seen_beacon").nth(index)
        karte.locator("h3.jobTitle a").click(timeout=15000)
        page.wait_for_timeout(2600)
        text = page.evaluate(
            """() => {
            const el = document.querySelector('div.simple-job-description-html');
            return el ? el.innerText : '';
        }"""
        )
        if not (text or "").strip():
            dismiss_consent(page, _CONSENT_LABELS)
            page.wait_for_timeout(2000)
            text = page.evaluate(
                """() => {
                const el = document.querySelector('div.simple-job-description-html');
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
        "quelle": "Indeed",
        "snippet": text[:400],
        "beschreibung": text,
    }
