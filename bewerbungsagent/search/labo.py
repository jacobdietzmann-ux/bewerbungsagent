"""jobs.labo.de — Fach-Jobbörse (Medizin/Labor/Technik), ohne Login abrufbar.

Die Seite ist ein „jwtpl"-Portal: Trefferliste und Anzeigen sind serverseitig
gerendert, aber ohne strukturierte Daten (kein JSON-LD, keine API). Live
verifiziert am 23.10.2026:

- Suche: ``GET /suchergebnis?jsjr=<Begriff>&jsjo=<Ort>`` (Formular der Startseite).
- Treffer: ``div.jwtpl-hili-item``; Titel, Firma, Ort und Datum stehen in
  ``span``-Elementen mit ``jwtpl-hili-item*``-Klassen. **Achtung:** Bei
  ``itemCompany`` stehen ``data-*``-Attribute *vor* ``class`` — ein Regex auf
  ``class="…"`` direkt nach dem Tag-Namen findet die Firma nicht.
- Paginierung: der „Weiter"-Knopf trägt eine fertige URL mit ``jssc=<Offset>``
  (20 Treffer je Seite).
- Anzeigentext: Die Detailseite hat kein JSON-LD, aber die Abschnitte
  („Über uns", „Aufgaben", „Profil", …) liegen als ``div`` mit
  ``jwtpl-jobaded-dataTextField`` im HTML — auch wenn der Block per CSS
  eingeklappt ist.

Titel enthalten weiche Trennzeichen (``&shy;`` / ``&#173;``), die im Dashboard
als Artefakt mitten im Wort stehen würden; sie werden entfernt.
"""

from __future__ import annotations

import re

import requests

from .base import clean_html

BASE = "https://jobs.labo.de"
SUCH_URL = f"{BASE}/suchergebnis"

_TIMEOUT = 25
_MAX_SEITEN = 5

# Weiche Trennzeichen: ``&shy;`` wird von ``html.unescape`` zu U+00AD, ``&#173;``
# ebenfalls. Beide müssen weg, sonst steht im Dashboard „Test&shy;ingenieur".
_SHY_RE = re.compile(r"\u00ad")

_ITEM_SPLIT_RE = re.compile(r'(?=<div class="jwtpl-hili-item )')
_LINK_RE = re.compile(r'class="jwtpl-hili-itemLink"\s+href="([^"]+)"')
_TITEL_RE = re.compile(r'class="jwtpl-hili-itemTitel"[^>]*>(.*?)</span>', re.S)
# ``class`` steht hier hinter ``data-jwtpl-*`` — deshalb nicht am Tag-Anfang ankern.
_FIRMA_RE = re.compile(r'class="jwtpl-hili-itemCompany[^"]*"[^>]*>(.*?)</span>', re.S)
_ORT_RE = re.compile(r'class="jwtpl-hili-itemLocation"[^>]*>(.*?)</span>\s*</div>', re.S)
_DATUM_RE = re.compile(r'class="jwtpl-hili-itemDate"[^>]*>(.*?)</span>', re.S)
_NAECHSTE_RE = re.compile(r'class="jwtpl-hilipage-nextBt[^"]*"\s+href="([^"]+)"')

# Abschnitte der Detailseite; ``dataTextField`` deckt alle Überschriften-Blöcke.
_FELD_RE = re.compile(
    r'class="jwtpl-jobaded-dataJobAd[A-Za-z]*\s+jwtpl-jobaded-dataTextField"[^>]*>(.*?)</div>',
    re.S)
_DETAIL_TITEL_RE = re.compile(
    r'class="jwtpl-jobaded-dataMainTitle"[^>]*>\s*<strong>(.*?)</strong>', re.S)
_DETAIL_FIRMA_RE = re.compile(r'class="jwtpl-jobaded-dataMainCompany"[^>]*>\s*<a[^>]*>(.*?)</a>', re.S)
_DETAIL_ORT_RE = re.compile(r'class="jwtpl-jobaded-dataMainLocation"[^>]*>(.*?)</div>', re.S)

# Ab dieser Länge gilt ein Text als brauchbar (wie in ``ats``).
_MIN_DESCRIPTION = 200


def _clean(text: str) -> str:
    """HTML-Tags/Entities entfernen und weiche Trennzeichen tilgen."""
    return _SHY_RE.sub("", clean_html(text))


def _url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    return href if href.startswith("http") else f"{BASE}{href}"


