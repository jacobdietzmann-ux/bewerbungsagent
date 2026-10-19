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
from .statuses import normalize_status
from .storage import load_json, now_iso, save_json

# Fit-Bänder. Ein Wert liegt in genau einem Band, und aus dem Band folgen Status
# und Dokumenterzeugung — die Grenzen stehen deshalb nur hier:
#   < 50 %  → ausgeblendet (kein tragfähiger Treffer)
#   50–64 % → ``research``: beobachten, aber keine Unterlagen bauen
#   ≥ 65 %  → ``docs``: Unterlagen erzeugen
# Ein Anschreiben für einen 55-%-Treffer kostet Zeit und geht fast nie durch.
FIT_BAND_AUSBLENDEN = 50
FIT_BAND_UNTERLAGEN = 65

# Namen für ``documents.min_fit_for_generation`` in der config.json.
FIT_RANK = {"hoch": FIT_BAND_UNTERLAGEN, "mittel": FIT_BAND_AUSBLENDEN, "niedrig": 0}


def _fit_fuer_unterlagen(config: Config) -> int:
    """Fit-Schwelle für die automatische Dokumenterzeugung.

    Einzige Quelle ist ``documents.min_fit_for_generation``. ``run_enrich`` hatte
    die 50 zuvor fest verdrahtet und damit die Konfiguration ignoriert — eine
    Änderung dort wäre wirkungslos geblieben.
    """
    name = config.data["documents"].get("min_fit_for_generation", "hoch")
    return FIT_RANK.get(name, FIT_BAND_UNTERLAGEN)

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


def _commute_settings(config: Config) -> tuple[str, str, dict]:
    """Wohnadresse, Kontaktadresse und Firmensitz-Überschreibungen aus ``commute``.

    Alle drei sind persönliche/projektbezogene Angaben und stehen deshalb in der
    privaten ``config.json`` (im Google-Drive-Ordner) — nicht im Quelltext.
    """
    commute = config.data.get("commute") or {}
    return (commute.get("home_address") or "",
            commute.get("contact_email") or "",
            commute.get("office_overrides") or {})


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


def letzter_fund_meta(config: Config) -> dict:
    """Jüngster Fund (``{}``, wenn noch keiner protokolliert ist).

    Das Dashboard markiert damit die zuletzt gefundenen Stellen. Gespeichert wird
    der ``created``-Zeitstempel der zuletzt neu erfassten Stellen — nicht das
    Zeitfenster des letzten Laufs. Ein Lauf ohne neue Funde würde das Label sonst
    bei allen Stellen verschwinden lassen, obwohl die Funde die neuesten bleiben.
    """
    return _store(config).get_meta("letzter_fund") or {}


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
    neu = state.get("neu") or []
    if neu:
        # Alle Stellen eines Laufs erhalten denselben ``created``-Stempel; der
        # früheste davon ist der Bezugspunkt für „neu gefunden".
        store.set_meta("letzter_fund", {"zeitpunkt": min(neu), "anzahl": len(neu)})
    _persist_state(config, store, state)
    return {"matched": len(matches), "state": state, "context": context, "neu": len(neu)}


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


# Kennung am ``deleted_reason``: erkennbar und bei jedem Lauf neu bewertbar.
RESEARCH_REASON_PREFIX = "research-kriterium"


def _research_filter_settings(config: Config) -> dict | None:
    """Einstellungen des Research-Filters oder ``None`` bei ``enabled: false``."""
    raw = config.data.get("research_filter") or {}
    if raw.get("enabled") is False:
        return None
    return {
        "fit_min": int(raw.get("fit_min", 60)),
        "fit_max": int(raw.get("fit_max", 70)),
        "keep_high_fit": int(raw.get("keep_high_fit", 80)),
        "commute_grace_min": int(raw.get("commute_grace_min", 10)),
    }


