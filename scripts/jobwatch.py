#!/usr/bin/env python3
"""Job-Watch: führt die Bewerbungs-Pipeline aus und meldet neue Stellen per Telegram.

Ablauf pro Lauf:
  1. optional: agent.py search -> match -> enrich -> dashboard (venv-Python)
  2. Vergleich der aktuellen Stellen mit dem Snapshot des letzten Laufs
  3. Digest der neuen Stellen (Fit-Band 60-70 % = Research, > 70 % = Unterlagen bauen)
  4. Versand an Telegram (config.json in ~/telegram-bot) + Protokoll in data/watch_runs.json

Nutzung:
    python scripts/jobwatch.py                  # voller Lauf inkl. Suche
    python scripts/jobwatch.py --no-search      # nur auswerten, was schon in data/ liegt
    python scripts/jobwatch.py --dry-run        # nichts senden, Digest nur ausgeben
    python scripts/jobwatch.py --min-fit 60 --top 12
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib import parse, request

AGENT_DIR = Path(__file__).resolve().parent.parent
DATA = AGENT_DIR / "data"
SNAPSHOT = DATA / "watch_snapshot.json"
RUN_LOG = DATA / "watch_runs.json"
RUN_OUTPUT = DATA / "watch_last_run.log"
NOTIFY_CONFIG = Path(os.environ.get("NOTIFY_CONFIG", Path.home() / "telegram-bot" / "config.json"))
MAX_TG_LEN = 3800
# Ohne Text bewertet ``match`` nur den Titel, der nächste Lauf holt das nach.
# Ein Fehler hier darf die übrigen Schritte deshalb nicht verhindern.
OPTIONAL_STEPS = {"fetch"}
# Anzeigen pro Tageslauf nachladen (Browser). 300 × ~2,5 s ≈ 12 Minuten; reicht
# für einen Suchlauf, ohne den 07:00-Job endlos werden zu lassen.
FETCH_LIMIT = 300


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


def run_pipeline(timeout: int = 3600) -> bool:
    """search -> fetch -> match -> enrich -> dashboard.

    ``fetch`` gehört in den Tageslauf: StepStone und Arbeitnow liefern keine
    Anzeigentexte mehr, und ohne Text zählt nur der Titel — der Fit fällt auf
    0–34 % und keine Stelle erreicht mehr die 65-Prozent-Schwelle. Der Lauf ist
    auf ``FETCH_LIMIT`` Anzeigen begrenzt (Browser, ~2–3 s pro Anzeige).
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(AGENT_DIR)
    python = env.get("JOBWATCH_PYTHON") or str(Path.home() / ".venvs" / "bewerbungsagent" / "Scripts" / "python.exe")
    steps = [("search", []), ("fetch", ["--limit", str(FETCH_LIMIT)]),
             ("match", []), ("enrich", []), ("dashboard", [])]
    ok = True
    with RUN_OUTPUT.open("w", encoding="utf-8", errors="replace") as log:
        for step, extra in steps:
            log.write(f"\n##### {step} ({datetime.now().isoformat(timespec='seconds')})\n")
            log.flush()
            try:
                code = subprocess.run(
                    [python, "agent.py", step, *extra],
                    cwd=str(AGENT_DIR), env=env, timeout=timeout,
                    stdout=log, stderr=subprocess.STDOUT,
                ).returncode
            except subprocess.TimeoutExpired:
                code = -1
            log.write(f"##### {step} exit={code}\n")
            if code != 0:
                _log(f"Schritt '{step}' fehlgeschlagen (exit {code}) — siehe {RUN_OUTPUT}")
                ok = False
                if step not in OPTIONAL_STEPS:
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


def fit_band(score: int | float) -> str:
    if score > 70:
        return "Unterlagen"
    if score >= 60:
        return "Research"
    return ""


def parse_failed_sources(log_path: Path = RUN_OUTPUT) -> list[str]:
    """Findet Quellen, die im letzten Lauf einen Fehler geworfen haben.

    Die Pipeline loggt z. B. "! ats (Qualcomm): HTTPError". Fällt eine Quelle aus,
    fehlen deren Stellen im Dashboard — das muss sichtbar sein, statt still zu passieren.
    """
    if not log_path.exists():
        return []
    error_markers = ("httperror", "timeout", "traceback", "fehler", "error",
                     "exception", "connection", "403", "429", "500")
    failed: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("!") or "JobSpy" in stripped:
            continue
        # "! ats (X): 125 gefunden, 21 im Umkreis" ist eine Statistik, kein Fehler.
        if "gefunden" in stripped or "im Umkreis" in stripped:
            continue
        if not any(marker in stripped.lower() for marker in error_markers):
            continue
        name = stripped.lstrip("! ").split(":")[0].strip()
        if name and name not in failed:
            failed.append(name)
    return failed


