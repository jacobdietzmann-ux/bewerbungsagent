"""Pipeline-Orchestrierung: Suche → Matching → Dokumente → Dashboard."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .commute import enrich_commute
from .config import AGENT_ROOT, Config
from .dashboard import build_dashboard
from .documents import generate_anschreiben, generate_lebenslauf
from .importer import import_old_dashboard
from .matching import match_jobs
from .profile import Profile, normalize
from .salary import enrich_salary
from .search import run_search as _search
from .storage import load_json, now_iso, save_json

FIT_RANK = {"hoch": 3, "mittel": 2, "niedrig": 1}

# Dateinamen analog zu den bestehenden Bewerbungsordnern in 01_Bewerbungen/.
_DOC_NAMES = {
    "de": {"anschreiben": "Anschreiben_Jacob_Dietzmann.pdf",
           "lebenslauf": "Lebenslauf_Jacob_Dietzmann.pdf"},
    "en": {"anschreiben": "Cover_Letter_Jacob_Dietzmann_EN.pdf",
           "lebenslauf": "CV_Jacob_Dietzmann_EN.pdf"},
}


def load_config_and_profile(config_path: Path | None = None):
    config = Config(config_path)
    if not config.profile_path.exists():
        raise FileNotFoundError(f"Profil nicht gefunden: {config.profile_path}")
    profile = Profile.load(config.profile_path)
    return config, profile


def _job_key(job: dict) -> str:
    url = normalize(job.get("url", ""))
    if url:
        return url
    return normalize(f"{job.get('firma', '')}|{job.get('titel', '')}")


def safe_name(value: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "-", value or "stelle")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80].strip()


def _fit_value(job: dict) -> int:
    """Einheitlicher Fit-Wert (0–100) für alte (fit_pct) und neue (score) Stellen."""
    raw = job.get("fit_pct") if job.get("fit_pct") is not None else job.get("score")
    try:
        return round(float(raw)) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# Schritte
# --------------------------------------------------------------------------

def run_search(config: Config, profile: Profile) -> dict:
    jobs, errors = _search(config, profile)
    save_json(config.jobs_path(), jobs)
    return {"count": len(jobs), "errors": errors, "path": str(config.jobs_path())}


def run_match(config: Config, profile: Profile) -> dict:
    jobs = load_json(config.jobs_path(), [])
    location = config.data["search"].get("location")
    matches = match_jobs(profile, jobs, location=location)
    for i, m in enumerate(matches, start=1):
        m.setdefault("id", i)
        m["key"] = _job_key(m)
    save_json(config.matches_path(), matches)
    state = _merge_state(load_json(config.state_path(), {"applications": []}), matches)
    save_json(config.state_path(), state)
    return {"matched": len(matches), "state": state}


def run_generate(config: Config, profile: Profile, job_ids=None, min_fit=None) -> dict:
    matches = load_json(config.matches_path(), [])
    min_fit = min_fit or config.data["documents"].get("min_fit_for_generation", "mittel")
    threshold = FIT_RANK.get(min_fit, FIT_RANK["mittel"])

    selected = []
    for m in matches:
        # Abgelaufene Anzeigen überspringen.
        if m.get("verfuegbar") is False:
            continue
        if job_ids is not None:
            if m.get("id") in job_ids:
                selected.append(m)
        elif FIT_RANK.get(m.get("fit_geschaetzt", "niedrig"), 1) >= threshold:
            selected.append(m)

    created = []
    for job in selected:
        created.extend(_generate_one(config, profile, job))

    return {"generated": created, "jobs_processed": len(selected)}


def run_enrich(config: Config, profile: Profile) -> dict:
    """Anreicherung + Bereinigung des Bestands:

    1. Pendelweg (Auto) von Garching für alle Stellen berechnen.
    2. Gehaltsschätzung für alle Stellen ohne eigene Zahlenangabe.
    3. Stellen in ``research`` prüfen (Fit-Wert auffrischen/anzeigen).
    4. Stellen mit FIT < 50 % löschen — nur für noch nicht versendete Stellen
       (``research``/``docs``); versendete/abgeschlossene bleiben sichtbar.
    5. Für Stellen mit FIT > 65 % automatisch Bewerbungsunterlagen erzeugen.
    """
    state = load_json(config.state_path(), {"applications": []})
    apps = state.get("applications", [])

    # 1) Pendelweg
    commute_stats = enrich_commute(apps, config.data_dir)

    # 2) Gehaltsschätzung
    salary_stats = enrich_salary(apps)

    # 3) research-Stellen prüfen: Fit ist bereits gespeichert; wir protokollieren sie.
    research_checked = []
    for a in apps:
        if a.get("status") == "research":
            research_checked.append({
                "firma": a.get("firma"), "titel": a.get("titel"),
                "fit": _fit_value(a), "ort": a.get("ort"),
                "verfuegbar": a.get("verfuegbar", True),
            })

    # 4) FIT < 50 % löschen — NUR für Stellen, die noch nicht versendet wurden
    #    (research/docs). Bereits verschickte/abgeschlossene Stellen (sent,
    #    followup, interview, rejected) bleiben sichtbar, da sie echte
    #    Bewerbungsaktivität dokumentieren.
    _ACTIVE_STATUSES = {"sent", "followup", "interview", "rejected"}
    deleted_count = 0
    for a in apps:
        if a.get("status") in _ACTIVE_STATUSES:
            continue
        if _fit_value(a) < 50 and not a.get("deleted"):
            a["deleted"] = True
            a["deleted_reason"] = "FIT < 50 %"
            deleted_count += 1

    # 5) FIT > 65 % automatisch bewerben (nur wenn noch keine Unterlagen vorliegen)
    generated = []
    for a in apps:
        if a.get("deleted"):
            continue
        if a.get("verfuegbar") is False:
            continue
        if _fit_value(a) <= 65:
            continue
        if a.get("dokumente"):
            continue
        for created in _generate_one(config, profile, a):
            generated.append(created)
            # Dokument-Referenzen direkt in den In-Memory-Zustand übernehmen,
            # damit sie nicht durch den finalen ``save_json`` verloren gehen.
            a["dokumente"] = {**a.get("dokumente", {}), **created["dokumente"]}
            if a.get("status") in (None, "research", "neu"):
                a["status"] = "docs"

    state["applications"] = apps
    state["updated"] = now_iso()
    save_json(config.state_path(), state)

    return {
        "commute": commute_stats,
        "salary": salary_stats,
        "research_checked": research_checked,
        "deleted_fit_under_50": deleted_count,
        "generated": generated,
        "generated_count": len(generated),
        "total": len(apps),
    }


def run_import_old(config: Config) -> dict:
    """Importiert den Inhalt des alten Dashboards (MD + State) als Anwendungen."""
    apps = import_old_dashboard(config)
    state = load_json(config.state_path(), {"applications": []})
    existing_keys = {a.get("key") for a in state.get("applications", [])}
    merged = state.get("applications", [])
    for app in apps:
        if app["key"] not in existing_keys:
            merged.append(app)
            existing_keys.add(app["key"])
    state["applications"] = merged
    state["updated"] = now_iso()
    save_json(config.state_path(), state)
    return {"imported": len(apps), "total": len(merged)}


def run_dashboard(config: Config) -> dict:
    state = load_json(config.state_path(), {"applications": []})
    path = build_dashboard(state, config.dashboard_path)
    return {"path": str(path), "applications": len(state.get("applications", []))}


def run_full(config: Config, profile: Profile) -> dict:
    s = run_search(config, profile)
    m = run_match(config, profile)
    g = run_generate(config, profile)
    d = run_dashboard(config)
    return {"search": s, "match": m["matched"], "generated": g["generated"], "dashboard": d}


# --------------------------------------------------------------------------
# Interna
# --------------------------------------------------------------------------

def _merge_state(existing: dict, matches: list[dict]) -> dict:
    apps = existing.get("applications", []) if isinstance(existing, dict) else []
    by_key = {a.get("key"): a for a in apps if a.get("key")}
    score_fields = ("score", "fit_geschaetzt", "begruendung", "matched_skills",
                    "title_hits", "body_hits", "location_bonus", "beschreibung",
                    "verfuegbar")

    result = []
    seen: set[str] = set()
    for m in matches:
        key = m["key"]
        if key in by_key:
            old = by_key[key]
            for f in score_fields:
                old[f] = m.get(f)
            old.setdefault("status", "research")
            old.setdefault("dokumente", {})
            old.setdefault("created", now_iso())
            result.append(old)
        else:
            m.setdefault("status", "research")
            m.setdefault("dokumente", {})
            m.setdefault("created", now_iso())
            result.append(m)
        seen.add(key)

    # Bereits erfasste, aber aktuell nicht mehr gefundene Stellen behalten.
    for a in apps:
        if a.get("key") not in seen:
            result.append(a)

    return {"updated": now_iso(), "applications": result}


def _generate_one(config: Config, profile: Profile, job: dict) -> list[dict]:
    match = job  # matches sind Jobs inkl. Score-Feldern
    folder = config.bewerbungen_dir / safe_name(f"{job.get('firma', '')} - {job.get('titel', '')}")
    folder.mkdir(parents=True, exist_ok=True)

    languages = config.data["documents"].get("languages", ["de"])
    files: dict[str, str] = {}
    for lang in languages:
        names = _DOC_NAMES.get(lang, _DOC_NAMES["de"])
        ans = generate_anschreiben(profile, job, match, folder / names["anschreiben"], config.data, lang)
        cv = generate_lebenslauf(profile, job, match, folder / names["lebenslauf"], config.data, lang)
        files[f"anschreiben_{lang}"] = _rel(ans)
        files[f"lebenslauf_{lang}"] = _rel(cv)

    # Stellenanzeige als Referenz im selben Ordner ablegen.
    stellenanzeige = folder / "Stellenanzeige.txt"
    stellenanzeige.write_text(_stellenanzeige_text(job), encoding="utf-8")
    files["stellenanzeige"] = _rel(stellenanzeige)

    # Referenzschreiben (BMW) als Anlage kopieren, falls vorhanden.
    from .documents import copy_reference_letter
    ref = copy_reference_letter(profile, folder)
    if ref:
        files["referenzschreiben"] = _rel(ref)

    _record_docs(config, job, files)
    return [{"id": job.get("id"), "firma": job.get("firma"), "titel": job.get("titel"),
             "dokumente": files}]


def _stellenanzeige_text(job: dict) -> str:
    lines = [
        job.get("titel", ""),
        f"{job.get('firma', '')} · {job.get('ort', '')}",
        f"Quelle: {job.get('quelle', '')}",
        f"URL: {job.get('url', '')}",
        "",
        "-" * 60,
        "",
        job.get("beschreibung", "") or "(keine Beschreibung verfügbar)",
    ]
    return "\n".join(lines).strip() + "\n"


def _rel(path: Path) -> str:
    return os.path.relpath(str(path), str(AGENT_ROOT))


def _record_docs(config: Config, job: dict, files: dict) -> None:
    state = load_json(config.state_path(), {"applications": []})
    key = job.get("key") or _job_key(job)
    for a in state.get("applications", []):
        if a.get("key") == key:
            a["dokumente"] = {**a.get("dokumente", {}), **files}
            if a.get("status") in (None, "research", "neu"):
                a["status"] = "docs"
            break
    save_json(config.state_path(), state)
