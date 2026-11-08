#!/usr/bin/env python3
"""Kommandozeilen-Einstieg für den Bewerbungsagenten.

Beispiele:
    python agent.py search
    python agent.py match
    python agent.py generate --all
    python agent.py generate --ids 1,2,3
    python agent.py dashboard
    python agent.py pipeline     # alle Schritte aus bewerbungsagent/schritte.py
    python agent.py status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bewerbungsagent.cleanup import run_cleanup
from bewerbungsagent.commute import MAX_COMMUTE_MINUTES
from bewerbungsagent.config import Config
from bewerbungsagent.db import Store
from bewerbungsagent.documents import CV_TEMPLATES, DEFAULT_CV_TEMPLATE
from bewerbungsagent.followup import run_followup
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
from bewerbungsagent.profile_export import (
    export_profile_markdown,
    profile_markdown_stale,
)
from bewerbungsagent.provider_health import is_disabled, set_enabled
from bewerbungsagent.provider_health import reset as reset_health
from bewerbungsagent.quality import run_quality
from bewerbungsagent.saved_searches import (
    find_saved_search,
    load_saved_searches,
    to_definition,
)
from bewerbungsagent.storage import load_json, now_iso


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


def _print_provider_stats(stats: dict) -> None:
    """Zeigt je Quelle, wie viele Funde sie beigetragen hat (und ob sie lief)."""
    if not stats:
        return
    print("Quellen:")
    for name, st in stats.items():
        if st.get("uebersprungen"):
            print(f"  - {name}: übersprungen ({st['uebersprungen']})")
            continue
        fehler = len(st.get("fehler") or [])
        print(f"  - {name}: {st.get('gefunden', 0)} Fund(e)"
              + (f", {fehler} Fehler" if fehler else ""))
        for hinweis in st.get("hinweise") or []:
            print(f"      {hinweis}")


def _print_failed(failed: list[dict]) -> None:
    """Meldet Stellen, deren Unterlagen nicht erzeugt werden konnten."""
    if failed:
        print(f"Unterlagen fehlgeschlagen: {len(failed)} Stelle(n).")
    for f in failed:
        print(f"  ! {f['firma']} — {f['titel']}: {f['fehler']}")


def _print_schritt_fehler(fehler: dict) -> None:
    """Meldet optionale Schritte, die gescheitert sind."""
    for name, text in (fehler or {}).items():
        print(f"  ! Schritt {name} fehlgeschlagen: {text}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bewerbungsagent")
    parser.add_argument("--config", default=None,
                        help="Pfad zur config.json (Standard: ./config.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    ssearch = sub.add_parser("search", help="Web-Suche nach Stellenangeboten ausführen")
    ssearch.add_argument("name", nargs="?", default=None,
                         help="Name einer gespeicherten Suche (siehe `agent.py searches`)")
    sub.add_parser("searches", help="Gespeicherte Suchen auflisten")
    fetch_p = sub.add_parser("fetch", help="Vollständige Stellenbeschreibungen per Browser laden")
    fetch_p.add_argument("--limit", type=int, default=None,
                         help="höchstens N Anzeigen laden (Standard: alle ohne Text)")
    fetch_p.add_argument("--only-unsure", action="store_true",
                         help="nur Stellen, deren Titel allein nicht für die Triage reicht")
    sub.add_parser("match", help="Fit-Scoring gegen das Skill-Profil ausführen")
    sub.add_parser("import-old", help="Inhalt des alten Dashboards übernehmen")
    sub.add_parser("enrich", help="Pendelweg + Gehalt + Bereinigung (FIT-Filter) + Auto-Bewerbung")
    sub.add_parser("quality", help="Erzeugte Unterlagen unabhängig prüfen (Fakten, Pflichtteile, PDF)")
    fo = sub.add_parser("followup", help="Fällige Nachfassen anzeigen (optional Texte schreiben)")
    fo.add_argument("--days", type=int, default=None,
                    help="Wartezeit in Tagen (Standard: aus config.json, sonst 14)")
    fo.add_argument("--write", action="store_true",
                    help="Follow-up-Text in den jeweiligen Bewerbungsordner schreiben")
    prov = sub.add_parser("providers", help="Zustand der Such-Quellen anzeigen / ein- und ausschalten")
    prov.add_argument("--enable", metavar="NAME", default=None,
                      help="Quelle wieder einschalten (setzt den Fehlerzähler zurück)")
    prov.add_argument("--disable", metavar="NAME", default=None,
                      help="Quelle manuell abschalten")
    prov.add_argument("--reset", action="store_true",
                      help="gesamte Historie löschen (alle Quellen wieder aktiv)")
    cln = sub.add_parser("cleanup", help="Alte Bewerbungsordner aufräumen")
    cln.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts verschieben")
    cln.add_argument("--days", type=int, default=60, help="Altersgrenze in Tagen (Standard 60)")
    sub.add_parser("dashboard", help="HTML-Dashboard (neu) erzeugen")
    pe = sub.add_parser("profile-export",
                        help="Markdown-Lesefassung des Profils aus der JSON erzeugen")
    pe.add_argument("--out", help="Zielpfad (Standard: profile_markdown aus config.json)")
    pe.add_argument("--check", action="store_true",
                    help="nur prüfen; Exit 1, wenn die Datei vom JSON-Stand abweicht")
    sub.add_parser("status", help="Übersicht der aktuellen Stellen anzeigen")
    ab = sub.add_parser("absagen",
                        help="Absagen aus exportierten Mails erkennen und zuordnen")
    ab.add_argument("--mails", required=True,
                    help="JSON-Liste mit id, date, from, subject, body (z. B. aus dem Mailcheck)")
    ab.add_argument("--apply", action="store_true",
                    help="eindeutige Zuordnungen als 'rejected' in die DB schreiben")
    ab.add_argument("--out", default=None,
                    help="Ergebnis zusätzlich als JSON speichern (Format von scripts/apply_status.py)")
    ab.add_argument("--out-result", default=None, dest="out_result",
                    help="Vollständiges Ergebnis als JSON (updates, unklar, positiv) — "
                         "für den Mailcheck, der die Mails danach als gelesen markiert")
    li = sub.add_parser("leads-import",
                        help="Leads aus Job-Mails (Firma + Titel) in den manuellen Import aufnehmen")
    li.add_argument("--file", required=True,
                    help="JSON-Liste mit firma, titel, ort, quelle (z. B. aus dem Mailcheck)")
    sl = sub.add_parser("shortlist",
                        help="Wochenauswahl: fertige, noch nicht versendete Bewerbungen nach Fit")
    sl.add_argument("--top", type=int, default=8, help="Anzahl (Standard 8)")
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
        _print_provider_stats(result.get("provider_stats") or {})
        for err in result["errors"]:
            print(f"  ! {err}")
        print(f"Ergebnis: {result['path']}")
        print("Tipp: `python agent.py fetch` lädt die vollständigen Beschreibungen per Browser.")

    elif args.command == "searches":
        searches = load_saved_searches(config)
        print(f"{len(searches)} gespeicherte Suche(n):")
        for s in searches:
            marker = " · Tageslauf" if s.get("daily") else ""
            print(f"  - {s['name']}: {len(s.get('query_terms', []))} Begriffe · "
                  f"Ort {s.get('location', '?')} · Provider {', '.join(s.get('providers', []))}"
                  f"{marker}")

    elif args.command == "fetch":
        from fetch_descriptions import fetch_descriptions
        result = fetch_descriptions(config, limit=args.limit, only_unsure=args.only_unsure)
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
        _print_failed(result.get("failed") or [])
        if result.get("skipped_budget"):
            print(f"Zurückgestellt (Wochenbudget erreicht): {len(result['skipped_budget'])} "
                  "Stelle(n) — kommen nächste Woche dran.")
        if result.get("skipped_firma"):
            print(f"Zurückgestellt (schon genug offene Bewerbungen bei der Firma): "
                  f"{len(result['skipped_firma'])} Stelle(n).")
            for s in result["skipped_firma"]:
                print(f"  - {s['firma']} — {s['titel']} ({s['fit']} %)")
        if result.get("pendel_knapp"):
            print(f"Pendelweg knapp über der Grenze, als Research behalten: "
                  f"{result['pendel_knapp']} Stelle(n).")
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
        _print_failed(result.get("failed") or [])
        if result.get("skipped_bestand"):
            print(f"  Übersprungen (Dublette, gelöscht oder abgeschlossen): "
                  f"{result['skipped_bestand']} Stelle(n)")
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

    elif args.command == "providers":
        store = Store(config.db_path())
        health = store.get_meta("provider_health") or {}
        if args.reset:
            health = reset_health(health)
        if args.enable:
            health = set_enabled(health, args.enable, True, now=now_iso())
        if args.disable:
            health = set_enabled(health, args.disable, False, now=now_iso())
        if args.reset or args.enable or args.disable:
            store.set_meta("provider_health", health)
        if not health:
            print("Noch keine Statistik — sie entsteht beim nächsten Suchlauf.")
            return 0
        print(f"{'Quelle':<12} {'Status':<6} {'Läufe':>5} {'Fehler':>6} {'Serie':>5} "
              f"{'Funde':>6}  letzter Fehler")
        for name in sorted(health):
            e = health[name]
            status = "AUS" if is_disabled(health, name) else "aktiv"
            letzter = (e.get("letzter_fehler_text") or "–")[:60]
            print(f"{name:<12} {status:<6} {e.get('laeufe', 0):>5} {e.get('fehler', 0):>6} "
                  f"{e.get('serie_fehler', 0):>5} {e.get('gefunden', 0):>6}  {letzter}")

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

    elif args.command == "profile-export":
        ziel = Path(args.out) if args.out else (config.data.get("profile_markdown") or "").strip()
        if not ziel:
            print("✗ Kein Ziel: --out angeben oder profile_markdown in config.json setzen.")
            return 2
        ziel = Path(ziel)
        if args.check:
            veraltet = profile_markdown_stale(config.profile_path, ziel)
            print(("✗ veraltet: " if veraltet else "✓ aktuell: ") + str(ziel))
            return 1 if veraltet else 0
        export_profile_markdown(config.profile_path, ziel)
        print(f"Profil-Markdown geschrieben: {ziel}")
        return 0

    elif args.command == "status":
        _print_jobs(config)

    elif args.command == "absagen":
        import json

        from bewerbungsagent.absagen import auswerten, overlay_from_updates, positives
        mails = json.loads(Path(args.mails).read_text(encoding="utf-8"))
        store = Store(config.db_path())
        apps = store.load_state().get("applications", [])
        r = auswerten(mails, apps)
        pos = positives(mails, apps)
        print(f"Mails geprüft: {len(mails)} — Absagen zugeordnet: {len(r['updates'])}, "
              f"unklar: {len(r['unklar'])}, keine Absage: {r['keine_absage']}, "
              f"schon erfasst: {r.get('schon_erfasst', 0)}, "
              f"Einladungen/Zusagen: {len(pos)}")
        for u in r["updates"]:
            tp = ", Talentpool" if u["absage_talentpool"] else ""
            print(f"  ✓ {u['statusChangedAt']}  {u['firma']} — {u['titel']}  "
                  f"[{u['absage_grund']}{tp}]")
        for u in r["unklar"]:
            print(f"  ? {u['datum']}  {u['betreff']}  → {u['warum']}")
        for p in pos:
            ziel = f"{p['firma']} — {p['titel']}" if p.get("key") else (p.get("betreff") or "?")
            print(f"  {'+' if p['ok'] else '!'} {p['datum']}  {ziel}  [{p['art']}]  "
                  f"{p['hinweis'] or 'Dashboard: versendet'}")
        if args.out:
            Path(args.out).write_text(json.dumps(r["updates"], ensure_ascii=False, indent=2),
                                      encoding="utf-8")
            print(f"Gespeichert: {args.out}")
        if args.out_result:
            Path(args.out_result).write_text(
                json.dumps({**r, "positiv": pos}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        if args.apply and r["updates"]:
            store.apply_overlay(overlay_from_updates(r["updates"]))
            store.export_json(config.state_path())
            print(f"In die Datenbank übernommen: {len(r['updates'])} Absage(n).")
        elif r["updates"]:
            print("Nichts geschrieben — mit --apply übernehmen.")


    elif args.command == "leads-import":
        import json

        from bewerbungsagent.search.manual import merge_mail_leads
        leads = json.loads(Path(args.file).read_text(encoding="utf-8"))
        neu = merge_mail_leads(config.import_path(), leads)
        print(f"Leads übernommen: {neu} neu, {len(leads) - neu} bekannt oder unvollständig "
              f"({config.import_path()}).")

    elif args.command == "shortlist":
        from bewerbungsagent.auswahl import shortlist
        apps = Store(config.db_path()).load_state().get("applications", [])
        liste = shortlist(apps, top=args.top)
        if not liste:
            print("Keine fertigen, unversendeten Bewerbungen.")
            return 0
        print(f"Wochenauswahl ({len(liste)}): vor dem Versand Ansprechpartner klären "
              "und kurz zur Firma recherchieren.")
        for i, s in enumerate(liste, 1):
            hinweise = []
            if s["kontakt_fehlt"]:
                hinweise.append("Ansprechpartner fehlt")
            if s["pendel_knapp"]:
                hinweise.append("Pendelweg knapp drüber")
            print(f"{i:>2}. {s['fit']:>3} %  {s['firma']} — {s['titel']} ({s['ort'] or '?'})"
                  + (f"  [{', '.join(hinweise)}]" if hinweise else ""))
            if s.get("url"):
                print(f"      {s['url']}")

    elif args.command == "pipeline":
        result = run_full(config, profile)
        print(f"Suche: {result['search']['count']} Stelle(n)")
        _print_job_context(result["search"]["context"])
        for err in result["search"]["errors"]:
            print(f"  ! {err}")
        f = result.get("fetch") or {}
        print(f"Anzeigentexte: {f.get('fetched', 0)} geladen, {f.get('skipped', 0)} leer, "
              f"{f.get('errors', 0)} Fehler")
        print(f"Matching: {result['match']} Stelle(n)")
        print(f"Dokumente: {len(result['generated'])} Datei(en)")
        _print_failed(result.get("failed") or [])
        q = result.get("quality") or {}
        print(f"Qualität: {q.get('geprueft', 0)} geprüft, {q.get('mit_befunden', 0)} mit Befunden")
        print(f"Dashboard: {result['dashboard']['path']}")
        _print_schritt_fehler(result.get("fehler"))

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
        _print_failed([*(result.get("enrich") or {}).get("failed", []),
                       *(result.get("generate") or {}).get("failed", [])])
        if review:
            print("  Freigabe        : erfolgt im Dashboard (Status ändern oder Eintrag löschen)")
        else:
            print("  Freigabe        : übersprungen (--ohne-review)")
        d = result.get("dashboard") or {}
        if d.get("path"):
            print(f"  Dashboard       : {d['path']} ({d.get('applications', 0)} relevant)")
        _print_schritt_fehler(result.get("fehler"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
