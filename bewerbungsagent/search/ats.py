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

import concurrent.futures
import json
import re
import time
from html import unescape as html_unescape
from urllib.parse import quote, urlencode, urlparse

import requests

from ..commute import is_near_munich
from ..profile import normalize
from .base import clean_html

# Ab dieser Länge gilt ein Beschreibungstext als brauchbar. Kürzere „Inhalte"
# sind meist nur ein Satz Verweis und würden das Scoring verfälschen.
_MIN_DESCRIPTION = 200

_TIMEOUT = 25

# JobLeads drosselt Bursts über Cloudflare mit HTTP 429 (Sekunden, kein
# Tageslimit): 177 Detailseiten mit 6 Threads liefen in eine Sperre, 80 kamen
# durch. Deshalb weniger Parallelität plus Backoff statt vieler Threads.
_JOBLEADS_WORKERS = 3
_JOBLEADS_RETRIES = 4
_JOBLEADS_BACKOFF = 1.5


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


def _workday_page(list_url: str, headers: dict, offset: int) -> dict:
    """Eine Seite des Workday-Job-Index (``limit`` ist auf 20 begrenzt)."""
    r = requests.post(
        list_url, headers=headers, timeout=_TIMEOUT,
        json={"appliedFacets": {}, "limit": 20,
              "offset": offset, "searchText": ""},
    )
    r.raise_for_status()
    return r.json()


def workday(tenant: str, site: str, firma: str,
            user_agent: str | None = None, max_jobs: int = 2000) -> list[dict]:
    """Workday: externe Karriereseite ohne Authentifizierung.

    Die Stellenliste kommt über ``POST /wday/cxs/{tenant}/{site}/jobs`` — die
    JSON-Antwort ist öffentlich, aber ``limit`` ist auf 20 begrenzt, daher wird
    paginiert (parallel, weil einzelne Konzerne mehrere tausend Stellen führen).
    Jede Stelle trägt Titel, Ort und den Pfad zur Detailseite, aber **keinen**
    Beschreibungstext: der liegt nur als ``application/ld+json`` auf der
    Detailseite und wird über den Browser-Fetch nachgeladen.

    ``max_jobs`` begrenzt die Zahl der abzurufenden Einträge; der München-Filter
    greift erst danach.
    """
    headers = {**(_ua(user_agent)), "Accept": "application/json",
               "Content-Type": "application/json"}
    list_url = f"https://{tenant}.wd3.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    base = f"https://{tenant}.wd3.myworkdayjobs.com"

    first = _workday_page(list_url, headers, 0)
    postings = first.get("jobPostings") or []
    total = first.get("total") or len(postings)
    limit = min(total, max_jobs)

    if limit > len(postings):
        offsets = list(range(len(postings), limit, 20))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for page in pool.map(lambda o: _workday_page(list_url, headers, o),
                                 offsets):
                postings.extend(page.get("jobPostings") or [])

    jobs: list[dict] = []
    for posting in postings[:max_jobs]:
        path = (posting.get("externalPath") or "").strip()
        if not path:
            continue
        jobs.append(_job(
            firma=firma,
            titel=posting.get("title") or "",
            ort=posting.get("locationsText") or "",
            url=f"{base}/en-US/{site}{path}",
            beschreibung="",
        ))
    return jobs


BOARDS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def eightfold(host: str, domain: str, firma: str, *, location: str = "munich",
              user_agent: str | None = None, max_jobs: int = 500) -> list[dict]:
    """Eightfold.ai-Karriereseite (``/api/pcsx/search``).

    Achtfold ist das ATS hinter Qualcomm, Infineon u. a. Der öffentliche Index
    liefert JSON mit ``data.positions`` und ``data.count``; ``num`` wird
    serverseitig ignoriert (immer 10 pro Seite), deshalb wird über ``start``
    paginiert. Der ``location``-Parameter filtert serverseitig — ohne ihn hätte
    eine Firma mehrere tausend Stellen, die erst danach lokal gefiltert würden.

    Der Beschreibungstext fehlt im Index und wird über den Browser-Fetch
    nachgeladen.
    """
    base = f"https://{host}/api/pcsx/search"
    params = {"domain": domain, "query": "", "location": location,
              "start": 0, "num": 10}
    positions: list[dict] = []
    while True:
        r = requests.get(base, params=params, headers=_ua(user_agent),
                         timeout=_TIMEOUT)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        page = data.get("positions") or []
        if not page:
            break
        positions.extend(page)
        count = data.get("count") or 0
        params["start"] += len(page)
        if (count and len(positions) >= count) or len(positions) >= max_jobs:
            break

    jobs: list[dict] = []
    for p in positions[:max_jobs]:
        title = (p.get("name") or "").strip()
        url_path = (p.get("positionUrl") or "").strip()
        if not title or not url_path:
            continue
        locations = p.get("locations") or p.get("standardizedLocations") or []
        jobs.append(_job(
            firma=firma,
            titel=title,
            ort=", ".join(filter(None, locations)),
            url=f"https://{host}{url_path}",
            beschreibung="",
        ))
    return jobs