def build_digest(jobs: list[dict], new_jobs: list[dict], baseline_created: bool,
                 min_fit: int, top: int, warnings: list[str] | None = None,
                 max_commute: int | None = None) -> str:
    today = datetime.now().strftime("%d.%m.%Y")

    def nah(job: dict) -> bool:
        """Pendelgrenze wie im Dashboard: zu weit = kein Vorschlag."""
        if max_commute is None:
            return True
        minuten = job.get("pendelzeit_min")
        return minuten is None or int(minuten) <= max_commute

    alle_passend = [j for j in jobs if (j.get("score") or 0) >= min_fit]
    zu_weit = [j for j in alle_passend if not nah(j)]
    relevant = [j for j in alle_passend if nah(j)]
    stark = [j for j in relevant if (j.get("score") or 0) > 70]

    lines: list[str] = []
    if baseline_created:
        lines.append(f"Bewerbungs-Watch — Baseline {today}")
        lines.append(f"Erster Lauf: {len(jobs)} Stellen erfasst, {len(relevant)} mit Fit ≥ {min_fit} %.")
    else:
        lines.append(f"Bewerbungs-Watch — {today}")
        lines.append(f"Bestand: {len(jobs)} · davon Fit ≥ {min_fit} %: {len(relevant)} · NEU in diesem Lauf: {len(new_jobs)}")
    if zu_weit and max_commute is not None:
        lines.append(f"  ({len(zu_weit)} Stelle(n) über der Pendelgrenze von {max_commute} min ausgeblendet.)")

    if warnings:
        lines.append("")
        lines.extend(f"⚠️ {w}" for w in warnings)

    picks = [j for j in (relevant if baseline_created else new_jobs)
             if (j.get("score") or 0) >= min_fit and nah(j)]
    picks.sort(key=lambda j: (j.get("score") or 0), reverse=True)

    if not picks:
        lines.append("")
        lines.append("Keine neuen Stellen im Fit-Band. Nichts zu tun.")
    else:
        lines.append("")
        for job in picks[:top]:
            score = int(job.get("score") or 0)
            band = fit_band(score)
            commute = job.get("pendelzeit_min")
            commute_txt = f", {commute} min Pendel" if commute else ""
            ort = (job.get("ort") or "").split(",")[0][:28]
            lines.append(f"• {score} % [{band}] {job.get('firma') or '?'} — {(job.get('titel') or '?')[:70]}")
            lines.append(f"  {ort}{commute_txt}")
            if job.get("url"):
                lines.append(f"  {job['url']}")
        if len(picks) > top:
            lines.append(f"… und {len(picks) - top} weitere (>= {min_fit} %).")

    if not baseline_created and stark:
        lines.append("")
        lines.append(f"Hinweis: {len(stark)} Stelle(n) über 70 % — dort lohnt ein Bewerbungsdokument.")

    text = "\n".join(lines)
    return text[:MAX_TG_LEN]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Neue Stellen finden und per Telegram melden.")
    parser.add_argument("--no-search", action="store_true", help="keine neue Websuche, nur data/ auswerten")
    parser.add_argument("--dry-run", action="store_true", help="nicht senden, nur ausgeben")
    parser.add_argument("--min-fit", type=int, default=60, help="Fit-Schwelle für den Digest (Standard 60)")
    parser.add_argument("--top", type=int, default=12, help="maximale Anzahl Stellen im Digest")
    parser.add_argument("--max-pendel", type=int, default=None,
                        help="Pendelgrenze in Minuten (Standard: max_pendelzeit_min aus config.json)")
    parser.add_argument("--always", action="store_true",
                        help="auch senden, wenn es nichts Neues gibt (Standard: still bleiben)")
    args = parser.parse_args(argv)

    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.no_search:
        _log("Pipeline startet (search -> match -> enrich -> dashboard) …")
        if not run_pipeline():
            _log("Pipeline unvollständig — Digest wird aus dem vorhandenen Stand gebaut.")

    jobs = load_jobs()
    previous: dict = {}
    if SNAPSHOT.exists():
        try:
            previous = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    # Der Digest liest seit 04.11. die Datenbank statt ``matches.json``. Alte
    # Snapshots enthalten die Roh-Treffer (662 statt 24) und würden einen
    # falschen „Bestand gefallen"-Alarm auslösen. Quelle wechselt → Baseline.
    quelle = "db-v1"
    quellenwechsel = bool(previous) and previous.get("quelle") != quelle
    known = set() if quellenwechsel else set(previous.get("keys") or [])
    baseline_created = not known
    new_jobs = [j for j in jobs if job_key(j) not in known]

    # Rückgang gegenüber dem letzten Lauf sichtbar machen: eine ausgefallene Quelle
    # (z. B. "! ats (Qualcomm): HTTPError") lässt Stellen still aus dem Dashboard fallen.
    warnings: list[str] = []
    prev_count = previous.get("count") or 0
    if quellenwechsel:
        _log("Quelle gewechselt (matches.json → Datenbank): Snapshot neu aufgebaut.")
    elif not baseline_created and len(jobs) < prev_count:
        failed = parse_failed_sources()
        if failed:
            warnings.append(
                f"Bestand gefallen ({prev_count} → {len(jobs)}): Quelle(n) mit Fehler im Lauf: "
                f"{', '.join(failed[:4])}. Diese Stellen fehlen im Dashboard bis zum nächsten erfolgreichen Lauf — "
                "nichts gelöscht, der Verlauf bleibt in der Datenbank."
            )
        else:
            warnings.append(
                f"Bestand gefallen ({prev_count} → {len(jobs)}), ohne Fehler in der Quelle: "
                "vermutlich abgelaufene Anzeigen."
            )

    digest = build_digest(jobs, new_jobs, baseline_created, args.min_fit, args.top, warnings,
                          max_commute=args.max_pendel if args.max_pendel is not None
                          else _pendelgrenze())
    print("\n" + digest + "\n")

    # Watchdog-Prinzip: ohne Neuigkeiten still bleiben (kein Rauschen im Chat) —
    # außer der Bestand ist messbar geschrumpft, dann ist eine Warnung nötig.
    should_send = baseline_created or bool(new_jobs) or bool(warnings) or args.always
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
                                             if (j.get("score") or 0) >= args.min_fit])),
        "telegram": sent,
        "dry_run": args.dry_run,
        "baseline_angelegt": baseline_created,
    })
    RUN_LOG.write_text(json.dumps(runs[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    _log(f"Snapshot aktualisiert: {len(jobs)} Stellen · neu: {len(new_jobs)} · Telegram: {'ja' if sent else 'nein'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
