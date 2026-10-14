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

from bewerbungsagent.cleanup import run_cleanup
from bewerbungsagent.config import Config
from bewerbungsagent.documents import CV_TEMPLATES, DEFAULT_CV_TEMPLATE
from bewerbungsagent.pipeline import (
    load_config_and_profile,
    run_dashboard,
    run_enrich,
    run_full,
    run_generate,
    run_import_old,
    run_match,
    run_search,
)
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
    sub = parser.add_subparsers(dest="command", required=True)

    ssearch = sub.add_parser("search", help="Web-Suche nach Stellenangeboten ausführen")
    ssearch.add_argument("name", nargs="?", default=None,
                         help="Name einer gespeicherten Suche (siehe `agent.py searches`)")
    sub.add_parser("searches", help="Gespeicherte Suchen auflisten")
    sub.add_parser("fetch", help="Vollständige Stellenbeschreibungen per Browser laden")
    sub.add_parser("match", help="Fit-Scoring gegen das Skill-Profil ausführen")
    sub.add_parser("import-old", help="Inhalt des alten Dashboards übernehmen")
    sub.add_parser("enrich", help="Pendelweg + Gehalt + Bereinigung (FIT-Filter) + Auto-Bewerbung")
    cln = sub.add_parser("cleanup", help="Alte Bewerbungsordner aufräumen")
    cln.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts verschieben")
    cln.add_argument("--days", type=int, default=60, help="Altersgrenze in Tagen (Standard 60)")
    sub.add_parser("dashboard", help="HTML-Dashboard (neu) erzeugen")
    sub.add_parser("status", help="Übersicht der aktuellen Stellen anzeigen")
    sub.add_parser("pipeline", help="Vollständigen Ablauf ausführen")

    gen = sub.add_parser("generate", help="Bewerbungsunterlagen erzeugen")
    gen.add_argument("--all", action="store_true", help="alle passenden Stellen (gem. min_fit)")
    gen.add_argument("--ids", help="kommagetrennte Job-IDs, z. B. 1,2,3")
    gen.add_argument("--fit", choices=["hoch", "mittel", "niedrig"], default=None,
                     help="Mindest-Fit für --all")
    gen.add_argument("--template", choices=sorted(CV_TEMPLATES), default=None,
                     help="Lebenslauf-Vorlage (Standard: aus config.json)")

    args = parser.parse_args(argv)

    config, profile = load_config_and_profile()

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
                flag = "" if r["verfuegbar"] else " (abgelaufen)"
                print(f"  - {r['firma']} — {r['titel']}: Fit {r['fit']}%{flag}")
        print(f"Gelöscht (FIT < 50 %): {result['deleted_fit_under_50']} Stelle(n).")
        print(f"Gelöscht (Pendelweg > {config.data.get('max_pendelzeit_min', 90)} min): "
              f"{result.get('deleted_commute', 0)} Stelle(n).")
        print(f"Automatisch bewerbt (FIT > 65 %): {result['generated_count']} Stelle(n).")
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
            print(f"  Übersprungen (Pendelweg > {config.data.get('max_pendelzeit_min', 90)} min): "
                  f"{len(skipped)} Stelle(n)")
            for s in skipped:
                print(f"      - {s.get('firma')} — {s.get('titel')} "
                      f"({s.get('pendelzeit_min')} min)")
        run_dashboard(config)
        print(f"Dashboard aktualisiert: {config.dashboard_path}")

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
        print(f"Dashboard erzeugt: {result['path']} "
              f"({result['applications']} relevante Stellen; "
              f"{result['hidden_without_documents']} ohne Bewerbungsdokumente und "
              f"{result['hidden_too_far']} mit mehr als 90 Minuten Pendelzeit ausgeblendet)")

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