def smartrecruiters(company: str, firma: str, *, city: str | None = None,
                    country: str | None = None,
                    user_agent: str | None = None,
                    max_jobs: int = 500) -> list[dict]:
    """SmartRecruiters: ``/v1/companies/{company}/postings`` (Renesas u. a.).

    Die Liste liefert 100 Stellen pro Seite inklusive Ort; ``city``/``country``
    filtern serverseitig. Den **vollständigen Anzeigentext** gibt es nur über die
    Detail-URL (``jobAd.sections``: jobDescription + qualifications +
    additionalInformation) — deshalb wird sie pro Stelle nachgeladen. Für diese
    Stellen entfällt damit der Browser-Fetch.
    """
    headers = {**(_ua(user_agent)), "Accept": "application/json"}
    base = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
    postings: list[dict] = []
    offset = 0
    while len(postings) < max_jobs:
        params: dict = {"limit": 100, "offset": offset}
        if city:
            params["city"] = city
        if country:
            params["country"] = country
        r = requests.get(base, params=params, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        page = data.get("content") or []
        if not page:
            break
        postings.extend(page)
        total = data.get("totalFound") or 0
        offset += len(page)
        if offset >= total:
            break

    def _detail(posting: dict) -> str:
        try:
            d = requests.get(
                f"{base}/{posting.get('id')}", headers=headers, timeout=_TIMEOUT
            )
            d.raise_for_status()
            sections = ((d.json() or {}).get("jobAd") or {}).get("sections") or {}
        except (requests.RequestException, ValueError):
            return ""
        parts = [_texts((sections.get(k) or {}).get("text") or "") for k in
                 ("jobDescription", "qualifications", "additionalInformation")]
        return "\n\n".join(p for p in parts if p)

    jobs: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        descriptions = list(pool.map(_detail, postings[:max_jobs]))
    for posting, desc in zip(postings[:max_jobs], descriptions):
        location = posting.get("location") or {}
        place = ", ".join(filter(None, [location.get("city"),
                                        location.get("country")]))
        url = (posting.get("postingUrl") or posting.get("ref") or "").strip()
        if not posting.get("name") or not url:
            continue
        job = _job(firma=firma, titel=posting.get("name") or "",
                   ort=place, url=url, beschreibung=desc)
        jobs.append(job)
    return jobs


def oracle_cloud(host: str, site: str, firma: str, *,                 location: str | None = None,
                 user_agent: str | None = None,
                 max_jobs: int = 500) -> list[dict]:
    """Oracle Cloud HCM („Oracle Recruiting Cloud", z. B. Texas Instruments).

    Der öffentliche Index ``/hcmRestApi/resources/latest/recruitingCEJobRequisitions``
    liefert 25 Stellen pro ``finder``-Aufruf; ``offset`` paginiert und
    ``location`` filtert serverseitig (Land oder Stadt). ``hasMore`` ist **nicht**
    verlässlich (steht schon auf ``false``, während noch Stellen folgen) — die
    Schleife läuft deshalb, bis eine Seite kürzer als ``limit`` ist.

    Der Beschreibungstext fehlt im Index (``ShortDescriptionStr`` ist leer) und
    wird über den Browser-Fetch von der Detailseite geladen.
    """
    url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    page_size = 25
    jobs: list[dict] = []
    offset = 0
    while len(jobs) < max_jobs:
        finder = (f"findReqs;siteNumber={site},limit={page_size},offset={offset},"
                  f"sortBy=POSTING_DATES_DESC")
        if location:
            finder += f",location={location}"
        r = requests.get(url, params={"onlyData": "true",
                                      "expand": "requisitionList.secondaryLocations",
                                      "finder": finder},
                         headers=_ua(user_agent), timeout=_TIMEOUT)
        r.raise_for_status()
        items = (r.json() or {}).get("items") or []
        page = (items[0].get("requisitionList") or []) if items else []
        if not page:
            break
        for raw in page:
            job_id = str(raw.get("Id") or "").strip()
            title = (raw.get("Title") or "").strip()
            if not job_id or not title:
                continue
            jobs.append(_job(
                firma=firma,
                titel=title,
                ort=raw.get("PrimaryLocation") or "",
                url=f"https://careers.ti.com/de/sites/{site}/job/{job_id}/",
                beschreibung="",
            ))
        offset += len(page)
        if len(page) < page_size:
            break
    return jobs[:max_jobs]


# --------------------------------------------------------------------------
# TYPO3-Jobbörse (MTU Aero Engines)
# --------------------------------------------------------------------------

# Die Liste rendert jede Stelle als ``div.jobs-list__item`` mit den Eckdaten in
# ``data-*``-Attributen — robuster als das sichtbare Markup zu parsen.
_MTU_ITEM_RE = re.compile(
    r'<div class="jobs-list__item"\s+'
    r'data-job-id="[^"]*"\s+'
    r'data-title="([^"]*)"\s+'
    r'data-category="([^"]*)"\s+'
    r'data-location="([^"]*)"\s+'
    r'data-target-group="([^"]*)"\s*>'
    r'.*?href="([^"]+)"',
    re.DOTALL,
)

# ``data-location`` kodiert Orte als ``münchen_ger`` / ``fort worth_usa``.
# Für die Ortsprüfung wird das in lesbaren Text zurückverwandelt.
_MTU_LOCATION_SUFFIX_RE = re.compile(r"_(ger|usa|pol|srb|can|sg|nl|aut|gbr)$")


def _mtu_location(raw: str) -> str:
    """``münchen_ger,starnberg_ger`` → ``München, Starnberg``."""
    parts = []
    for part in (raw or "").split(","):
        text = _MTU_LOCATION_SUFFIX_RE.sub("", part.strip())
        text = text.replace("_", " ").strip()
        if text:
            parts.append(text.title())
    return ", ".join(parts)


def _mtu_description(url: str, user_agent: str | None) -> str:
    """Volltext aus dem ``application/ld+json`` der Detailseite."""
    try:
        r = requests.get(url, headers=_ua(user_agent), timeout=_TIMEOUT)
        r.raise_for_status()
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                          r.text, re.DOTALL)
        if not match:
            return ""
        data = json.loads(match.group(1))
    except (requests.RequestException, ValueError):
        return ""
    return _texts(data.get("description") or "")


