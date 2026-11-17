#!/usr/bin/env python3
"""Job-Watch: führt die Bewerbungs-Pipeline aus und meldet neue Stellen per Telegram.

Ablauf pro Lauf:
  1. optional: alle Schritte aus bewerbungsagent/schritte.py über agent.py (venv-Python)
  2. Vergleich der aktuellen Stellen mit dem Snapshot des letzten Laufs
  3. Digest der neuen Stellen mit ihrem echten Stand (Unterlagen, Research, ohne Rollentitel)
     und der Quellen, deren Zustand sich seit der letzten Meldung geändert hat
  4. Versand an Telegram (config.json in ~/telegram-bot) + Protokoll in
     data/watch_runs.<rechner>.json (Snapshot und Protokoll gelten pro Rechner, ADR-061)

Nutzung:
    python scripts/jobwatch.py                  # voller Lauf inkl. Suche
    python scripts/jobwatch.py --no-search      # nur auswerten, was schon in data/ liegt
    python scripts/jobwatch.py --dry-run        # nichts senden, Digest nur ausgeben
    python scripts/jobwatch.py --min-fit 65 --top 12
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib import parse, request

# Code-Ort: Das Paket liegt neben ``scripts/``; ohne diesen Eintrag fände es nur
# ``PYTHONPATH``.
CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from bewerbungsagent.config import AGENT_ROOT  # noqa: E402
from bewerbungsagent.matching import fit_value, has_role_signal  # noqa: E402
from bewerbungsagent.schritte import SCHRITT_NAMEN, SCHRITTE  # noqa: E402

# Datenordner (``BEWERBUNGSAGENT_HOME``, sonst der Code-Ort, ADR-057).
AGENT_DIR = AGENT_ROOT
DATA = AGENT_DIR / "data"


def _rechnername() -> str:
    """Kurzname dieses Rechners für Dateinamen (``JOBWATCH_RECHNER`` überschreibt)."""
    roh = os.environ.get("JOBWATCH_RECHNER") or platform.node() or ""
    return re.sub(r"[^a-z0-9_-]+", "-", roh.lower()).strip("-") or "unbekannt"


# Snapshot, Laufliste und Laufausgabe gelten **pro Rechner** (ADR-061). Jeder
# Rechner hat seine eigene ``jobs.db`` (vom Drive-Sync ausgenommen), der Ordner
# ``data/`` wird aber synchronisiert. Mit einem gemeinsamen Snapshot verglich
# jeder Rechner seinen Bestand mit dem des anderen: 80 von 81 Stellen „neu".
RECHNER = _rechnername()
SNAPSHOT = DATA / f"watch_snapshot.{RECHNER}.json"
RUN_LOG = DATA / f"watch_runs.{RECHNER}.json"
RUN_OUTPUT = DATA / f"watch_last_run.{RECHNER}.log"
# Früherer, gemeinsamer Snapshot. Nur für die Umstellung gelesen, nie geschrieben.
ALT_SNAPSHOT_NAME = "watch_snapshot.json"
NOTIFY_CONFIG = Path(os.environ.get("NOTIFY_CONFIG", Path.home() / "telegram-bot" / "config.json"))
MAX_TG_LEN = 3800
# Fällt das Netz aus, sind alle Quellen betroffen: Der Digest bleibt trotzdem kurz.
MAX_QUELLEN = 8
MAX_GRUND = 160
# Bänder wie in ``pipeline`` (ADR-059): ab 65 % sichtbar, ab 71 % Unterlagen.
FIT_SICHTBAR = 65
FIT_UNTERLAGEN = 71


def _log(msg: str) -> None:
    print(f"[jobwatch] {msg}", flush=True)


def _pendelgrenze(default: int = 30) -> int:
    """Pendelgrenze aus ``config.json`` (``max_pendelzeit_min``).

    Der Digest listete zuvor auch Stellen mit 97 oder 293 Minuten Pendelweg,
    weil er nur den Fit prüfte. Das Dashboard blendet sie längst aus — der
    Alert muss dieselbe Grenze ziehen.
    """
    try:
        daten = json.loads((AGENT_DIR / "config.json").read_text(encoding="utf-8"))
        return int(daten.get("max_pendelzeit_min") or default)
    except Exception:
        return default


def _venv_python() -> Path:
    """Interpreter der Projekt-venv — auf beiden Plattformen.

    Windows legt ihn unter ``Scripts/python.exe`` ab, Linux/macOS unter
    ``bin/python``. Ein fest verdrahteter ``Scripts/python.exe``-Pfad ließ den
    Lauf unter Linux bei jedem Schritt scheitern.
    """
    venv_dir = Path.home() / ".venvs" / "bewerbungsagent"
    kandidaten = (
        venv_dir / "Scripts" / "python.exe",   # Windows
        venv_dir / "bin" / "python",           # Linux/macOS
    )
    return next((p for p in kandidaten if p.is_file()), venv_dir / "bin" / "python")


def _python_fuer_schritte(env: dict) -> str:
    """Interpreter für die Schrittprozesse.

    Reihenfolge: ``JOBWATCH_PYTHON`` → Projekt-venv → laufender Interpreter.
    Die venv kommt vor ``sys.executable``: wurde ``jobwatch.py`` mit dem
    System-Python gestartet, fehlen diesem die Abhängigkeiten (SQLAlchemy,
    Playwright, reportlab) — die Schritte brächen dann alle ab.
    """
    if env.get("JOBWATCH_PYTHON"):
        return env["JOBWATCH_PYTHON"]
    venv = _venv_python()
    return str(venv) if venv.is_file() else sys.executable


def run_pipeline(timeout: int = 3600) -> bool:
    """Führt jeden Schritt aus ``schritte.SCHRITTE`` als eigenen Prozess aus.

    So hat jeder Schritt sein Zeitlimit und seine Zeilen im Protokoll, und ein
    Absturz des Browsers trifft nicht den Digest. Ein optionaler Schritt darf
    scheitern, ein Pflichtschritt beendet die Folge.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(CODE_DIR)
    python = _python_fuer_schritte(env)
    RUN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ok = True
    with RUN_OUTPUT.open("w", encoding="utf-8", errors="replace") as log:
        for schritt in SCHRITTE:
            step = schritt.name
            log.write(f"\n##### {step} ({datetime.now().isoformat(timespec='seconds')})\n")
            log.flush()
            try:
                code = subprocess.run(
                    [python, str(CODE_DIR / "agent.py"), step, *schritt.argumente],
                    cwd=str(AGENT_DIR), env=env, timeout=timeout,
                    stdout=log, stderr=subprocess.STDOUT,
                ).returncode
            except subprocess.TimeoutExpired:
                code = -1
            log.write(f"##### {step} exit={code}\n")
            if code != 0:
                _log(f"Schritt '{step}' fehlgeschlagen (exit {code}) — siehe {RUN_OUTPUT}")
                ok = False
                if not schritt.optional:
                    break
    return ok


