"""JobSpy-Provider: aggregiert LinkedIn, Indeed und Google Jobs.

Nutzt die Bibliothek ``python-jobspy``, um Stellen direkt von den Jobbörsen zu
beziehen — statt über die generische Web-Suche (DuckDuckGo/Bing), die auf diesen
Portalen nur Listing-/Redirect-Seiten liefert und deshalb bisher gefiltert wurde.

Relevante Quellen für den deutschen Markt (Ort = München):

- ``linkedin`` — globale Suche, nutzt den ``location``-Parameter.
- ``indeed``   — ``country_indeed="germany"`` + ``location``.
- ``google``   — Google Jobs (``udm=8``); indexiert die ATS-Seiten der Arbeitgeber
  (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Personio, …) und liefert
  mit ``job_url_direct`` oft den direkten ATS-Link.

Bewusst ausgeschlossen: ZipRecruiter (nur US/CA), Glassdoor (schwache DE-Daten,
aggressives Rate-Limit) sowie Bayt/Naukri/BDJobs/HelloWork (andere Regionen).

Die vollständige Anzeigenbeschreibung wird direkt als ``beschreibung`` übernommen,
sodass ``fetch_descriptions.py`` (Browser-Fetch) für diese Stellen übersprungen wird.
"""

from __future__ import annotations

# Sites, die für den deutschen Markt relevant sind.
SITES = ("linkedin", "indeed", "google")

# Anzeigename je JobSpy-Site für das ``quelle``-Feld.
_SITE_LABELS = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "google": "Google Jobs",
}

# Hosts von ATS-Systemen; Google Jobs indexiert sie, job_url_direct zeigt dorthin.
_ATS_HOSTS = (
    "greenhouse.io", "lever.co", "jobs.lever.co", "ashbyhq.com",
    "smartrecruiters.com", "apply.workable.com", "workable.com",
    "personio.", "recruitee.com", "join.com", "bamboohr.com",
    "jobvite.com", "taleo.net", "successfactors.", "softgarden.",
    "icims.com", "pinpoint.com",
)

_SNIPPET_MAX = 420


def _direct_url(job: dict) -> str:
    """Bevorzugt den Direkt-Link (häufig ATS) vor der Aggregator-URL."""
    return (job.get("job_url_direct") or job.get("job_url") or "").strip()


def _is_ats(url: str) -> bool:
    """True, wenn die URL auf ein ATS-System zeigt (Greenhouse, Lever, …)."""
    host = url.lower()
    return any(h in host for h in _ATS_HOSTS)


def _snippet(description: str) -> str:
    """Kürzt die Beschreibung auf eine Vorschau für das ``snippet``-Feld."""
    text = (description or "").strip()
    if len(text) <= _SNIPPET_MAX:
        return text
    cut = text[:_SNIPPET_MAX].rsplit(" ", 1)[0]
    return f"{cut} …"


def search(query: str, location: str = "München", max_results: int = 8,
           timeout: int = 15, user_agent: str = "Mozilla/5.0") -> list[dict]:
    """Sucht über LinkedIn, Indeed und Google Jobs für einen Suchbegriff + Ort.

    ``timeout`` wird nur für die Interface-Gleichheit mit den anderen Providern
    akzeptiert; JobSpy bietet keinen direkten Timeout-Parameter.
    """
    # Lazy-Import: pandas/pydantic nur laden, wenn der Provider wirklich genutzt wird.
    from jobspy import scrape_jobs

    df = scrape_jobs(
        site_name=list(SITES),
        search_term=query,
        google_search_term=f"{query} {location}",
        location=location,
        country_indeed="germany",
        results_wanted=max_results,
        verbose=0,
        user_agent=user_agent,
        description_format="markdown",
    )
    if df is None or getattr(df, "empty", True):
        return []

    results: list[dict] = []
    for row in df.to_dict("records"):
        titel = (row.get("title") or "").strip()
        url = _direct_url(row)
        if not titel or not url:
            continue
        beschreibung = (row.get("description") or "").strip()
        results.append({
            "titel": titel,
            "firma": (row.get("company") or row.get("company_name") or "").strip(),
            "ort": (row.get("location") or "").strip(),
            "url": url,
            "quelle": _SITE_LABELS.get(row.get("site"), "JobSpy"),
            "snippet": _snippet(beschreibung),
            "beschreibung": beschreibung,
        })
        if len(results) >= max_results:
            break
    return results