def typo3_jobboard(list_url: str, firma: str, *,
                   user_agent: str | None = None,
                   only_near_munich: bool = True,
                   max_jobs: int = 500) -> list[dict]:
    """TYPO3-Jobbörse mit Solr-Suche (MTU Aero Engines).

    Die Übersichtsseite enthält **alle** Stellen (keine Paginierung) und trägt
    Titel, Kategorie, Ort und Zielgruppe als ``data-*``-Attribute. Den
    vollständigen Anzeigentext liefert die Detailseite als ``application/ld+json``
    — per normalem HTTP-Abruf, ohne Browser.

    Die Detailseiten werden nur für die Stellen geladen, die den Ortsfilter
    passieren (bei MTU sind das rund 190 von 400) — sonst kostet ein Lauf
    mehrere Minuten für Stellen, die anschließend ohnehin aussortiert werden.
    """
    r = requests.get(list_url, headers=_ua(user_agent), timeout=_TIMEOUT)
    r.raise_for_status()

    parsed = []
    for title, _category, location, _target, url in _MTU_ITEM_RE.findall(r.text):
        title = clean_html(html_unescape(title))
        if not title or not url:
            continue
        place = _mtu_location(location)
        if only_near_munich and not is_near_munich(place):
            continue
        parsed.append((title, place, url.strip()))

    parsed = parsed[:max_jobs]
    if not parsed:
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        descriptions = list(pool.map(
            lambda entry: _mtu_description(entry[2], user_agent), parsed))

    jobs: list[dict] = []
    for (title, place, url), desc in zip(parsed, descriptions):
        jobs.append(_job(firma=firma, titel=title, ort=place, url=url,
                         beschreibung=desc))
    return jobs


