"""Pipeline-Orchestrierung: Suche → Matching → Dokumente → Dashboard."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .commute import (
    MAX_COMMUTE_MINUTES,
    commute_limit_minutes,
    enrich_commute,
    exceeds_commute_limit,
)
from .config import AGENT_ROOT, Config
from .dashboard import build_dashboard, dashboard_applications, documented_applications
from .db import Store
from .documents import (
    DEFAULT_CV_TEMPLATE,
    generate_anschreiben,
    generate_lebenslauf_vorlage,
)
from .homeoffice import detect_home_office
from .importer import import_old_dashboard
from .industry import classify_industry
from .matching import fit_value, has_role_signal, is_student_role, match_jobs
from .profile import Profile, normalize
from .salary import enrich_salary
from .search import run_search as _search
from .storage import load_json, now_iso, save_json

# Unterlagen-Schwellen als konkreter Score. „mittel" = 50 heißt: Stellen ab
# 50 % Fit werden gebaut (bewusst unter der Kategorie „hoch" ≥ 65), damit auch
# solide mittlere Treffer Unterlagen bekommen. „niedrig" = 0 baut alles.
FIT_RANK = {"hoch": 65, "mittel": 50, "niedrig": 0}

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


def _store(config: Config) -> Store:
    """SQLite-Store für den Datenbestand (Single Source of Truth, ADR-018)."""
    return Store(config.db_path())


def _commute_settings(config: Config) -> tuple[str, str]:
    """Wohnadresse und Kontaktadresse aus ``commute``.

    Beide sind persönliche Angaben und stehen deshalb in der privaten
    ``config.json`` (im Google-Drive-Ordner) — nicht im Quelltext.
    """
    commute = config.data.get("commute") or {}
    return commute.get("home_address") or "", commute.get("contact_email") or ""


def _persist_state(config: Config, store: Store, state: dict) -> None:
    """Schreibt den Bestand in SQLite und aktualisiert den JSON-Snapshot (Backup)."""
    store.save_state(state)
    store.export_json(config.state_path())


def safe_name(value: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "-", value or "stelle")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80].strip()


def _fit_value(job: dict) -> int:
    """Einheitlicher Fit-Wert — siehe :func:`matching.fit_value`."""
    return fit_value(job)


# --------------------------------------------------------------------------
# Schritte
# --------------------------------------------------------------------------

def run_search(config: Config, profile: Profile, definition: dict | None = None) -> dict:
    jobs, errors, triage_rejected = _search(config, profile, definition)
    save_json(config.jobs_path(), jobs)
    context = _enrich_job_context(config, jobs)
    return {
        "count": len(jobs), "errors": errors, "path": str(config.jobs_path()),
        "context": context, "triage_rejected": triage_rejected,
    }


def run_match(config: Config, profile: Profile) -> dict:
    jobs = load_json(config.jobs_path(), [])
    context = _enrich_job_context(config, jobs)
    location = config.data["search"].get("location")
    matches = match_jobs(profile, jobs, location=location)
    for i, m in enumerate(matches, start=1):
        m.setdefault("id", i)
        m["key"] = _job_key(m)
    save_json(config.matches_path(), matches)
    store = _store(config)
    state = _merge_state(store.load_state(), matches, limit=_commute_limit_minutes(config))
    _persist_state(config, store, state)
    return {"matched": len(matches), "state": state, "context": context}


def _enrich_job_context(config: Config, jobs: list[dict]) -> dict:
    unresolved = 0
    for job in jobs:
        if job.get("quelle") == "Import" and job.get("branche"):
            job["branche_quelle"] = "Quelle"
        job["branche"] = classify_industry(job)
        job.setdefault("branche_quelle", "Heuristik")
        job["homeoffice"] = detect_home_office(job)
        if job["branche"] == "Nicht ermittelt":
            unresolved += 1

    # Save the industry assignment even if the routing service is unavailable.
    save_json(config.jobs_path(), jobs)
    commute = (
        enrich_commute(jobs, config.data_dir, *_commute_settings(config))
        if jobs else
        {"total": 0, "remote": 0, "routed": 0, "cached": 0, "failed": 0}
    )
    save_json(config.jobs_path(), jobs)
    commute_unresolved = [
        {"firma": job.get("firma", ""), "titel": job.get("titel", ""),
         "ort": job.get("ort", "")}
        for job in jobs
        if job.get("pendel_modus") == "Nicht ermittelt"
    ]
    return {
        "commute": commute,
        "commute_unresolved": commute_unresolved,
        "industry_classified": len(jobs) - unresolved,
        "industry_unresolved": unresolved,
    }


def _commute_limit_minutes(config: Config) -> int:
    """Obergrenze des Pendelwegs in Minuten (konfigurierbar, sonst Standard)."""
    return commute_limit_minutes(config.data)


def _commute_blocked(config: Config, job: dict) -> bool:
    """True, wenn die Stelle wegen zu weitem Pendelweg nicht angelegt werden darf."""
    return exceeds_commute_limit(job, limit=_commute_limit_minutes(config))


def run_generate(config: Config, profile: Profile, job_ids=None, min_fit=None,
                 template: str | None = None) -> dict:
    matches = load_json(config.matches_path(), [])
    min_fit = min_fit or config.data["documents"].get("min_fit_for_generation", "mittel")
    threshold = FIT_RANK.get(min_fit, FIT_RANK["mittel"])

    selected = []
    skipped_commute = []
    skipped_student = []
    for m in matches:
        # Abgelaufene Anzeigen überspringen.
        if m.get("verfuegbar") is False:
            continue
        # Studenten-/Praktikumsstellen werden nie bedient.
        if is_student_role(m.get("titel")):
            skipped_student.append(m)
            continue
        wanted = m.get("id") in job_ids if job_ids is not None else _fit_value(m) >= threshold
        if not wanted:
            continue
        # Zu weiter Pendelweg: gar nicht erst anlegen.
        if _commute_blocked(config, m):
            skipped_commute.append(m)
            continue
        selected.append(m)

    created = []
    for job in selected:
        created.extend(_generate_one(config, profile, job, template=template))

    return {"generated": created, "jobs_processed": len(selected),
            "skipped_commute": skipped_commute, "skipped_student": skipped_student}


def run_enrich(config: Config, profile: Profile) -> dict:
    """Anreicherung + Bereinigung des Bestands:

    1. Pendelweg (Auto) von Garching für alle Stellen berechnen.
    2. Gehaltsschätzung für alle Stellen ohne eigene Zahlenangabe.
    3. Stellen in ``research`` prüfen (Fit-Wert auffrischen/anzeigen).
    4. Stellen mit FIT < 50 % löschen — nur für noch nicht versendete Stellen
       (``research``/``docs``); versendete/abgeschlossene bleiben sichtbar.
    5. Für Stellen mit FIT ≥ 50 % automatisch Bewerbungsunterlagen erzeugen.
    """
    store = _store(config)
    state = store.load_state()
    apps = state.get("applications", [])

    # 1) Pendelweg
    commute_stats = enrich_commute(apps, config.data_dir, *_commute_settings(config))

    # 1b) Homeoffice-Anteil aus der Beschreibung (falls noch nicht gesetzt).
    for a in apps:
        if not a.get("homeoffice"):
            a["homeoffice"] = detect_home_office(a)

    # 2) Gehaltsschätzung
    salary_stats = enrich_salary(apps)

    # 3) research-Stellen prüfen: Fit ist bereits gespeichert; wir protokollieren sie.
    research_checked = []
    for a in apps:
        if a.get("status") == "research":
            research_checked.append({
                "firma": a.get("firma"), "titel": a.get("titel"),
                "fit": _fit_value(a), "ort": a.get("ort"),
                "verfuegbar": a.get("verfuegbar"),
            })

    # 4) Bereinigung:
    #    a) Stellen mit zu weitem Pendelweg werden nicht angelegt (deleted-Flag).
    #    b) FIT < 50 % löschen — NUR für Stellen, die noch nicht versendet wurden
    #       (research/docs). Bereits verschickte/abgeschlossene Stellen (sent,
    #       followup, interview, rejected) bleiben sichtbar, da sie echte
    #       Bewerbungsaktivität dokumentieren.
    #    c) Stellen mit bereits erstellten Unterlagen bleiben immer sichtbar:
    #       für sie wurden bewusst Dokumente erzeugt (oft auf ausdrücklichen
    #       Wunsch), sie sind also kein Suchrauschen. Der Pendelweg-Ausschluss
    #       gilt weiterhin, weil er eine harte Vorgabe ist.
    _ACTIVE_STATUSES = {"sent", "followup", "interview", "rejected"}
    deleted_count = 0
    deleted_commute = 0
    deleted_student = 0
    restored_documented = 0
    restored_reason = 0
    restored_active = 0
    for a in apps:
        # Harte Ausschlussregel (oberste Priorität): Studenten-/Praktikums-/
        # Ausbildungsstellen sind für einen Vollzeit-Ingenieur kategorisch
        # irrelevant — unabhängig von Status, Fit oder bereits erzeugten
        # Unterlagen. Auch ein abgeschlossener „rejected“-Eintrag ist hier
        # kein wertvoller Verlauf, sondern fehladressiertes Rauschen.
        if is_student_role(a.get("titel")):
            a["deleted"] = True
            a["deleted_reason"] = "Studenten-/Praktikumsstelle (keine Vollzeit-Ingenieurrolle)"
            deleted_student += 1
            continue
        if a.get("status") in _ACTIVE_STATUSES:
            # Versendete/abgeschlossene Bewerbungen dokumentieren echte
            # Aktivität und werden hier nie ausgeblendet. Ein noch vorhandenes
            # Flag stammt dann aus einem älteren Lauf und ist ungültig —
            # 3 verschickte Bewerbungen (u. a. AIRBUS mit 78 %) waren dadurch
            # im Dashboard unsichtbar.
            if a.get("deleted"):
                a.pop("deleted", None)
                a.pop("deleted_reason", None)
                restored_active += 1
            continue
        if a.get("deleted"):
            # Ein ausgeblendeter Datensatz wird *neu bewertet*: Der Grund muss
            # noch gelten. Sonst bleibt eine Stelle für immer versteckt, weil
            # sich ihre Datengrundlage geändert hat. Genau das passierte beim
            # Nachladen der Anzeigentexte: 14 Stellen waren unter „FIT < 50 %"
            # gelöscht worden, als sie mangels Text maximal 38 % erreichen
            # konnten, und lagen danach bei 50–68 %. Ebenso waren 2 Stellen unter
            # „Pendelzeit über 30 Minuten" gelöscht — damals galt 90 min, heute
            # 30 (eine davon mit 78 % Fit).
            if _commute_blocked(config, a):
                continue                     # harte Grenze: bleibt ausgeblendet
            # Für dokumentierte Stellen wurden bewusst Unterlagen erzeugt — sie
            # bleiben sichtbar, unabhängig von der Begründung.
            if a.get("dokumente"):
                a.pop("deleted", None)
                a.pop("deleted_reason", None)
                restored_documented += 1
                continue
            reason = (a.get("deleted_reason") or "").strip()
            low = reason.lower()
            # Vom Nutzer gesetzte Kriterien bleiben unangetastet — sie sind eine
            # bewusste Entscheidung, kein ableitbarer Zustand.
            if not reason or "nutzerkriterium" in low or "neubewertung" in low:
                continue
            if low.startswith("fit"):
                if _fit_value(a) < 50:
                    continue                 # Grund gilt weiter
            elif low.startswith("pendel"):
                pass                         # Pendelweg ist oben schon geprüft
            else:
                continue                     # z. B. Rollen-Ausschluss — bewusst
            a.pop("deleted", None)
            a.pop("deleted_reason", None)
            restored_reason += 1
            continue
        if _commute_blocked(config, a):
            a["deleted"] = True
            a["deleted_reason"] = f"Pendelweg > {_commute_limit_minutes(config)} min"
            deleted_commute += 1
            continue
        if _fit_value(a) < 50 and not a.get("dokumente"):
            a["deleted"] = True
            a["deleted_reason"] = "FIT < 50 %"
            deleted_count += 1

    # 5) FIT ≥ 50 % automatisch bewerben (nur wenn noch keine Unterlagen vorliegen)
    generated = []
    skipped_role = []
    for a in apps:
        if a.get("deleted"):
            continue
        if a.get("verfuegbar") is False:
            continue
        if _fit_value(a) < FIT_RANK["mittel"]:
            continue
        if a.get("dokumente"):
            continue
        if _commute_blocked(config, a):
            continue
        # Ein hoher Fit entsteht auch bei Software-Rollen über generische
        # Technologie-Treffer. Automatisch beworben wird nur, wenn der Titel
        # auch eine Test-/Absicherungsrolle belegt (siehe ``has_role_signal``).
        if not has_role_signal(a.get("titel")):
            skipped_role.append({"firma": a.get("firma"), "titel": a.get("titel"),
                                 "fit": _fit_value(a)})
            continue
        for created in _generate_one(config, profile, a):
            generated.append(created)
            # Dokument-Referenzen direkt in den In-Memory-Zustand übernehmen,
            # damit sie nicht durch den finalen ``_persist_state`` verloren gehen.
            a["dokumente"] = {**a.get("dokumente", {}), **created["dokumente"]}
            if a.get("status") in (None, "research", "neu"):
                a["status"] = "docs"

    state["applications"] = apps
    state["updated"] = now_iso()
    _persist_state(config, store, state)

    return {
        "commute": commute_stats,
        "salary": salary_stats,
        "research_checked": research_checked,
        "deleted_fit_under_50": deleted_count,
        "deleted_commute": deleted_commute,
        "deleted_student": deleted_student,
        "restored_documented": restored_documented,
        "restored_reason": restored_reason,
        "restored_active": restored_active,
        "generated": generated,
        "generated_count": len(generated),
        "skipped_role": skipped_role,
        "total": len(apps),
    }


def run_import_old(config: Config) -> dict:
    """Importiert den Inhalt des alten Dashboards (MD + State) als Anwendungen."""
    apps = import_old_dashboard(config)
    store = _store(config)
    state = store.load_state()
    existing_keys = {a.get("key") for a in state.get("applications", [])}
    merged = state.get("applications", [])
    for app in apps:
        if app["key"] not in existing_keys:
            merged.append(app)
            existing_keys.add(app["key"])
    state["applications"] = merged
    state["updated"] = now_iso()
    _persist_state(config, store, state)
    return {"imported": len(apps), "total": len(merged)}


def run_dashboard(config: Config) -> dict:
    state = _store(config).load_state()
    path = build_dashboard(state, config.dashboard_path, _commute_limit_minutes(config))
    all_applications = state.get("applications", [])
    documented = documented_applications(all_applications)
    applications = dashboard_applications(all_applications, _commute_limit_minutes(config))
    return {
        "path": str(path),
        "applications": sum(not bool(app.get("deleted")) for app in applications),
        "with_documents": len(documented),
        "hidden_without_documents": len(all_applications) - len(documented),
        "hidden_too_far": len(documented) - len(applications),
    }


def run_full(config: Config, profile: Profile) -> dict:
    s = run_search(config, profile)
    m = run_match(config, profile)
    g = run_generate(config, profile)
    d = run_dashboard(config)
    return {"search": s, "match": m["matched"], "generated": g["generated"], "dashboard": d}


# --------------------------------------------------------------------------
# Interna
# --------------------------------------------------------------------------

def _merge_state(existing: dict, matches: list[dict],
                 limit: int = MAX_COMMUTE_MINUTES) -> dict:
    apps = existing.get("applications", []) if isinstance(existing, dict) else []
    by_key = {a.get("key"): a for a in apps if a.get("key")}
    # Felder, die aus dem Matching-Ergebnis übernommen werden.
    # Wichtig: ``score_job()`` liefert nur Scoring-Felder plus die Kopie des Job-
    # Datensatzes. Fehlt ein Feld dort (z. B. ``verfuegbar``, weil jobs.json
    # gerade nichts dazu weiß), darf der vorhandene Wert NICHT überschrieben
    # werden — sonst wird aus „geprüft verfügbar" ein ``None`` und im Dashboard
    # landete fälschlich das Badge „abgelaufen".
    score_fields = ("score", "fit_geschaetzt", "begruendung", "matched_skills",
                    "title_hits", "body_hits", "location_bonus", "beschreibung",
                    "verfuegbar", "branche", "branche_quelle", "pendel_modus",
                    "pendelzeit_min", "pendeldistanz_km", "homeoffice")

    result = []
    seen: set[str] = set()
    for m in matches:
        key = m["key"]
        if key in by_key:
            old = by_key[key]
            for f in score_fields:
                if f in m and m[f] is not None:
                    old[f] = m[f]
            old.setdefault("status", "research")
            old.setdefault("dokumente", {})
            old.setdefault("created", now_iso())
            _flag_far_commute(old, limit)
            result.append(old)
        else:
            m.setdefault("status", "research")
            m.setdefault("dokumente", {})
            m.setdefault("created", now_iso())
            # Neue Stellen mit zu weitem Pendelweg gar nicht erst anlegen.
            _flag_far_commute(m, limit)
            result.append(m)
        seen.add(key)

    # Bereits erfasste, aber aktuell nicht mehr gefundene Stellen behalten.
    for a in apps:
        if a.get("key") not in seen:
            result.append(a)

    return {"updated": now_iso(), "applications": result}


def _flag_far_commute(app: dict, limit: int) -> bool:
    """Markiert eine Stelle mit zu weitem Pendelweg als gelöscht (bleibt in der DB).

    Bereits versendete/abgeschlossene Bewerbungen bleiben unangetastet, da sie
    echte Aktivität dokumentieren.
    """
    if app.get("status") in ("sent", "followup", "interview", "rejected"):
        return False
    if app.get("deleted"):
        return False
    if not exceeds_commute_limit(app, limit=limit):
        return False
    app["deleted"] = True
    app["deleted_reason"] = f"Pendelweg > {limit} min"
    return True


def _generate_one(config: Config, profile: Profile, job: dict, template: str | None = None) -> list[dict]:
    match = job  # matches sind Jobs inkl. Score-Feldern
    folder = config.bewerbungen_dir / safe_name(f"{job.get('firma', '')} - {job.get('titel', '')}")
    folder.mkdir(parents=True, exist_ok=True)

    template = template or (config.data["documents"].get("lebenslauf_template") or DEFAULT_CV_TEMPLATE)
    languages = config.data["documents"].get("languages", ["de"])
    files: dict[str, str] = {}
    for lang in languages:
        names = _DOC_NAMES.get(lang, _DOC_NAMES["de"])
        ans = generate_anschreiben(profile, job, match, folder / names["anschreiben"], config.data, lang)
        # Eigene DOCX-Vorlage bevorzugen (mit pro-Stelle angepasstem Profil-Absatz);
        # bei fehlender Vorlage fällt die Funktion intern auf ReportLab zurück.
        cv = generate_lebenslauf_vorlage(profile, job, match, folder / names["lebenslauf"], config.data, lang,
                                         template=template)
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
    store = _store(config)
    state = store.load_state()
    key = job.get("key") or _job_key(job)
    for a in state.get("applications", []):
        if a.get("key") == key:
            a["dokumente"] = {**a.get("dokumente", {}), **files}
            if a.get("status") in (None, "research", "neu"):
                a["status"] = "docs"
            break
    _persist_state(config, store, state)
