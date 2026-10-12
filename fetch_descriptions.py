"""Lädt die vollständigen Stellenbeschreibungen über einen echten Browser (Chromium).

Der Python-`requests`-Weg wurde von StepStone (Bot-Schutz) blockiert; ein echter
Headless-Browser rendert die Seite jedoch vollständig und zeigt die Abschnitte
„Was Sie erwartet" (Aufgaben) und „Was Sie mitbringen" (Anforderungen).

Ablauf:
1. Lädt ``data/jobs.json``.
2. Öffnet jede Stellen-Detail-URL im Headless-Chromium und extrahiert den
   Beschreibungstext (Aufgaben + Anforderungen).
3. Schreibt den Text als ``beschreibung``-Feld zurück in ``data/jobs.json``.
   Bereits befüllte Beschreibungen werden übersprungen (resume-fähig).

Nutzung:
    python fetch_descriptions.py [--limit N] [--headed]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from bewerbungsagent.config import Config

# Substrings, die den Beginn des Beschreibungsteils markieren (Aufgaben/Anforderungen/Benefits).
_START_SUBSTRINGS = [
    # Aufgaben
    "aufgabe", "aufgabengebiet", "erwartet", "your task", "your role", "your responsib",
    "what you", "what we expect", "what we are looking", "responsibilit", "the role",
    "was wir suchen", "was sie erwarten", "was dich erwartet", "was erwartet",
    # Anforderungen
    "mitbring", "bringst", "bringen sie", "bringen wir", "ihr profil", "dein profil",
    "your profile", "qualifikation", "anforderung", "requirement", "looking for",
    "your qualifications", "das bringst", "das bringen", "zeichnet",
    # Benefits (Beginn zählt ebenfalls, da wir bis zum Footer alles erfassen)
    "bieten", "offer", "benefits", "warum",
]

# Zeilen-Prefixe, die das Ende des Beschreibungsteils markieren (Footer/Benefits).
_END_PREFIXES = [
    "kontakt", "gehalt", "neugierig", "diese jobs waren", "pendelzeit",
    "mitarbeitervorteile", "unternehmensporträt", "ansprechpartner",
    "über den bewerbungsprozess", "jobs in", "ingenieurwesen jobs", "testing jobs",
    "qualitätsmanagement jobs", "jobs als",
]

_NOISE_BLOCKS = {
    "login", "genug gesucht?", "jetzt starten", "gehalt anzeigen", "schnelle bewerbung",
    "ich bin interessiert", "pendelzeit anzeigen", "zeig weitere", "speichern",
    "job finden", "job posten", "jobs finden",
}

# Textmarker für abgelaufene / nicht mehr verfügbare Stellenanzeigen.
_EXPIRED_MARKERS = [
    "nicht mehr verfügbar", "nicht mehr verfuegbar", "nicht mehr vorhanden",
    "not available", "no longer available", "this job ad isn't available",
    "job ad isn't available", "diese stellenanzeige ist", "anzeige ist abgelaufen",
    "job is no longer", "position has been filled", "position wurde besetzt",
    "stellenanzeige abgelaufen", "abgelaufen",
]


def _is_expired(text: str) -> bool:
    """Erkennt abgelaufene/nicht mehr verfügbare Stellenanzeigen im Seitentext."""
    low = text.lower()
    return any(m in low for m in _EXPIRED_MARKERS)


def _extract_description(text: str) -> str:
    """Extrahiert den relevanten Beschreibungsteil (Aufgaben + Anforderungen + Benefits)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""

    start_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if any(s in low for s in _START_SUBSTRINGS):
            start_idx = i
            break

    end_idx = len(lines)
    search_from = (start_idx + 1) if start_idx is not None else 0
    for i in range(search_from, len(lines)):
        low = lines[i].lower()
        if any(low.startswith(p) for p in _END_PREFIXES):
            end_idx = i
            break

    if start_idx is None:
        start_idx = 0

    body = [l for l in lines[start_idx:end_idx] if l.lower() not in _NOISE_BLOCKS]
    return "\n".join(body).strip()


def fetch_descriptions(config: Config, limit: int | None = None, headed: bool = False) -> dict:
    jobs_path = config.jobs_path()
    if not jobs_path.exists():
        print("Keine jobs.json gefunden. Zuerst `python agent.py search` ausführen.")
        return {"fetched": 0, "skipped": 0, "errors": 0}

    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    targets = [j for j in jobs if j.get("url") and not (j.get("beschreibung") or "").strip()]
    if limit:
        targets = targets[:limit]

    print(f"Zu laden: {len(targets)} von {len(jobs)} Stellen (ohne Beschreibung).")

    fetched = skipped = errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=not headed,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            locale="de-DE",
        )
        page = ctx.new_page()

        for i, job in enumerate(targets, 1):
            url = job["url"]
            firma = job.get("firma", "")[:24]
            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                # Lazy-Content laden (Beschreibung erscheint teils erst nach Scroll).
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(1200)
                page.mouse.wheel(0, 6000)
                page.wait_for_timeout(1200)
                text = page.inner_text("body")
                if _is_expired(text):
                    job["verfuegbar"] = False
                    skipped += 1
                    print(f"[{i}/{len(targets)}] ABGELAUFEN {firma}")
                else:
                    desc = _extract_description(text)
                    if desc:
                        job["beschreibung"] = desc
                        job["verfuegbar"] = True
                        fetched += 1
                        print(f"[{i}/{len(targets)}] OK   {firma:<24} ({len(desc)} Zeichen)")
                    else:
                        skipped += 1
                        print(f"[{i}/{len(targets)}] LEER {firma}")
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"[{i}/{len(targets)}] FEHL {firma}: {type(exc).__name__}")

            # Fortschritt nach jedem Job speichern (resume-fähig).
            jobs_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(1.0)

        ctx.close()
        browser.close()

    return {"fetched": fetched, "skipped": skipped, "errors": errors}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stellenbeschreibungen per Browser laden")
    parser.add_argument("--limit", type=int, default=None, help="max. Anzahl zu laden")
    parser.add_argument("--headed", action="store_true", help="sichtbaren Browser verwenden")
    args = parser.parse_args(argv)

    config = Config()
    result = fetch_descriptions(config, limit=args.limit, headed=args.headed)
    print(f"\nFertig: {result['fetched']} geladen, {result['skipped']} leer, {result['errors']} Fehler.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