# --------------------------------------------------------------------------
# JobLeads (aggregiert Stellen, serverseitig gerendert)
# --------------------------------------------------------------------------

# Der Kartencontainer trägt je nach Auslieferung ein Vue-Scope-Attribut vor
# ``class`` („<div data-v-cb046f9e="" class="search-job-card …">"), wie es die
# gespeicherte SPA-DOM (MHTML) enthält. Deshalb nicht auf die Position von
# ``class`` verlassen, sondern auf das exakte ``data-testid``. Fallback bleibt
# der Klassenname, falls eine Auslieferung das Testid wegkürzt.
_JOLEADS_CARD_RE = re.compile(
    r'<div class="search-job-card.*?(?=<div class="search-job-card|$)',
    re.DOTALL,
)
_JOLEADS_CARD_MARKER = 'data-testid="search-job-card"'
_JOLEADS_CARD_CLASS_RE = re.compile(
    r'<div[^>]*class="[^"]*search-job-card(?=[\s"])', re.IGNORECASE)
_JOBLEADS_LINK_RE = re.compile(
    r'data-testid="search-job-card-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_JOBLEADS_COMPANY_RE = re.compile(
    r'data-testid="search-job-card-company-name"[^>]*>(.*?)<', re.DOTALL)
_JOBLEADS_SALARY_RE = re.compile(
    r'data-testid="job-card-chip-salary"[^>]*>(.*?)</', re.DOTALL)
_JOBLEADS_DATE_RE = re.compile(
    r'data-testid="job-card-date"[^>]*>(.*?)</', re.DOTALL)
# Das JSON-LD trägt ein ``nonce``-Attribut vor ``type``, deshalb nicht auf die
# genaue Attributreihenfolge verlassen.
_JOBLEADS_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*id="jobPostingLdjson"[^>]*>'
    r'(.*?)</script>',
    re.DOTALL,
)


# JobLeads schreibt Orte im Slug ohne Umlaute („munchen"). Für das Dashboard
# wird daraus wieder der lesbare Name — sonst steht bei jeder Münchener Stelle
# „Munchen".
_JOBLEADS_ORT_FIX = {
    "munchen": "München",
    "garching bei munchen": "Garching bei München",
    "unterschleissheim": "Unterschleißheim",
    "unterfohring": "Unterföhring",
    "furstenfeldbruck": "Fürstenfeldbruck",
    "grunwald": "Grünwald",
    "grobenszell": "Gröbenzell",
}


def jobleads_url(query: str, location: str = "München",
                 *, radius_km: int = 30, days: int = 7,
                 min_salary: int = 0) -> str:
    """Baut eine JobLeads-Such-URL aus Begriff + Ort.

    JobLeads verlangt für den Ortsfilter Koordinaten; ohne sie greift nur der
    Slug-Ort in der URL. Die Koordinaten kommen aus ``commute`` (dort liegt der
    München-Mittelpunkt schon), damit sie nicht doppelt gepflegt werden.

    ``min_salary`` wird von JobLeads **nicht** als harte Grenze angewendet —
    bei ``minSalary=80000`` kamen weiterhin Anzeigen mit 60.000–80.000. Der
    Parameter verschiebt nur das Ranking, deshalb ist er standardmäßig aus.
    """
    from ..commute import MUNICH_LAT, MUNICH_LON

    params = {
        "filter_by_contractType": "full_time",
        "filter_by_daysReleased": str(days),
        "location_coordinates_radius": str(radius_km * 1000),
        "location_latitude": f"{MUNICH_LAT}",
        "location_longitude": f"{MUNICH_LON}",
        "location_radius": str(radius_km),
    }
    if min_salary:
        params["minSalary"] = str(min_salary)
    slug = quote(location, safe="") if location else ""
    q = quote(query, safe="")
    return f"https://www.jobleads.com/de/jobs/l/{slug}/q/{q}?{urlencode(params)}"


