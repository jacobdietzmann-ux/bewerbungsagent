"""Such-Orchestrierung: führt die Provider aus, dedupliziert und normalisiert Jobs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .. import triage as _triage
from ..config import Config
from ..profile import Profile, normalize
from . import arbeitnow, ats, bing, duckduckgo, jobspy, manual, stepstone


def _clean_url(url: str) -> str:
    """Entfernt Tracking-Parameter, um Duplikate zu erkennen."""
    try:
        parts = urlparse(url)
        keep = {k: v for k, v in parse_qs(parts.query).items()
                if k.lower() not in {"utm_source", "utm_medium", "utm_campaign",
                                     "utm_term", "utm_content", "trk", "ref", "src"}}
        query = urlencode(keep, doseq=True)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, query, ""))
    except Exception:
        return url


def build_queries(s: dict) -> list[str]:
    location = s.get("location", "München")
    return [f"{term} Jobs {location}" for term in s.get("query_terms", [])]


def build_stepstone_queries(s: dict) -> list[str]:
    """StepStone nutzt Suchbegriff + Ort getrennt (kein „Jobs Ort“-Suffix)."""
    return [term for term in s.get("query_terms", [])]


_LISTING_HINTS = (
    "jobs in", "jobs &", "stellenangebote", "stellenanzeigen", "jobs als",
    "offene stellen", "dringend", "jobs münchen", "jobs munchen", "jobsuche",
    "stellen suchen", "jobs: ", " - jooble", " - stepstone", " - indeed",
    " - glassdoor", " - kimeta", "tausende freie jobs", "neuer job:",
    "projekte für", "projekte fuer",
)


def _is_listing_page(title: str) -> bool:
    """Erkennt Aggregator-/Übersichtsseiten („N Jobs in München …“) anhand des Titels."""
    t = normalize(title)
    if not t:
        return False
    if any(h in t for h in _LISTING_HINTS):
        return True
    # Muster „<Zahl> Jobs“ / „<Zahl> Stellen“
    return bool(re.search(r"^\d+\s+(jobs|stellen|offene)", t))


_NON_JOB_HOSTS = (
    "wikipedia.org", "studyflix.de", "youtube.com", "youtu.be", "amazon.", "ebay.",
    "alternate.de", "computerbase.de", "heise.de", "chip.de", "netzwelt.de",
    "wikiwand.com", "britannica.com", "ionos.de", "ionos.com", "tecchannel.de",
    "embedded-world.de", "mikrocontroller.net", "golem.de", "t-online.de",
    "focus.de", "spiegel.de", "linkedin.com", "xing.com", "kununu.com",
    "indeed.com", "glassdoor", "monster.de", "stepstone.de/store",
)


def _is_non_job_host(url: str) -> bool:
    """Erkennt Lexikon-, Shop- und Nachrichten-Treffer, die keine Stellenanzeige sind."""
    host = (urlparse(url).netloc or "").lower()
    if not host:
        return False
    return any(h in host for h in _NON_JOB_HOSTS)


def _existing_jobs(config: Config) -> list[dict]:
    """Bekannte Anzeigen (Bestand + Import) — Grundlage für die ATS-Erkennung.

    Daraus lassen sich die Karriereseiten der Firmen ableiten, die schon einmal
    gefunden wurden. Ohne das müsste jede Firma von Hand in ``ats_boards``
    eingetragen werden.
    """
    from ..storage import load_json
    jobs: list[dict] = []
    for path in (config.jobs_path(), config.import_path()):
        try:
            jobs.extend(load_json(path, []) or [])
        except Exception:
            continue
    return jobs


# Quellen, die bereits verifizierte Stellen liefern (strukturierte Jobbörsen statt
# roher Web-Such-Treffer). Für diese entfallen Aggregator-/Lexikon-Filter — die URLs
# von LinkedIn/Indeed/StepStone sind dort echte Anzeigen, keine Listing-Seiten.
_DIRECT_SOURCES = {"StepStone", "Import", "LinkedIn", "Indeed", "Google Jobs",
                   "ATS", "Arbeitnow", "JobLeads"}


def run_search(config: Config, profile: Profile,
               definition: dict | None = None) -> tuple[list[dict], list[str]]:
    """Führt eine Suche aus.

    ``definition`` (optional) überschreibt einzelne Suchparameter — für
    „gespeicherte Suchen": ``{"query_terms": [...], "location": "...",
    "providers": [...]}``. Ohne Angabe wird die Standard-Suche aus ``config.json``
    verwendet. Manueller Import läuft unabhängig davon immer mit.
    """
    s = dict(config.data["search"])
    if definition:
        for key in ("query_terms", "location", "providers"):
            if definition.get(key) is not None:
                s[key] = definition[key]
    jobs: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    # Zweiter Schlüssel: dieselbe Stelle erscheint oft auf der Firmen-Karriereseite
    # *und* bei einer Jobbörse — mit unterschiedlicher URL. Ohne diesen Schlüssel
    # landen beide Varianten im Bestand. Der Import läuft zuerst, daher gewinnt die
    # Original-Anzeige (mit vollständigem Text) gegen den Aggregator-Treffer.
    seen_identity: set[tuple[str, str]] = set()

    def add(job: dict) -> None:
        if job.get("quelle") not in _DIRECT_SOURCES:
            if _is_listing_page(job.get("titel", "")):
                return
            if _is_non_job_host(job.get("url", "")):
                return
        key = normalize(job.get("url") or f"{job.get('firma')} {job.get('titel')}")
        if key and key in seen:
            return
        firma = normalize(job.get("firma") or "")
        titel = normalize(job.get("titel") or "")
        identity = (firma, titel)
        if firma and titel and identity in seen_identity:
            return
        seen.add(key)
        if firma and titel:
            seen_identity.add(identity)
        jobs.append(job)

    # 1) Manueller Import (immer, falls Datei vorhanden).
    try:
        for j in manual.search(config.import_path()):
            if j.get("titel"):
                add(j)
    except Exception as exc:  # pragma: no cover - defensiv
        errors.append(f"manual: {exc}")

    # 2) Web-Provider.
    if s.get("enabled", True):
        for name in s.get("providers", []):
            if name == "manual":
                continue
            provider = {"duckduckgo": duckduckgo, "bing": bing,
                        "stepstone": stepstone, "jobspy": jobspy,
                        "ats": ats, "arbeitnow": arbeitnow,
                        "jobleads": ats}.get(name)
            if provider is None:
                errors.append(f"Unbekannter Provider: {name}")
                continue

            if name == "ats":
                # Karriereseiten der Zielunternehmen. Die Board-Liste steht in
                # ``search.ats_boards``; fehlt sie, wird sie aus den vorhandenen
                # Anzeigen abgeleitet — dann braucht keine Firma Pflege.
                boards = s.get("ats_boards")
                if not boards:
                    boards = ats.boards_from_jobs(_existing_jobs(config))
                jobs_found, ats_errors = provider.search(
                    boards,
                    user_agent=s.get("user_agent", "Mozilla/5.0"),
                    only_near_munich=s.get("ats_only_near_munich", True),
                )
                for job in jobs_found:
                    add(job)
                errors.extend(ats_errors)
            elif name == "jobleads":
                # JobLeads ist ein Aggregator mit Such-URLs; anders als die
                # ATS-Boards gibt es keine feste Karriereseite. Ein Eintrag ist
                # entweder ein Suchbegriff (URL wird gebaut) oder ein Dict mit
                # fertiger ``list_url`` (z. B. eine von Hand kuratierte Suche).
                entries = s.get("jobleads_searches") or []
                for entry in entries:
                    extra: dict = {}
                    if isinstance(entry, str):
                        list_url = ats.jobleads_url(
                            entry, s.get("location", "München"),
                            min_salary=s.get("jobleads_min_salary", 0),
                        )
                    else:
                        list_url = str(entry.get("list_url") or "").strip()
                        extra = entry
                    if not list_url:
                        errors.append("jobleads: list_url fehlt")
                        continue
                    try:
                        for job in ats.jobleads(
                            list_url,
                            user_agent=s.get("user_agent", "Mozilla/5.0"),
                            only_near_munich=s.get("ats_only_near_munich", True),
                            with_description=extra.get("with_description", True),
                            max_jobs=extra.get("max_jobs", 100),
                        ):
                            add(job)
                    except Exception as exc:
                        errors.append(f"{name} ({list_url[:40]}...): {exc}")
            elif name == "arbeitnow":
                try:
                    for job in provider.search(
                        max_pages=s.get("arbeitnow_pages", 3),
                        user_agent=s.get("user_agent", "Mozilla/5.0"),
                        only_near_munich=True,
                    ):
                        add(job)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
            elif name == "stepstone":
                # StepStone: Suchbegriff + Ort getrennt.
                for term in build_stepstone_queries(s):
                    try:
                        for raw in provider.search(
                            term,
                            location=s.get("location", "München"),
                            max_results=s.get("max_results_per_provider", 8),
                            timeout=s.get("timeout_seconds", 15),
                            user_agent=s.get("user_agent", "Mozilla/5.0"),
                        ):
                            add(_to_job(raw))
                    except Exception as exc:
                        errors.append(f"{name} ({term[:40]}...): {exc}")
            elif name == "jobspy":
                # JobSpy (LinkedIn/Indeed/Google) ist langsam und liefert für
                # nahe verwandte Suchbegriffe stark überlappende Treffer; daher nur
                # auf einem begrenzten Teil der Suchbegriffe laufen lassen.
                terms = build_stepstone_queries(s)[:s.get("jobspy_max_terms", 4)]
                for term in terms:
                    try:
                        for job in provider.search(
                            term,
                            location=s.get("location", "München"),
                            max_results=s.get("max_results_per_provider", 8),
                            timeout=s.get("timeout_seconds", 15),
                            user_agent=s.get("user_agent", "Mozilla/5.0"),
                        ):
                            add(job)
                    except Exception as exc:
                        errors.append(f"{name} ({term[:40]}...): {exc}")
            else:
                for query in build_queries(s):
                    try:
                        for raw in provider.search(
                            query,
                            max_results=s.get("max_results_per_provider", 8),
                            timeout=s.get("timeout_seconds", 15),
                            user_agent=s.get("user_agent", "Mozilla/5.0"),
                        ):
                            add(_to_job(raw))
                    except Exception as exc:
                        errors.append(f"{name} ({query[:40]}...): {exc}")

    # IDs vergeben.
    for i, job in enumerate(jobs, start=1):
        job.setdefault("id", i)
        job.setdefault("firma", _guess_firma(job))
        job.setdefault("ort", "")
        job.setdefault("status", "neu")
        job.setdefault("titel", job.get("titel", ""))

    # Relevanz-Triage: domänenfremde Treffer (Vertrieb, Marketing, Finanzen,
    # Gastronomie, Fahren …) fliegen raus, *bevor* sie den Bestand erreichen.
    # Sie werden nicht stillschweigend verworfen, sondern zur Nachvollziehbarkeit
    # in ``data/triage_rejected.json`` protokolliert.
    if s.get("triage", True):
        jobs, rejected = _triage.split(jobs, config)
        if rejected:
            try:
                from ..storage import save_json
                save_json(config.data_dir / "triage_rejected.json",
                          [{"titel": j.get("titel"), "firma": j.get("firma"),
                            "url": j.get("url"),
                            "grund": _triage.verdict_for(j, config).reason}
                           for j in rejected])
            except Exception as exc:  # pragma: no cover - defensiv
                errors.append(f"triage-Protokoll: {exc}")
        # IDs nach dem Filter neu und lückenlos vergeben.
        for i, job in enumerate(jobs, start=1):
            job["id"] = i
        triage_rejected = len(rejected)
    else:
        triage_rejected = 0
    return jobs, errors, triage_rejected


def _to_job(raw: dict) -> dict:
    titel, firma = _split(raw["titel"])
    industry = raw.get("branche") or raw.get("industry") or raw.get("company_industry")
    return {
        "titel": titel,
        "firma": raw.get("firma") or firma,
        "ort": raw.get("ort") or "",
        "url": _clean_url(raw.get("url", "")),
        "quelle": raw.get("quelle", ""),
        "snippet": raw.get("snippet", ""),
        "branche": industry if isinstance(industry, str) else "",
        "branche_quelle": (
            "Quelle" if isinstance(industry, str) and industry.strip() else "Heuristik"
        ),
    }


def _split(title: str) -> tuple[str, str]:
    from .base import split_title_firma
    return split_title_firma(title)


def _guess_firma(job: dict) -> str:
    if job.get("firma"):
        return job["firma"]
    from .base import split_title_firma
    _, firma = split_title_firma(job.get("titel", ""))
    return firma
