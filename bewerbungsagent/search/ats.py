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


def oracle_cloud(host: str, site: str, firma: str, *,
                 location: str | None = None,
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
