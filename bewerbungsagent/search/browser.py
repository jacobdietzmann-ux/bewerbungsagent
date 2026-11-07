"""Gemeinsamer Headless-Browser für Provider, die JavaScript brauchen.

Zwei Portale liefern ihre Treffer nur nach dem Rendern im Browser:

- **XING** antwortet mit HTTP 200, aber das HTML enthält **keine** Anzeige
  (reine JS-Hülle); es gibt weder RSS noch eine offene JSON-API, und die
  GraphQL-Introspection ist in Produktion gesperrt. Mit echtem Browser kommen
  89 Treffer für „Test Engineer" in München (20 je Klick auf „Show more").
- **Indeed** beantwortet einfache HTTP-Anfragen mit Cloudflare-HTTP 403
  („Security Check") — auch die alte RSS-Schnittstelle und ``python-jobspy``.
  Im Browser lädt die Trefferliste normal, und die Detailseite liefert den
  Volltext in ``div.simple-job-description-html``.

Ein Browserstart kostet rund eine Sekunde. Deshalb bekommen die Provider eine
**Liste** von Suchbegriffen und arbeiten sie in einer Sitzung ab, statt je
Begriff einen Browser zu öffnen.

Der Helfer liegt hier und nicht in ``fetch_descriptions.py`` (Wurzel-Skript),
damit das Paket nicht vom Skript abhängt.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

# Derselbe User-Agent wie in ``fetch_descriptions`` — die Portale behandeln
# unbekannte Agents strenger.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _chromium_executable_path() -> Path | None:
    """System-Chromium unter Linux bevorzugen (kein Download nötig)."""
    system = Path("/usr/bin/chromium")
    if sys.platform.startswith("linux") and system.is_file():
        return system
    return None


_INSTALL_LOCK = threading.Lock()
_install_versucht = False
_INSTALL_TIMEOUT_S = 900


def _browser_fehlt(exc: BaseException) -> bool:
    """Erkennt „Chromium-Binärdatei passt nicht zur Playwright-Version"."""
    text = str(exc)
    return "Executable doesn't exist" in text or "playwright install" in text


def install_chromium() -> bool:
    """Lädt das zur installierten Playwright-Version passende Chromium.

    Passiert, wenn das Python-Paket ``playwright`` aktualisiert wurde, die
    Browser-Binärdateien aber noch von der alten Version stammen (Fehler
    ``Executable doesn't exist``). Läuft höchstens **einmal pro Prozess**,
    damit ein dauerhaft fehlschlagender Download den Lauf nicht blockiert.
    Mit ``BEWERBUNGSAGENT_NO_AUTOINSTALL=1`` abschaltbar.
    """
    global _install_versucht
    if os.environ.get("BEWERBUNGSAGENT_NO_AUTOINSTALL", "").strip() in ("1", "true"):
        return False
    with _INSTALL_LOCK:
        if _install_versucht:
            return False
        _install_versucht = True
        print("  Playwright-Browser fehlt oder ist veraltet -> "
              "installiere Chromium (einmalig) ...", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  Chromium-Installation fehlgeschlagen: {exc}", flush=True)
            return False
        if result.returncode != 0:
            print("  Chromium-Installation fehlgeschlagen: "
                  f"{(result.stderr or result.stdout).strip()[-300:]}", flush=True)
            return False
        return True


def _launch(p, headed: bool):
    """Startet Chromium; repariert einen fehlenden Browser einmal selbst."""
    def start():
        return p.chromium.launch(
            executable_path=_chromium_executable_path(),
            headless=not headed,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
    try:
        return start()
    except Exception as exc:
        if not _browser_fehlt(exc) or not install_chromium():
            raise
        return start()


def available() -> bool:
    """True, wenn Playwright samt Chromium nutzbar ist."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return True


@contextlib.contextmanager
def browser_page(*, headed: bool = False) -> Iterator:
    """Headless-Chromium mit deutschem Kontext.

    ``--disable-blink-features=AutomationControlled`` ist nötig: ohne das Flag
    erkennt Indeed den Automationsmodus und liefert die Captcha-Seite statt der
    Trefferliste.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p, headed)
        context = browser.new_context(user_agent=USER_AGENT, locale="de-DE")
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


def dismiss_consent(page, labels: tuple[str, ...]) -> bool:
    """Klickt den Cookie-Hinweis weg, falls er die Seite blockiert.

    Indeed und XING blenden beim ersten Besuch ein Consent-Banner ein, das die
    Klicks abfängt. Die Beschriftungen unterscheiden sich je nach Sprache; ein
    fehlendes Banner ist kein Fehler.
    """
    for label in labels:
        try:
            knopf = page.get_by_role("button", name=label, exact=False)
            if knopf.count():
                knopf.first.click(timeout=4000)
                page.wait_for_timeout(1200)
                return True
        except Exception:
            continue
    return False