def research_keep_reason(app: dict, limit: int, settings: dict) -> str:
    """Warum eine Research-Stelle bleibt — ``""`` bedeutet: entfernen.

    Drei Gründe, einen Fund zu behalten:
    1. Fit im Fenster ``fit_min``–``fit_max`` (knapp unter der Unterlagen-Schwelle).
    2. Fit ≥ ``keep_high_fit``: ein sehr guter Treffer ist kein Rauschen, auch
       wenn (noch) keine Unterlagen entstanden sind.
    3. Pendelweg knapp über der Grenze (bis ``limit + commute_grace_min``): eine
       zweite Chance, falls sich Wohnung oder Grenze ändern.
    """
    fit = _fit_value(app)
    if settings["fit_min"] <= fit <= settings["fit_max"]:
        return f"Fit {fit} % im Fenster"
    if settings["keep_high_fit"] and fit >= settings["keep_high_fit"]:
        return f"Fit {fit} % über {settings['keep_high_fit']} %"
    commute = app.get("pendelzeit_min")
    if commute is not None and commute != "":
        try:
            minutes = float(commute)
        except (TypeError, ValueError):
            return ""
        if limit < minutes <= limit + settings["commute_grace_min"]:
            return f"Pendelweg {minutes:g} min knapp über {limit} min"
    return ""


def _apply_research_filter(config: Config, apps: list[dict]) -> dict:
    """Begrenzt den ``research``-Bestand auf die behaltenswerten Funde.

    Markiert nur ``deleted`` — nichts wird gelöscht. Stellen mit Unterlagen
    bleiben unangetastet (dort wurde bewusst gearbeitet).
    """
    settings = _research_filter_settings(config)
    if settings is None:
        return {"enabled": False, "kept": 0, "removed": 0, "restored": 0}

    limit = _commute_limit_minutes(config)
    kept = removed = restored = 0
    for a in apps:
        if normalize_status(a.get("status")) != "research":
            continue
        if a.get("dokumente"):
            continue
        keep = research_keep_reason(a, limit, settings)
        reason = (a.get("deleted_reason") or "")
        is_filtered = reason.lower().startswith(RESEARCH_REASON_PREFIX)

        if keep:
            kept += 1
            if a.get("deleted") and is_filtered:
                # Grund gilt nicht mehr (Fit/Pendelweg haben sich geändert).
                a.pop("deleted", None)
                a.pop("deleted_reason", None)
                restored += 1
        elif not a.get("deleted"):
            a["deleted"] = True
            a["deleted_reason"] = (
                f"{RESEARCH_REASON_PREFIX}: Fit {settings['fit_min']}–{settings['fit_max']} % "
                f"oder Pendelweg ≤ {limit + settings['commute_grace_min']} min nötig"
            )
            removed += 1
    return {"enabled": True, "kept": kept, "removed": removed, "restored": restored}


def run_generate(config: Config, profile: Profile, job_ids=None, min_fit=None,
                 template: str | None = None) -> dict:
    matches = load_json(config.matches_path(), [])
    # ``min_fit`` als Name ("hoch"/"mittel"/"niedrig") oder Zahl.
    if isinstance(min_fit, (int, float)):
        threshold = int(min_fit)
    elif min_fit:
        threshold = FIT_RANK.get(min_fit, FIT_BAND_UNTERLAGEN)
    else:
        threshold = _fit_fuer_unterlagen(config)

    # Welche Stellen haben schon Unterlagen? Die Information steht in der DB
    # (``state.json``/``jobs.db``), *nicht* in ``matches.json`` — die beiden
    # laufen sonst auseinander und derselbe Lauf erzeugt alles erneut.
    # Nur beim Mengenlauf (``--all``) wird übersprungen; ``--ids`` ist ein
    # ausdrücklicher Wunsch und erzeugt weiter neu.
    bereits_dokumentiert: set[str] = set()
    if job_ids is None:
        for a in _store(config).load_state().get("applications", []):
            if a.get("dokumente"):
                key = a.get("key") or _job_key(a)
                if key:
                    bereits_dokumentiert.add(key)

    selected = []
    skipped_commute = []
    skipped_student = []
    skipped_existing = []
    skipped_role = []
    for m in matches:
        # Abgelaufene Anzeigen überspringen.
        if m.get("verfuegbar") is False:
            continue
        # Studenten-/Praktikumsstellen werden nie bedient.
        if is_student_role(m.get("titel")):
            skipped_student.append(m)
            continue
        if bereits_dokumentiert and ((m.get("key") or _job_key(m)) in bereits_dokumentiert):
            skipped_existing.append(m)
            continue
        wanted = m.get("id") in job_ids if job_ids is not None else _fit_value(m) >= threshold
        if not wanted:
            continue
        # Zu weiter Pendelweg: gar nicht erst anlegen.
        if _commute_blocked(config, m):
            skipped_commute.append(m)
            continue
        # Wie in ``run_enrich``: ein hoher Fit entsteht auch bei Software-Rollen
        # über generische Technologie-Treffer. Beim Mengenlauf wird nur
        # beworben, wenn der Titel eine Test-/Absicherungsrolle belegt.
        # ``--ids`` bleibt davon unberührt (ausdrücklicher Wunsch).
        if job_ids is None and not has_role_signal(m.get("titel")):
            skipped_role.append({"firma": m.get("firma"), "titel": m.get("titel"),
                                 "fit": _fit_value(m)})
            continue
        selected.append(m)

    created = []
    for job in selected:
        created.extend(_generate_one(config, profile, job, template=template))

    return {"generated": created, "jobs_processed": len(selected),
            "skipped_commute": skipped_commute, "skipped_student": skipped_student,
            "skipped_role": skipped_role, "skipped_existing": len(skipped_existing)}


