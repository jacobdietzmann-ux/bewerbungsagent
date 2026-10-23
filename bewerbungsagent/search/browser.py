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
import sys
from pathlib import Path
from typing import Iterator

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
        browser = p.chromium.launch(
            executable_path=_chromium_executable_path(),
            headless=not headed,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
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