def _jobleads_cards(html: str) -> list[str]:
    """Zerlegt eine JobLeads-Ergebnisseite in Kartenblöcke.

    Geschnitten wird am ``data-testid="search-job-card"`` des Containers; der
    Block beginnt beim davorstehenden ``<div``. Damit ist die Reihenfolge der
    Attribute egal — die Live-Seite liefert ``class`` zuerst, die gespeicherte
    SPA-DOM schiebt ``data-v-*`` davor.
    """
    marks = [m.start() for m in re.finditer(
        re.escape(_JOLEADS_CARD_MARKER), html)]
    if not marks:
        return _JOLEADS_CARD_RE.findall(html)
    starts = []
    for mark in marks:
        start = html.rfind("<div", 0, mark)
        starts.append(start if start >= 0 else mark)
    cards = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html)
        if end > start:
            cards.append(html[start:end])
    return cards


def _jobleads_location(url: str) -> str:
    """Ort aus dem Slug: ``/de/job/titel--gilching--hash`` → ``Gilching``."""
    path = urlparse(url).path.rstrip("/")
    parts = path.split("--")
    if len(parts) < 2:
        return ""
    raw = parts[-2].replace("-", " ").strip()
    if not raw:
        return ""
    readable = raw.title()
    return _JOBLEADS_ORT_FIX.get(readable.lower(), readable)


def _jobleads_description(url: str, user_agent: str | None) -> str:
    """Volltext aus dem ``JobPosting``-JSON-LD der Detailseite.

    Bei HTTP 429 wird mit wachsendem Abstand erneut versucht — Cloudflare
    drosselt nur kurzfristig, ein einzelner Fehlversuch würde den Volltext
    sonst stillschweigend verlieren und die Stelle zu schwach bewerten.
    """
    for versuch in range(_JOBLEADS_RETRIES):
        try:
            r = requests.get(url, headers=_ua(user_agent), timeout=_TIMEOUT)
            if r.status_code == 429:
                time.sleep(_JOBLEADS_BACKOFF * (2 ** versuch))
                continue
            r.raise_for_status()
        except requests.RequestException:
            return ""
        match = _JOBLEADS_LD_RE.search(r.text)
        if not match:
            return ""
        try:
            data = json.loads(match.group(1))
        except ValueError:
            return ""
        return _texts(data.get("description") or "")
    return ""


def jobleads(list_url: str, firma: str = "JobLeads", *,
             user_agent: str | None = None,
             only_near_munich: bool = True,
             with_description: bool = True,
             max_jobs: int = 100) -> list[dict]:
    """JobLeads-Suchergebnisseite (serverseitig gerendert, ohne Login).

    Die Trefferliste steht vollständig im HTML: jede Stelle ist eine
    ``div.search-job-card`` mit ``data-testid``-Markern für Titel, Firma,
    Gehalt und Datum; der Ort steckt im Slug der Anzeigen-URL. Die Detailseite
    liefert den Volltext als ``JobPosting``-JSON-LD — ebenfalls ohne Login.

    Anders als bei den ATS-Quellen ist die Firma hier **der Arbeitgeber aus der
    Anzeige**, nicht JobLeads selbst: sonst landen alle Treffer unter einem
    Namen und der Firmenfilter im Dashboard wird unbrauchbar.
    """
    r = requests.get(list_url, headers=_ua(user_agent), timeout=_TIMEOUT)
    r.raise_for_status()

    entries = []
    seen: set[str] = set()
    for card in _jobleads_cards(r.text):
        link = _JOBLEADS_LINK_RE.search(card)
        if not link:
            continue
        href = link.group(1).strip()
        title = clean_html(link.group(2))
        if not href or not title:
            continue
        url = href if href.startswith("http") else f"https://www.jobleads.com{href}"
        if url in seen:
            continue
        company = _JOBLEADS_COMPANY_RE.search(card)
        salary = _JOBLEADS_SALARY_RE.search(card)
        firma = clean_html(company.group(1)) if company else ""
        # Mancherorts steht die Firma zusätzlich im Linktext
        # („tracetronic GmbH: Key Account Manager …") — sonst erscheint sie im
        # Dashboard doppelt.
        if firma and title.lower().startswith(firma.lower() + ":"):
            title = title[len(firma) + 1:].strip()
        entries.append({
            "titel": title,
            "firma": firma,
            "ort": _jobleads_location(url),
            "url": url,
            "gehalt": clean_html(salary.group(1)) if salary else "",
        })
        seen.add(url)

    if only_near_munich:
        entries = [e for e in entries if is_near_munich(e["ort"])]
    entries = entries[:max_jobs]
    if not entries:
        return []

    descriptions: list[str] = [""] * len(entries)
    if with_description:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=_JOBLEADS_WORKERS) as pool:
            descriptions = list(pool.map(
                lambda e: _jobleads_description(e["url"], user_agent), entries))

    jobs: list[dict] = []
    for entry, desc in zip(entries, descriptions):
        job = _job(firma=entry["firma"] or firma, titel=entry["titel"],
                   ort=entry["ort"], url=entry["url"], beschreibung=desc)
        # Eigene Quelle: JobLeads ist weder Portal-Suche noch Arbeitgeber-ATS,
        # und nur so lässt sich im Dashboard nachvollziehen, woher die Stelle kam.
        job["quelle"] = "JobLeads"
        if entry["gehalt"]:
            job["gehalt"] = entry["gehalt"]
            job["gehalt_quelle"] = "Anzeige"
        jobs.append(job)
    return jobs