def load_jobs() -> list[dict]:
    """Bestand aus der Datenbank — nach Bereinigung, nicht aus ``matches.json``.

    ``matches.json`` enthält **alle** Treffer des Matchings. Was ``enrich``
    danach ausblendet (Pendelweg, Research-Filter, Studenten-/Technikerrollen)
    oder was als Dublette zusammengeführt wurde, steht dort weiterhin — der
    Telegram-Digest zeigte dadurch Stellen, die im Dashboard längst fehlen,
    und „NEU"-Zahlen, die niemand nachvollziehen konnte. Deshalb: DB lesen,
    gelöschte und abgeschlossene Vorgänge raus.
    """
    try:
        from bewerbungsagent.config import Config
        from bewerbungsagent.db import Store

        config = Config(AGENT_DIR / "config.json")
        apps = Store(config.db_path()).load_state().get("applications", [])
        offen = [a for a in apps
                 if not a.get("deleted")
                 and (a.get("status") or "research") not in
                 ("sent", "followup", "interview", "rejected", "absage", "beworben")]
        if offen or apps:
            return offen
    except Exception as exc:  # Datenbank nicht erreichbar → alte Quelle
        _log(f"Datenbank nicht lesbar ({exc}) — Digest aus matches.json.")
    path = DATA / "matches.json"
    if not path.exists():
        raise SystemExit(f"matches.json fehlt: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def job_key(job: dict) -> str:
    return f"{(job.get('url') or '').strip()}|{(job.get('titel') or '').strip()}"


def etikett(job: dict) -> str:
    """Stand einer Stelle, wie ihn das Dashboard zeigt — nicht nur das Fit-Band.

    Bis 13.11.2026 hing ``[Unterlagen]`` allein am Fit über 70 %. Gemeldet wurden so
    auch Stellen ohne Unterlagen und ohne passenden Rollentitel (Se3 „Staff Computer
    Vision Engineer", 94 %), für die der Lauf bewusst keine Unterlagen erzeugt.
    """
    if job.get("dokumente") and job.get("status") == "docs":
        return "Unterlagen erstellt"
    if job.get("pendel_knapp"):
        return f"Research, Pendel {job.get('pendelzeit_min')} min"
    if not has_role_signal(job.get("titel")):
        return "Research, kein Rollentitel"
    if fit_value(job) >= FIT_UNTERLAGEN:
        return "Unterlagen folgen"
    return "Research"


_SYMBOL = {"Unterlagen erstellt": "✅", "Unterlagen folgen": "📝", "Research": "🔎",
           "Research, kein Rollentitel": "❔"}


def symbol(job: dict) -> str:
    """Kurzform von :func:`etikett` für Telegram (17.11.2026: Nachrichten waren zu lang)."""
    text = etikett(job)
    if text.startswith("Research, Pendel"):
        return f"🚗{job.get('pendelzeit_min')}′"
    return _SYMBOL.get(text, "🔎")


def _kurz(text: str | None, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def quellen_zeilen(aenderungen: dict) -> list[str]:
    """Eine Zeile je Art der Änderung, nur Namen (der Fehlertext steht im Protokoll)."""
    zeilen: list[str] = []
    for schluessel, kopf in (("neu", "⚠️ Neu ausgefallen"), ("abgeschaltet", "⛔ Abgeschaltet")):
        namen = [name for name, _grund in (aenderungen.get(schluessel) or [])]
        if namen:
            rest = f" +{len(namen) - MAX_QUELLEN}" if len(namen) > MAX_QUELLEN else ""
            zeilen.append(f"{kopf}: {', '.join(namen[:MAX_QUELLEN])}{rest}")
    if aenderungen.get("wieder_da"):
        zeilen.append(f"✅ Wieder da: {', '.join(aenderungen['wieder_da'])}")
    return zeilen


def quellen_aenderungen(gemeldet: dict) -> tuple[dict, list[str]]:
    """Vergleicht die aktuellen Störungen mit dem zuletzt Gemeldeten.

    Die Historie kommt aus der Datenbank, nicht aus dem Lauf-Log: Dort stehen
    Fehler nur als Text, und Statistikzeilen ließen sich nur am Wortlaut trennen.
    Ist sie nicht lesbar, bleibt der Stand erhalten. Ein leeres Ergebnis hieße
    sonst, alle gemeldeten Quellen wären wieder da.
    """
    try:
        from bewerbungsagent.config import Config
        from bewerbungsagent.db import Store
        from bewerbungsagent.provider_health import aenderungen_seit, stoerungen

        config = Config(AGENT_DIR / "config.json")
        store = Store(config.db_path())
        health = store.get_meta("provider_health") or {}
        # Entfernte Quellen (glassdoor, jobleads) behalten ihre alten Einträge in der
        # Historie und tauchten am 17.11.2026 als „neu ausgefallen" wieder auf.
        aktiv = set((config.data.get("search") or {}).get("providers") or [])
        if aktiv:
            health = {name: e for name, e in health.items() if name in aktiv}
        aktuell = stoerungen(health, store.get_meta("board_health"))
    except Exception as exc:
        _log(f"Quellen-Historie nicht lesbar ({exc}) — keine Quellenmeldung in diesem Lauf.")
        return gemeldet, []
    stand, aenderungen = aenderungen_seit(gemeldet, aktuell)
    return stand, quellen_zeilen(aenderungen)


def build_digest(jobs: list[dict], new_jobs: list[dict], baseline_created: bool,
                 min_fit: int, top: int, warnings: list[str] | None = None,
                 max_commute: int | None = None, quellen: list[str] | None = None) -> str:
    """Kurzer Telegram-Digest: Kopfzeile, neue Stellen, eine Fußzeile.

    Symbole: ✅ Unterlagen erstellt · 📝 Unterlagen folgen · 🔎 Research ·
    ❔ Research ohne passenden Rollentitel · 🚗 Research wegen Pendelweg (Minuten).
    """
    today = datetime.now().strftime("%d.%m.")

    def nah(job: dict) -> bool:
        """Pendelgrenze wie im Dashboard; Stellen in der Kulanz sind Research."""
        if max_commute is None or job.get("pendel_knapp"):
            return True
        minuten = job.get("pendelzeit_min")
        return minuten is None or int(minuten) <= max_commute

    relevant = [j for j in jobs if fit_value(j) >= min_fit and nah(j)]
    bereit = [j for j in jobs if j.get("status") == "docs" and j.get("dokumente")]
    # Passende Rollen zuerst, dann nach Fit: Sonst standen oben nur ❔-Stellen, deren
    # hoher Fit aus allgemeinen Begriffen kommt (17.11.2026).
    picks = sorted((j for j in (relevant if baseline_created else new_jobs)
                    if fit_value(j) >= min_fit and nah(j)),
                   key=lambda j: (symbol(j) != "❔", fit_value(j)), reverse=True)

    kopf = f"💼 Bewerbung {today}"
    if baseline_created:
        kopf += f" · Start: {len(relevant)} Stellen ab {min_fit} %"
    elif picks:
        kopf += f" · {len(picks)} neu"
    lines = [kopf]
    lines.extend(f"⚠️ {w}" for w in warnings or [])
    for job in picks[:top]:
        lines.append(f"{symbol(job)} {fit_value(job)} % {_kurz(job.get('firma') or '?', 25)} – "
                     f"{_kurz(job.get('titel') or '?', 55)}")
        if job.get("url"):
            lines.append(f"   {job['url']}")
    fuss = []
    if len(picks) > top:
        fuss.append(f"+{len(picks) - top} weitere")
    if bereit and not baseline_created:
        fuss.append(f"📄 {len(bereit)} Unterlagen bereit")
    if fuss:
        lines.append(" · ".join(fuss))
    lines.extend(quellen or [])
    return "\n".join(lines)[:MAX_TG_LEN]


def _ssl_context():
    """Windows-Python vertraut dem GoDaddy-Root von api.telegram.org nicht immer.

    Deshalb: Standard-Kontext versuchen, sonst certifi-Bundle nehmen.
    """
    import ssl
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def send_telegram(text: str) -> bool:
    try:
        cfg = json.loads(NOTIFY_CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"Telegram-Konfiguration nicht lesbar ({NOTIFY_CONFIG}): {exc}")
        return False
    token = cfg.get("bot_token")
    chats = cfg.get("allowed_chat_ids") or []
    if not token or not chats:
        _log("Kein bot_token/chat_id in der Konfiguration — Versand übersprungen.")
        return False
    ok = True
    for chat_id in chats:
        payload = parse.urlencode(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
        ).encode()
        try:
            with request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=payload, timeout=25,
                                 context=_ssl_context()) as resp:
                body = json.loads(resp.read().decode())
            if not body.get("ok"):
                _log(f"Telegram lehnte Nachricht ab: {body.get('description')}")
                ok = False
            else:
                _log(f"Telegram: Nachricht an {chat_id} gesendet.")
        except Exception as exc:
            _log(f"Telegram-Versand fehlgeschlagen: {exc}")
            ok = False
    return ok


def _umstellung_auf_rechner_snapshot(jobs: list[dict], quelle: str) -> dict:
    """Erster Lauf nach ADR-061: Ausgangsstand ohne Meldung.

    Gibt es noch den gemeinsamen ``watch_snapshot.json``, lief der Watch hier
    schon. Dessen Schlüssel stammen aber womöglich vom anderen Rechner und
    taugen nicht zum Vergleich. Der aktuelle Bestand gilt deshalb als bekannt;
    nur die schon gemeldeten Quellenänderungen werden übernommen. Ohne alten
    Snapshot bleibt es beim gewohnten Erstlauf (Baseline wird gemeldet).
    """
    alt = SNAPSHOT.parent / ALT_SNAPSHOT_NAME
    if alt == SNAPSHOT or not alt.exists():
        return {}
    try:
        gemeldet = json.loads(alt.read_text(encoding="utf-8")).get("gemeldete_quellen") or {}
    except Exception:
        gemeldet = {}
    _log(f"Eigener Snapshot für Rechner '{RECHNER}' angelegt — aktueller Bestand "
         f"({len(jobs)}) gilt als bekannt, keine Meldung neuer Stellen.")
    return {"quelle": quelle, "count": len(jobs), "keys": [job_key(j) for j in jobs],
            "gemeldete_quellen": gemeldet}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Neue Stellen finden und per Telegram melden.")
    parser.add_argument("--no-search", action="store_true", help="keine neue Websuche, nur data/ auswerten")
    parser.add_argument("--dry-run", action="store_true", help="nicht senden, nur ausgeben")
    parser.add_argument("--min-fit", type=int, default=FIT_SICHTBAR,
                        help=f"Fit-Schwelle für den Digest (Standard {FIT_SICHTBAR})")
    parser.add_argument("--top", type=int, default=5, help="maximale Anzahl Stellen im Digest")
    parser.add_argument("--max-pendel", type=int, default=None,
                        help="Pendelgrenze in Minuten (Standard: max_pendelzeit_min aus config.json)")
    parser.add_argument("--always", action="store_true",
                        help="auch senden, wenn es nichts Neues gibt (Standard: still bleiben)")
    args = parser.parse_args(argv)

    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Ein frischer Datenordner (neuer Rechner, neuer BEWERBUNGSAGENT_HOME) hat
    # noch kein ``data/``. Ohne den Ordner scheiterten Protokoll und Snapshot
    # mit FileNotFoundError, bevor der erste Schritt lief.
    DATA.mkdir(parents=True, exist_ok=True)

    if not args.no_search:
        _log(f"Pipeline startet ({' -> '.join(SCHRITT_NAMEN)}) …")
        if not run_pipeline():
            _log("Pipeline unvollständig — Digest wird aus dem vorhandenen Stand gebaut.")

    jobs = load_jobs()
    quelle = "db-v1"
    previous: dict = {}
    if SNAPSHOT.exists():
        try:
            previous = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    else:
        previous = _umstellung_auf_rechner_snapshot(jobs, quelle)
    # Der Digest liest seit 04.11. die Datenbank statt ``matches.json``. Alte
    # Snapshots enthalten die Roh-Treffer (662 statt 24) und würden einen
    # falschen „Bestand gefallen"-Alarm auslösen. Quelle wechselt → Baseline.
    quellenwechsel = bool(previous) and previous.get("quelle") != quelle
    known = set() if quellenwechsel else set(previous.get("keys") or [])
    baseline_created = not known
    new_jobs = [j for j in jobs if job_key(j) not in known]

    # Der Bestand kommt aus der Datenbank und schrumpft nicht, wenn eine Quelle
    # ausfällt. Ein Rückgang heißt: Einträge wurden gelöscht, versendet oder
    # ausgeblendet. Ausfälle meldet ``quellen_aenderungen`` unabhängig davon.
    warnings: list[str] = []
    prev_count = previous.get("count") or 0
    if quellenwechsel:
        _log("Quelle gewechselt (matches.json → Datenbank): Snapshot neu aufgebaut.")
    elif not baseline_created and len(jobs) < prev_count:
        warnings.append(f"Bestand gefallen ({prev_count} → {len(jobs)})")

    gemeldet = previous.get("gemeldete_quellen") or {}
    quellen_stand, quellen = quellen_aenderungen(gemeldet)

    digest = build_digest(jobs, new_jobs, baseline_created, args.min_fit, args.top, warnings,
                          max_commute=args.max_pendel if args.max_pendel is not None
                          else _pendelgrenze(), quellen=quellen)
    print("\n" + digest + "\n")

    # Watchdog-Prinzip: ohne Neuigkeiten still bleiben (kein Rauschen im Chat) —
    # außer der Bestand ist messbar geschrumpft oder eine Quelle hat sich geändert.
    should_send = (baseline_created or bool(new_jobs) or bool(warnings) or bool(quellen)
                   or args.always)
    sent = False
    if not args.dry_run and should_send:
        sent = send_telegram(digest)
    elif not should_send:
        _log("Keine neuen Stellen — keine Nachricht gesendet.")

    # Snapshot erst nach erfolgreichem Lauf fortschreiben, damit nichts verloren geht
    SNAPSHOT.write_text(json.dumps({
        "updated": datetime.now().isoformat(timespec="seconds"),
        "quelle": quelle,
        "count": len(jobs),
        "keys": [job_key(j) for j in jobs],
        # Nur Zugestelltes gilt als gemeldet: Kam die Nachricht nicht an oder war
        # es ein Probelauf, erscheint die Änderung im nächsten Digest erneut.
        "gemeldete_quellen": quellen_stand if sent or not quellen else gemeldet,
    }, ensure_ascii=False), encoding="utf-8")

    runs = []
    if RUN_LOG.exists():
        try:
            runs = json.loads(RUN_LOG.read_text(encoding="utf-8"))
        except Exception:
            runs = []
    runs.append({
        "zeitpunkt": datetime.now().isoformat(timespec="seconds"),
        "bestand": len(jobs),
        "neu": len(new_jobs),
        "digest_stellen": min(args.top, len([j for j in (jobs if baseline_created else new_jobs)
                                             if fit_value(j) >= args.min_fit])),
        "telegram": sent,
        "dry_run": args.dry_run,
        "baseline_angelegt": baseline_created,
    })
    RUN_LOG.write_text(json.dumps(runs[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    _log(f"Snapshot aktualisiert: {len(jobs)} Stellen · neu: {len(new_jobs)} · Telegram: {'ja' if sent else 'nein'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