def run_enrich(config: Config, profile: Profile) -> dict:
    """Anreicherung + Bereinigung des Bestands:

    1. Pendelweg (Auto) von Garching für alle Stellen berechnen.
    2. Gehaltsschätzung für alle Stellen ohne eigene Zahlenangabe.
    3. Stellen in ``research`` prüfen (Fit-Wert auffrischen/anzeigen).
    4. Stellen mit FIT < der Ausblende-Grenze (50 %) ausblenden — nur für noch
       nicht versendete Stellen (``research``/``docs``); versendete/abgeschlossene
       bleiben sichtbar.
    5. Für Stellen mit FIT ≥ der Unterlagen-Grenze (65 %) automatisch
       Bewerbungsunterlagen erzeugen.
    6. Bereits erzeugte Unterlagen im Band 50–64 % zurück auf ``research``
       setzen: diese Stellen erfüllen die Regel aus 5 nicht mehr.
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
                if _fit_value(a) < FIT_BAND_AUSBLENDEN:
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
        if _fit_value(a) < FIT_BAND_AUSBLENDEN and not a.get("dokumente"):
            a["deleted"] = True
            a["deleted_reason"] = f"FIT < {FIT_BAND_AUSBLENDEN} %"
            deleted_count += 1

    # 4b) Research-Pool begrenzen: nur Funde im Fit-Fenster, mit sehr hohem Fit
    #     oder knapp über der Pendelgrenze bleiben. Hält den Bestand
    #     entscheidbar, statt jede Suchspur zu sammeln.
    research_stats = _apply_research_filter(config, apps)

    # 6) Unterlagen im Mittelband zurücknehmen: ein 55-%-Treffer bekommt keine
    #    Bewerbung. Die Dateien bleiben liegen (nichts wird gelöscht), nur der
    #    Status wird ehrlich — ``docs`` heißt „hier liegt eine Bewerbung".
    schwellenwert = _fit_fuer_unterlagen(config)
    zurueckgenommen = []
    for a in apps:
        if a.get("deleted") or a.get("status") != "docs" or not a.get("dokumente"):
            continue
        if a.get("sentAt") or a.get("interviewDate"):
            continue                     # echte Aktivität, nicht anfassen
        if _fit_value(a) >= schwellenwert:
            continue
        a["status"] = "research"
        zurueckgenommen.append({"firma": a.get("firma"), "titel": a.get("titel"),
                                "fit": _fit_value(a)})

    # 5) Ab der Unterlagen-Schwelle automatisch bewerben (nur ohne Unterlagen)
    generated = []
    skipped_role = []
    for a in apps:
        if a.get("deleted"):
            continue
        if a.get("verfuegbar") is False:
            continue
        if _fit_value(a) < schwellenwert:
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
        "research_filter": research_stats,
        "generated": generated,
        "generated_count": len(generated),
        "skipped_role": skipped_role,
        "zurueckgenommen": zurueckgenommen,
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
    path = build_dashboard(state, config.dashboard_path, _commute_limit_minutes(config),
                           letzter_fund_meta(config))
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
    neu_zeitpunkte: list[str] = []
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
            neu_zeitpunkte.append(m["created"])
            # Neue Stellen mit zu weitem Pendelweg gar nicht erst anlegen.
            _flag_far_commute(m, limit)
            result.append(m)
        seen.add(key)

    # Bereits erfasste, aber aktuell nicht mehr gefundene Stellen behalten.
    for a in apps:
        if a.get("key") not in seen:
            result.append(a)

    return {"updated": now_iso(), "applications": result, "neu": neu_zeitpunkte}


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