# --------------------------------------------------------------------------
# SAP SuccessFactors „Jobs2Web" (tile-search-results, HTML statt JSON)
# --------------------------------------------------------------------------
_TILE_RE = re.compile(
    r'<li[^>]*class="[^"]*job-tile[^"]*"[^>]*data-url="([^"]+)"[^>]*>(.*?)</li>',
    re.DOTALL,
)
_TILE_TITLE_RE = re.compile(r'<a[^>]*class="jobTitle-link[^"]*"[^>]*>(.*?)</a>',
                            re.DOTALL)
_TILE_LOCATION_RE = re.compile(
    r'id="[^"]*-desktop-section-(?:multi)?location-value"[^>]*>(.*?)</div>',
    re.DOTALL,
)


def successfactors_j2w(host: str, firma: str, *,
                       user_agent: str | None = None,
                       max_jobs: int = 2000) -> list[dict]:
    """SAP SuccessFactors „Jobs2Web"-Karriereseite (HTML-Tiles).

    Diese ältere SuccessFactors-Variante hat **keinen** JSON-Endpunkt: die
    Stellen liegen als HTML-„Tiles" in ``/tile-search-results/?q=&startrow=N``
    (25 pro Seite, Gesamtzahl in ``jobRecordsFound``). Live verifiziert an
    HENSOLDT. Die Tiles enthalten Titel (``jobTitle-link``), Ort
    (``…-location-value``) und den Pfad zur Detailseite (``data-url``).

    Der Beschreibungstext fehlt und wird über den Browser-Fetch nachgeladen.
    """
    base = f"https://{host}/tile-search-results/"
    params = {"q": "", "startrow": 0}
    jobs: list[dict] = []
    seen: set[str] = set()
    while len(jobs) < max_jobs:
        r = requests.get(base, params=params, headers=_ua(user_agent),
                         timeout=_TIMEOUT)
        r.raise_for_status()
        text = r.text
        found_any = False
        for tile in _TILE_RE.finditer(text):
            found_any = True
            path, body = tile.group(1).strip(), tile.group(2)
            if not path or path in seen:
                continue
            seen.add(path)
            title_match = _TILE_TITLE_RE.search(body)
            if not title_match:
                continue
            title = clean_html(title_match.group(1))
            if not title:
                continue
            location_match = _TILE_LOCATION_RE.search(body)
            location = clean_html(location_match.group(1)) if location_match else ""
            jobs.append(_job(
                firma=firma,
                titel=title,
                ort=location,
                url=f"https://{host}{path}",
                beschreibung="",
            ))
        if not found_any:
            break
        params["startrow"] += 25
    return jobs


