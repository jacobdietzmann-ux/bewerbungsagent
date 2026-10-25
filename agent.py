#!/usr/bin/env python3
"""Kommandozeilen-Einstieg für den Bewerbungsagenten.

Beispiele:
    python agent.py search
    python agent.py match
    python agent.py generate --all
    python agent.py generate --ids 1,2,3
    python agent.py dashboard
    python agent.py pipeline     # Suche → Match → Dokumente → Dashboard
    python agent.py status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bewerbungsagent.cleanup import run_cleanup
from bewerbungsagent.commute import MAX_COMMUTE_MINUTES
from bewerbungsagent.config import Config
from bewerbungsagent.documents import CV_TEMPLATES, DEFAULT_CV_TEMPLATE
from bewerbungsagent.pipeline import (
    FIT_BAND_AUSBLENDEN,
    FIT_BAND_UNTERLAGEN,
    load_config_and_profile,
    run_dashboard,
    run_enrich,
    run_full,
    run_generate,
    run_import_old,
    run_match,
    run_search,
)
from bewerbungsagent.quality import run_quality
from bewerbungsagent.followup import run_followup
from bewerbungsagent.saved_searches import (
    find_saved_search,
    load_saved_searches,
    to_definition,
)
from bewerbungsagent.storage import load_json


def _print_jobs(config: Config) -> None:
    matches = load_json(config.matches_path(), [])
    if not matches:
        print("Keine Stellen vorhanden. Führe zuerst 'search' und 'match' aus.")
        return
    print(f"{'ID':>3}  {'Fit':>6}  {'Firma':<28} {'Titel':<50} {'Ort':<20} {'Status'}")
    print("-" * 120)
    for m in sorted(matches, key=lambda j: j.get("score", 0), reverse=True):
        print(f"{m.get('id', '?'):>3}  {str(m.get('score', '')) + '%':>6}  "
              f"{str(m.get('firma', ''))[:27]:<28} {str(m.get('titel', ''))[:49]:<50} "
              f"{str(m.get('ort', ''))[:19]:<20} {m.get('status', 'neu')}")


def _print_job_context(context: dict) -> None:
    commute = context.get("commute", {})
    if commute.get("total"):
        print("Pendelweg ergänzt: "
              f"{commute['routed']} berechnet, {commute['cached']} aus Cache, "
              f"{commute['remote']} remote, {commute['failed']} fehlgeschlagen.")
        for job in context.get("commute_unresolved", []):
            location = job["ort"] or "Ort fehlt"
            print(f"  Pendelweg nicht ermittelt: {job['firma']} — "
                  f"{job['titel']} ({location})")
    print("Branche eingetragen: "
          f"{context.get('industry_classified', 0)} zugeordnet, "
          f"{context.get('industry_unresolved', 0)} nicht ermittelt.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bewerbungsagent")
    parser.add_argument("--config", default=None,
                        help="Pfad zur config.json (Standard: ./config.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    ssearch = sub.add_parser("search", help="Web-Suche nach Stellenangeboten ausführen")
    ssearch.add_argument("name", nargs="?", default=None,
                         help="Name einer gespeicherten Suche (siehe `agent.py searches`)")
    sub.add_parser("searches", help="Gespeicherte Suchen auflisten")
    sub.add_parser("fetch", help="Vollständige Stellenbeschreibungen per Browser laden")
    sub.add_parser("match", help="Fit-Scoring gegen das Skill-Profil ausführen")
    sub.add_parser("import-old", help="Inhalt des alten Dashboards übernehmen")
    sub.add_parser("enrich", help="Pendelweg + Gehalt + Bereinigung (FIT-Filter) + Auto-Bewerbung")
    sub.add_parser("quality", help="Erzeugte Unterlagen unabhängig prüfen (Fakten, Pflichtteile, PDF)")
    fo = sub.add_parser("followup", help="Fällige Nachfassen anzeigen (optional Texte schreiben)")
    fo.add_argument("--days", type=int, default=None,
                    help="Wartezeit in Tagen (Standard: aus config.json, sonst 14)")
    fo.add_argument("--write", action="store_true",
                    help="Follow-up-Text in den jeweiligen Bewerbungsordner schreiben")
    cln = sub.add_parser("cleanup", help="Alte Bewerbungsordner aufräumen")
    cln.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts verschieben")
    cln.add_argument("--days", type=int, default=60, help="Altersgrenze in Tagen (Standard 60)")
    sub.add_parser("dashboard", help="HTML-Dashboard (neu) erzeugen")
    sub.add_parser("status", help="Übersicht der aktuellen Stellen anzeigen")
    sub.add_parser("pipeline", help="Vollständigen Ablauf ausführen")
    ablauf = sub.add_parser("ablauf", help="Ablauf als Graph ausführen (LangGraph)")
    ablauf.add_argument("--ohne-review", action="store_true",
                        help="Freigabe-Knoten überspringen (Bewertung erfolgt im Dashboard)")
    ablauf.add_argument("--beschreibung", choices=["nur_unsure", "alle"],
                        default="nur_unsure",
                        help="Anzeigentexte nachladen: nur für unklare Titel (Standard) "
                             "oder für alle Stellen ohne Text")

    gen = sub.add_parser("generate", help="Bewerbungsunterlagen erzeugen")
    gen.add_argument("--all", action="store_true", help="alle passenden Stellen (gem. min_fit)")
    gen.add_argument("--ids", help="kommagetrennte Job-IDs, z. B. 1,2,3")
    gen.add_argument("--fit", choices=["hoch", "mittel", "niedrig"], default=None,
                     help="Mindest-Fit für --all")
    gen.add_argument("--template", choices=sorted(CV_TEMPLATES), default=None,
                     help="Lebenslauf-Vorlage (Standard: aus config.json)")

    args = parser.parse_args(argv)

    try:
        config, profile = load_config_and_profile(
            Path(args.config) if args.config else None
        )
    except FileNotFoundError as exc:
        print(f"\n✗ {exc}\n")
        print("So startest du den Agenten ohne persönliche Daten (Sofortstart):")
        print("  1. cp config.example.json config.json")
        print("  2. python agent.py match          # nutzt das Demo-Profil aus dem Beispiel")
        print("\nFür den echten Betrieb: in config.json `profile_json` auf dein eigenes")
        print("Profil zeigen (z. B. ../02_Profil-und-Assets/Profil-Datenbank.json).")
        print("Pfad zur Config überschreiben: python agent.py --config <pfad> match")
        return 1

    if args.command == "search":
        definition = None
        if args.name:
            saved = find_saved_search(config, args.name)
            if saved is None:
                print(f"Gespeicherte Suche '{args.name}' nicht gefunden.")
                print("Verfügbar:", ", ".join(s["name"] for s in load_saved_searches(config)))
                return 1
            definition = to_definition(saved)
            print(f"Gespeicherte Suche: {saved['name']} "
                  f"({len(saved.get('query_terms', []))} Begriffe, {saved.get('location')})")
        result = run_search(config, profile, definition=definition)
        print(f"Suche abgeschlossen: {result['count']} Stelle(n) gefunden.")
        rejected = result.get("triage_rejected", 0)
        if rejected:
            print(f"  Ausgefiltert (domänenfremd, z. B. Vertrieb/Marketing): {rejected} "
                  f"— protokolliert in data/triage_rejected.json")
        _print_job_context(result["context"])
        for err in result["errors"]:
            print(f"  ! {err}")
        print(f"Ergebnis: {result['path']}")
        print("Tipp: `python agent.py fetch` lädt die vollständigen Beschreibungen per Browser.")

    elif args.command == "searches":
        searches = load_saved_searches(config)
        print(f"{len(searches)} gespeicherte Suche(n):")
        for s in searches:
            print(f"  - {s['name']}: {len(s.get('query_terms', []))} Begriffe · "
                  f"Ort {s.get('location', '?')} · Provider {', '.join(s.get('providers', []))}")

    elif args.command == "fetch":
        from fetch_descriptions import fetch_descriptions
        result = fetch_descriptions(config)
        print(f"Beschreibungen geladen: {result['fetched']} | leer: {result['skipped']} "
              f"| Fehler: {result['errors']}")
        print("Tipp: `python agent.py match` berechnet danach den präzisen Fit.")

    elif args.command == "match":
        result = run_match(config, profile)
        print(f"Matching abgeschlossen: {result['matched']} Stelle(n) bewertet.")
        _print_job_context(result["context"])
        _print_jobs(config)
        run_dashboard(config)
        print(f"Dashboard aktualisiert: {config.dashboard_path}")

    elif args.command == "import-old":
        result = run_import_old(config)
        print(f"Import abgeschlossen: {result['imported']} Einträge übernommen "
              f"(gesamt {result['total']}).")
        run_dashboard(config)
        print(f"Dashboard aktualisiert: {config.dashboard_path}")

    elif args.command == "enrich":
        result = run_enrich(config, profile)
        c = result["commute"]
        print("Pendelweg berechnet: "
              f"{c['routed']} geroutet, {c['cached']} aus Cache, {c['remote']} remote, "
              f"{c['failed']} fehlgeschlagen (von {c['total']}).")
        print(f"Gehalt: {result['salary']['kept']} aus Anzeige behalten, "
              f"{result['salary']['estimated']} geschätzt.")
        if result["research_checked"]:
            print(f"Research-Stellen geprüft ({len(result['research_checked'])}):")
            for r in result["research_checked"]:
                flag = " (abgelaufen)" if r.get("verfuegbar") is False else ""
                print(f"  - {r['firma']} — {r['titel']}: Fit {r['fit']}%{flag}")
        print(f"Ausgeblendet (FIT < {FIT_BAND_AUSBLENDEN} %): "
              f"{result['deleted_fit_under_50']} Stelle(n).")
        print(f"Gelöscht (Pendelweg > {config.data.get('max_pendelzeit_min', MAX_COMMUTE_MINUTES)} min): "
              f"{result.get('deleted_commute', 0)} Stelle(n).")
        print(f"Gelöscht (Studenten-/Praktikumsstelle): "
              f"{result.get('deleted_student', 0)} Stelle(n).")
        print(f"Gelöscht (Technikerrolle): "
              f"{result.get('deleted_technician', 0)} Stelle(n).")
        if result.get("restored_documented"):
            print(f"Wieder sichtbar (Unterlagen vorhanden): "
                  f"{result['restored_documented']} Stelle(n).")
        if result.get("restored_reason"):
            print(f"Wieder sichtbar (FIT-Grund entfallen): "
                  f"{result['restored_reason']} Stelle(n).")
        if result.get("restored_active"):
            print(f"Wieder sichtbar (versendet/abgeschlossen, Flag war veraltet): "
                  f"{result['restored_active']} Stelle(n).")
        for s in result.get("zurueckgenommen", []):
            print(f"Zurück auf Research (FIT < {FIT_BAND_UNTERLAGEN} %): "
                  f"{s['firma']} — {s['titel']} ({s['fit']} %)")
        print(f"Automatisch beworben (FIT ≥ {FIT_BAND_UNTERLAGEN} %): "
              f"{result['generated_count']} Stelle(n).")
        run_dashboard(config)
        print(f"Dashboard aktualisiert: {config.dashboard_path}")

    elif args.command == "generate":
        ids = None
        if args.ids:
            ids = [int(x) for x in args.ids.split(",") if x.strip().isdigit()]
        template = getattr(args, "template", None)
        result = run_generate(config, profile, job_ids=ids, min_fit=args.fit, template=template)
        print(f"Dokumente erzeugt für {result['jobs_processed']} Stelle(n)"
              f" (Vorlage: {CV_TEMPLATES[template or config.data['documents'].get('lebenslauf_template') or DEFAULT_CV_TEMPLATE]['label']}):")
        for g in result["generated"]:
            print(f"  - {g['firma']} — {g['titel']}")
            for name, rel in g["dokumente"].items():
                print(f"      {name}: {rel}")
        skipped = result.get("skipped_commute") or []
        if skipped:
            print(f"  Übersprungen (Pendelweg > {config.data.get('max_pendelzeit_min', MAX_COMMUTE_MINUTES)} min): "
                  f"{len(skipped)} Stelle(n)")
            for s in skipped:
                print(f"      - {s.get('firma')} — {s.get('titel')} "
                      f"({s.get('pendelzeit_min')} min)")
        skipped_student = result.get("skipped_student") or []
        if skipped_student:
            print(f"  Übersprungen (Studenten-/Praktikumsstelle): {len(skipped_student)} Stelle(n)")
            for s in skipped_student:
                print(f"      - {s.get('firma')} — {s.get('titel')}")
        skipped_technician = result.get("skipped_technician") or []
        if skipped_technician:
            print(f"  Übersprungen (Technikerrolle): {len(skipped_technician)} Stelle(n)")
            for s in skipped_technician:
                print(f"      - {s.get('firma')} — {s.get('titel')}")
        run_dashboard(config)
        print(f"Dashboard aktualisiert: {config.dashboard_path}")

    elif args.command == "quality":
        result = run_quality(config)
        print(f"Qualitätsprüfung: {result['geprueft']} Bewerbung(en) mit Unterlagen geprüft, "
              f"{result['mit_befunden']} mit Befunden.")
        for d in result.get("details") or []:
            print(f"  - {d['firma']} — {d['titel']}")
            for b in d["befunde"]:
                print(f"      {b}")

    elif args.command == "followup":
        result = run_followup(config, profile, after_days=args.days, write=args.write)
        print(f"Nachfassen fällig (nach {result['after_days']} Tagen): "
              f"{len(result['due'])} Bewerbung(en).")
        for d in result["due"]:
            print(f"  - {d['firma']} — {d['titel']} ({d['tage']} Tage)")
        if result["written"]:
            print(f"Texte geschrieben: {len(result['written'])}")
            for p in result["written"]:
                print(f"  {p}")

    elif args.command == "cleanup":
        result = run_cleanup(config, dry_run=args.dry_run, max_age_days=args.days)
        n = result["to_delete"]
        if result.get("dry_run"):
            print(f"DRY RUN — {n} Ordner würden verschoben werden:")
            for f in result["folders"]:
                print(f"  [{f['status']:9s}] {f['firma']} — {f['titel']}  ({f['reason']})")
            print("\nZum Ausführen: python agent.py cleanup")
        else:
            print(f"Cleanup abgeschlossen: {result['moved']} Ordner verschoben nach {result['trash']}")

    elif args.command == "dashboard":
        result = run_dashboard(config)
        limit = config.data.get("max_pendelzeit_min", MAX_COMMUTE_MINUTES)
        print(f"Dashboard erzeugt: {result['path']} "
              f"({result['applications']} relevante Stellen; "
              f"{result['hidden_without_documents']} ohne Bewerbungsdokumente und "
              f"{result['hidden_too_far']} mit mehr als {limit} Minuten Pendelzeit ausgeblendet)")

    elif args.command == "status":
        _print_jobs(config)

    elif args.command == "pipeline":
        result = run_full(config, profile)
        print(f"Suche: {result['search']['count']} Stelle(n)")
        _print_job_context(result["search"]["context"])
        for err in result["search"]["errors"]:
            print(f"  ! {err}")
        print(f"Matching: {result['match']} Stelle(n)")
        print(f"Dokumente: {len(result['generated'])} Datei(en)")
        print(f"Dashboard: {result['dashboard']['path']}")

    elif args.command == "ablauf":
        from bewerbungsagent.orchestrator import run_abo
        review = not args.ohne_review
        try:
            result = run_abo(config, profile, review=review,
                             beschreibung=args.beschreibung)
        except (RuntimeError, ValueError) as exc:
            print(str(exc))
            return 1
        print(f"Ablauf durchlaufen: {' → '.join(result.get('weg', []))}")
        s = result.get("search") or {}
        print(f"  Suche          : {s.get('count', 0)} Stelle(n)")
        if s.get("triage_rejected"):
            print(f"  Triage verworfen: {s['triage_rejected']} (Protokoll: data/triage_rejected.json)")
        print(f"  Text nachladen  : Umfang {result.get('beschreibung_umfang', '?')}, "
              f"offen {result.get('triage_unsure_verbleibend', 0)}, "
              f"{result.get('beschreibung_versuche', 0)}× gelaufen")
        print(f"  Matching        : {(result.get('match') or {}).get('matched', 0)} Stelle(n)")
        print(f"  Dokumente       : {len((result.get('generate') or {}).get('generated', []))} Datei(en)")
        if review:
            print("  Freigabe        : erfolgt im Dashboard (Status ändern oder Eintrag löschen)")
        else:
            print("  Freigabe        : übersprungen (--ohne-review)")
        d = result.get("dashboard") or {}
        if d.get("path"):
            print(f"  Dashboard       : {d['path']} ({d.get('applications', 0)} relevant)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
