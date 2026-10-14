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
from contextlib import contextmanager

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
#
# Bewusst *kontextgebundene* Muster: Die Seite wird als kompletter ``body``-Text
# gelesen und Jobbörsen listen darauf reihenweise fremde Anzeigen (Sidebar,
# „Weitere Jobs", Footer). Ein nacktes ``"abgelaufen"`` oder ein Präfix wie
# ``"diese stellenanzeige ist"`` schlägt dort ständig zu und markiert aktive
# Stellen als abgelaufen. Deshalb immer Wort + Bezug auf die Anzeige/Stelle.
_EXPIRED_PATTERNS = [
    r"nicht mehr verf[üu]gbar",
    r"nicht mehr vorhanden",
    r"no longer available",
    r"isn'?t available (anymore|any longer)?",
    r"(stellen|job)?anzeige\s+(ist|wurde)\s+(leider\s+)?(abgelaufen|entfernt|geschlossen|deaktiviert|offline)",
    r"anzeige\s+ist\s+abgelaufen",
    r"(bewerbungs)?frist\s+(ist\s+)?(abgelaufen|beendet|vorbei)",
    r"(diese\s+)?(stelle|position)\s+(ist|wurde)\s+(leider\s+)?(besetzt|geschlossen|abgelaufen|entfernt)",
    r"job\s+is\s+no\s+longer",
    r"(position|role)\s+has\s+been\s+filled",
    r"this\s+(position|role|job)\s+is\s+(no longer|closed|filled)",
    r"nicht\s+mehr\s+vakant",
]

_EXPIRED_RE = re.compile("|".join(_EXPIRED_PATTERNS), re.IGNORECASE)


def _is_expired(text: str) -> str | None:
    """Liefert den erkannten Marker oder ``None``, wenn die Anzeige verfügbar wirkt.

    Der Marker wird zurückgegeben (statt nur ``True``), damit sich Fehlalarme
    später am gespeicherten ``verfuegbar_grund`` nachvollziehen lassen.
    """
    match = _EXPIRED_RE.search(text)
    return match.group(0) if match else None


def _extract_description(text: str) -> str:
    """Extrahiert den relevanten Beschreibungsteil (Aufgaben + Anforderungen + Benefits)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
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

    body = [ln for ln in lines[start_idx:end_idx] if ln.lower() not in _NOISE_BLOCKS]
    return "\n".join(body).strip()


_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


@contextmanager
def browser_page(*, headed: bool = False):
    """Headless-Chromium mit deutschem Kontext als Kontextmanager.

    StepStone und Xing blockieren einfache HTTP-Clients; die Seiten brauchen
    einen echten Browser. Wird auch von ``scripts/recheck_expired.py`` genutzt,
    damit beide Stellen identisch laden und nicht auseinanderlaufen.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=not headed,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=_USER_AGENT, locale="de-DE")
        page = ctx.new_page()
        try:
            yield page
        finally:
            ctx.close()
            browser.close()


def load_page_text(page, url: str) -> str:
    """Öffnet ``url`` und liefert den sichtbaren Seitentext.

    Der Scroll ist nötig, weil die Beschreibung teils erst nachgeladen wird,
    wenn sie in den Viewport kommt (Lazy-Content).
    """
    page.goto(url, timeout=45000, wait_until="domcontentloaded")
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(1200)
    page.mouse.wheel(0, 6000)
    page.wait_for_timeout(1200)
    return page.inner_text("body")


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

    with browser_page(headed=headed) as page:
        for i, job in enumerate(targets, 1):
            url = job["url"]
            firma = job.get("firma", "")[:24]
            try:
                text = load_page_text(page, url)
                marker = _is_expired(text)
                if marker:
                    job["verfuegbar"] = False
                    job["verfuegbar_grund"] = marker
                    skipped += 1
                    print(f"[{i}/{len(targets)}] ABGELAUFEN {firma}  („{marker}“)")
                else:
                    desc = _extract_description(text)
                    if desc:
                        job["beschreibung"] = desc
                        job["verfuegbar"] = True
                        job.pop("verfuegbar_grund", None)
                        fetched += 1
                        print(f"[{i}/{len(targets)}] OK   {firma:<24} ({len(desc)} Zeichen)")
                    else:
                        skipped += 1
                        print(f"[{i}/{len(targets)}] LEER {firma}")
            except Exception as exc:
                errors += 1
                print(f"[{i}/{len(targets)}] FEHL {firma}: {type(exc).__name__}")

            # Fortschritt nach jedem Job speichern (resume-fähig).
            jobs_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(1.0)

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