# --------------------------------------------------------------------------
# Firmen-Jobbörse über die Sitemap (generisch)
# --------------------------------------------------------------------------

# ``<script type="application/ld+json">`` ohne feste Attributreihenfolge: das
# ``type`` kann hinter einem ``nonce``/``id`` stehen.
_JSONLD_SCRIPT_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
_SITEMAP_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.DOTALL)


def _jsonld_job_postings(html: str) -> list[dict]:
    """Alle ``JobPosting``-Objekte aus den JSON-LD-Blöcken einer Seite.

    Eine Seite enthält oft mehrere Blöcke (Breadcrumb, Organisation, Stelle) und
    die ``@type``-Angabe mal als String, mal als Liste. Beides wird abgedeckt.
    """
    found: list[dict] = []
    for match in _JSONLD_SCRIPT_RE.finditer(html or ""):
        roh = match.group(1).strip()
        if not roh:
            continue
        try:
            data = json.loads(roh)
        except ValueError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            typen = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == "jobposting" for t in typen if t):
                found.append(item)
    return found


def _jsonld_ort(posting: dict) -> str:
    """Ort aus ``jobLocation`` (Dict oder Liste, Adresse verschachtelt)."""
    locations = posting.get("jobLocation")
    items = locations if isinstance(locations, list) else [locations]
    for item in items:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        address = address if isinstance(address, dict) else {}
        ort = (address.get("addressLocality") or address.get("addressRegion")
               or item.get("name") or "")
        if str(ort).strip():
            return _texts(str(ort))
    return ""