def parse_list(html: str) -> list[dict]:
    """Zerlegt eine Trefferliste in ``{titel, firma, ort, datum, url}``."""
    treffer: list[dict] = []
    for block in _ITEM_SPLIT_RE.split(html):
        if not block.startswith('<div class="jwtpl-hili-item '):
            continue
        link = _LINK_RE.search(block)
        titel_match = _TITEL_RE.search(block)
        if not link or not titel_match:
            continue
        titel = _clean(titel_match.group(1))
        url = _url(link.group(1))
        if not titel or not url:
            continue
        firma = _FIRMA_RE.search(block)
        ort = _ORT_RE.search(block)
        datum = _DATUM_RE.search(block)
        treffer.append({
            "titel": titel,
            "firma": _clean(firma.group(1)) if firma else "",
            "ort": _clean(ort.group(1)) if ort else "",
            "datum": _clean(datum.group(1)) if datum else "",
            "url": url,
        })
    return treffer


def next_page(html: str) -> str:
    """URL der nächsten Ergebnisseite oder ``""``, wenn es keine gibt.

    Der „Weiter"-Knopf trägt die fertige URL samt ``jssc=<Offset>``; sie darf
    nicht nachgebaut werden, weil die Sitzungs-ID (``jssi``) dazugehört.
    """
    match = _NAECHSTE_RE.search(html)
    if not match:
        return ""
    href = match.group(1).strip()
    return _url(href) if href else ""


def parse_description(html: str) -> str:
    """Anzeigentext aus den ``dataTextField``-Blöcken der Detailseite."""
    felder = [_clean(f.group(1)) for f in _FELD_RE.finditer(html)]
    text = " ".join(f for f in felder if f)
    return text if len(text) >= _MIN_DESCRIPTION else ""


def parse_detail(html: str) -> dict:
    """Titel, Firma und Ort aus dem Kopf der Detailseite."""
    titel = _DETAIL_TITEL_RE.search(html)
    firma = _DETAIL_FIRMA_RE.search(html)
    ort = _DETAIL_ORT_RE.search(html)
    return {
        "titel": _clean(titel.group(1)) if titel else "",
        "firma": _clean(firma.group(1)) if firma else "",
        "ort": _clean(ort.group(1)) if ort else "",
    }


def _get(session: requests.Session, url: str, params: dict | None = None,
         user_agent: str | None = None) -> str | None:
    try:
        r = session.get(url, params=params, timeout=_TIMEOUT,
                        headers={"User-Agent": user_agent or "Mozilla/5.0"})
        r.raise_for_status()
    except requests.RequestException:
        return None
    return r.text


def search(terms: str | list[str], location: str = "München", *,
           user_agent: str | None = None,
           with_description: bool = True,
           max_jobs: int = 120) -> list[dict]:
    """Sucht auf jobs.labo.de und liefert Stellen samt Anzeigentext.

    ``terms`` darf eine Liste sein: das Portal kennt keinen Serverfilter über
    mehrere Begriffe, jeder Begriff ist eine eigene Anfrage. Ein Browser wird
    hier nicht gebraucht — die Seite ist serverseitig gerendert.
    """
    begriffe = [terms] if isinstance(terms, str) else list(terms or [])
    begriffe = [b.strip() for b in begriffe if b and b.strip()]
    if not begriffe:
        return []

    session = requests.Session()
    gefunden: dict[str, dict] = {}

    for begriff in begriffe:
        params = {"jsjr": begriff}
        if location:
            params["jsjo"] = location
        url = SUCH_URL
        for _seite in range(_MAX_SEITEN):
            html = _get(session, url, params=params, user_agent=user_agent)
            if not html:
                break
            neue = 0
            for eintrag in parse_list(html):
                if eintrag["url"] in gefunden:
                    continue
                gefunden[eintrag["url"]] = eintrag
                neue += 1
            params = None      # die Folge-URL bringt ihre Parameter selbst mit
            url = next_page(html)
            if not url or not neue or len(gefunden) >= max_jobs:
                break
        if len(gefunden) >= max_jobs:
            break

    ergebnis = list(gefunden.values())[:max_jobs]
    if not with_description:
        return [_job(e, "") for e in ergebnis]

    for eintrag in ergebnis:
        detail = _get(session, eintrag["url"], user_agent=user_agent) or ""
        text = parse_description(detail) if detail else ""
        if detail:
            kopf = parse_detail(detail)
            # Firma/Ort aus der Detailseite sind genauer als die Liste
            # (dort fehlt die Firma bei manchen Anzeigen ganz).
            eintrag["firma"] = eintrag["firma"] or kopf["firma"]
            eintrag["ort"] = kopf["ort"] or eintrag["ort"]
        eintrag["beschreibung"] = text
    return [_job(e, e.get("beschreibung") or "") for e in ergebnis]


def _job(eintrag: dict, beschreibung: str) -> dict:
    text = beschreibung if len(beschreibung) >= _MIN_DESCRIPTION else ""
    return {
        "titel": eintrag.get("titel", ""),
        "firma": eintrag.get("firma", ""),
        "ort": eintrag.get("ort", ""),
        "url": eintrag.get("url", ""),
        "quelle": "Labo",
        "snippet": text[:400],
        "beschreibung": text,
    }