def sitemap_jobboard(sitemap_url: str, firma: str, *,
                     url_must_contain: str | tuple[str, ...] = (),
                     user_agent: str | None = None,
                     only_near_munich: bool = True,
                     with_description: bool = True,
                     max_jobs: int = 200) -> list[dict]:
    """Firmen-Jobbörse ohne API: Sitemap → Detailseiten mit ``JobPosting``-JSON-LD.

    Für Karriereseiten, die weder ein bekanntes ATS noch einen JSON-Endpunkt
    haben, aber eine ``sitemap.xml`` mit den Anzeigen-URLs ausliefern. Live
    verifiziert an E.ON (``jobs.eon.com``): 502 Anzeigen in der Sitemap, der Ort
    steht im Slug, und die Detailseite liefert Titel, Arbeitgeber, Ort und
    Volltext als ``JobPosting``-JSON-LD.

    ``url_must_contain`` grenzt **vor** dem Laden der Detailseiten ein (eine
    Weltfirma hat hunderte Anzeigen; ohne Filter würde jede einzeln geladen).
    Der Filter ist eine Heuristik — der echte Ort kommt anschließend aus dem
    JSON-LD und wird gegen ``is_near_munich`` geprüft.
    """
    r = requests.get(sitemap_url, headers=_ua(user_agent), timeout=_TIMEOUT)
    r.raise_for_status()
    urls = [u.strip() for u in _SITEMAP_LOC_RE.findall(r.text)]
    urls = [u for u in urls if u.startswith("http") and "/job/" in u]
    if url_must_contain:
        needle = (url_must_contain if isinstance(url_must_contain, tuple)
                  else (url_must_contain,))
        kleingeschrieben = tuple(str(n).lower() for n in needle if str(n).strip())
        if kleingeschrieben:
            urls = [u for u in urls if any(n in u.lower() for n in kleingeschrieben)]

    seen: set[str] = set()
    unique = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    unique = unique[:max_jobs]
    if not unique:
        return []

    jobs: list[dict] = []
    for url in unique:
        try:
            detail = requests.get(url, headers=_ua(user_agent), timeout=_TIMEOUT)
            detail.raise_for_status()
        except requests.RequestException:
            continue
        postings = _jsonld_job_postings(detail.text)
        if not postings:
            continue
        posting = postings[0]
        titel = _texts(str(posting.get("title") or ""))
        if not titel:
            continue
        org = posting.get("hiringOrganization")
        if isinstance(org, list):
            org = org[0] if org else {}
        arbeitgeber = _texts(str((org or {}).get("name") or "")) if isinstance(org, dict) else ""
        beschreibung = _texts(str(posting.get("description") or "")) if with_description else ""
        jobs.append(_job(
            firma=arbeitgeber or firma,
            titel=titel,
            ort=_jsonld_ort(posting),
            url=url,
            beschreibung=beschreibung,
        ))
    return jobs


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
        firma = str(entry.get("firma") or "").strip()
        # Workday braucht Tenant und Site statt eines einzelnen Board-Namens.
        if ats == "workday":
            tenant = str(entry.get("tenant") or "").strip()
            site = str(entry.get("site") or "").strip()
            firma = firma or site
            if not tenant or not site:
                errors.append(f"ats (workday:{tenant or '?'}/{site or '?'}): tenant/site fehlt")
                continue
            try:
                found = workday(tenant, site, firma,
                                user_agent=user_agent,
                                max_jobs=entry.get("max_jobs", 2000))
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        elif ats == "eightfold":
            host = str(entry.get("host") or "").strip()
            domain = str(entry.get("domain") or "").strip()
            if not host or not domain:
                errors.append(f"ats (eightfold:{host or '?'}/{domain or '?'}): host/domain fehlt")
                continue
            try:
                found = eightfold(host, domain, firma,
                                  location=str(entry.get("location") or "munich"),
                                  user_agent=user_agent,
                                  max_jobs=entry.get("max_jobs", 500))
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        elif ats == "successfactors":
            host = str(entry.get("host") or "").strip()
            if not host:
                errors.append(f"ats (successfactors: host fehlt)")
                continue
            try:
                found = successfactors_j2w(host, firma,
                                           user_agent=user_agent,
                                           max_jobs=entry.get("max_jobs", 2000))
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        elif ats == "smartrecruiters":
            company = str(entry.get("company") or "").strip()
            if not company:
                errors.append(f"ats (smartrecruiters: company fehlt)")
                continue
            try:
                found = smartrecruiters(company, firma,
                                        city=entry.get("city"),
                                        country=entry.get("country"),
                                        user_agent=user_agent,
                                        max_jobs=entry.get("max_jobs", 500))
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        elif ats == "oracle":
            host = str(entry.get("host") or "").strip()
            site = str(entry.get("site") or "").strip()
            if not host or not site:
                errors.append(f"ats (oracle: host/site fehlt)")
                continue
            try:
                found = oracle_cloud(host, site, firma,
                                     location=entry.get("location"),
                                     user_agent=user_agent,
                                     max_jobs=entry.get("max_jobs", 500))
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        elif ats == "typo3":
            list_url = str(entry.get("list_url") or "").strip()
            if not list_url:
                errors.append(f"ats (typo3: list_url fehlt)")
                continue
            try:
                # Der Ortsfilter wird hier schon angewendet, weil er auch
                # entscheidet, für welche Stellen die Detailseite geladen wird.
                found = typo3_jobboard(
                    list_url, firma,
                    user_agent=user_agent,
                    only_near_munich=only_near_munich,
                    max_jobs=entry.get("max_jobs", 500),
                )
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        elif ats == "jobleads":
            list_url = str(entry.get("list_url") or "").strip()
            if not list_url:
                errors.append(f"ats (jobleads: list_url fehlt)")
                continue
            try:
                found = jobleads(
                    list_url, firma,
                    user_agent=user_agent,
                    only_near_munich=only_near_munich,
                    with_description=entry.get("with_description", True),
                    max_jobs=entry.get("max_jobs", 100),
                )
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        elif ats == "sitemap":
            sitemap_url = str(entry.get("sitemap") or entry.get("sitemap_url") or "").strip()
            if not sitemap_url:
                errors.append("ats (sitemap: sitemap fehlt)")
                continue
            try:
                found = sitemap_jobboard(
                    sitemap_url, firma,
                    url_must_contain=entry.get("url_must_contain") or (),
                    user_agent=user_agent,
                    only_near_munich=only_near_munich,
                    with_description=entry.get("with_description", True),
                    max_jobs=entry.get("max_jobs", 200),
                )
            except requests.RequestException as exc:
                errors.append(f"ats ({firma}): {type(exc).__name__}")
                continue
        else:
            board = str(entry.get("board") or "").strip()
            firma = firma or board
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
