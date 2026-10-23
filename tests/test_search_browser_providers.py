"""Tests für die Browser-Provider XING und Indeed (``search.xing``/``search.indeed``).

Ein echter Browser läuft in der CI nicht. Geprüft wird deshalb, was ohne
Chromium prüfbar ist und beim Parsen real kaputtging:

- **XING**: Firma und Ort werden relativ zum Titel gelesen. Eine Suche nach der
  „ersten Zeile in Title-Case" greift das Badge „Urgently hiring" ab — im
  Live-Test landete „Dringend gesucht" als Ort im Datensatz.
- **Indeed**: Der Anzeigentext kommt über den **Klick** auf den Titel
  (Master-Detail). Direkte ``/viewjob?jk=…``-Aufrufe enden im Cloudflare-Check
  oder in „Sign In" (im Test 0 von 3 Stellen), der Klick liefert 3 von 3.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.search import browser, indeed, xing


# --------------------------------------------------------------------------
# Gemeinsamer Browser-Helfer
# --------------------------------------------------------------------------

def test_browser_available_meldet_bool():
    assert isinstance(browser.available(), bool)


def test_user_agent_ist_gesetzt():
    assert "Mozilla" in browser.USER_AGENT


def test_consent_ohne_banner_ist_kein_fehler():
    class _Leer:
        def count(self):
            return 0

    class _Page:
        def get_by_role(self, *_a, **_k):
            return _Leer()

    assert browser.dismiss_consent(_Page(), ("Akzeptieren",)) is False


# --------------------------------------------------------------------------
# XING
# --------------------------------------------------------------------------

def test_xing_url_kodiert_begriff_und_ort():
    url = xing.search_url("Testingenieur", "München")
    assert url.startswith("https://www.xing.com/jobs/search?")
    assert "keywords=Testingenieur" in url
    assert "location=M%C3%BCnchen" in url


def test_xing_url_ohne_ort():
    assert "location=" not in xing.search_url("Testingenieur", "")


def test_xing_liest_firma_und_ort_relativ_zum_titel():
    """Firma/Ort werden am Titeltext verankert, nicht am Badge.

    Im Live-Test stand „Urgently hiring" als erste Zeile; eine Suche nach der
    ersten Zeile in Title-Case machte daraus „Dringend gesucht" als Ort.
    """
    gesamt = {}

    class _FakePage:
        def evaluate(self, script):
            gesamt["script"] = script
            return []

    xing._karten(_FakePage())
    script = gesamt["script"]
    assert "findIndex(z => z === titel)" in script
    assert "zeilen[i + 1]" in script      # Firma
    assert "zeilen[i + 2]" in script      # Ort


def test_xing_job_setzt_quelle_und_volltext():
    job = xing._job({"titel": "Testingenieur", "firma": "Acme", "ort": "München",
                     "url": "https://x.test/1", "beschreibung": "x" * 500})
    assert job["quelle"] == "XING"
    assert job["beschreibung"] == "x" * 500
    assert job["snippet"].startswith("x")


def test_xing_ohne_beschreibung_bleibt_leer():
    job = xing._job({"titel": "T", "firma": "F", "ort": "O", "url": "u"})
    assert job["beschreibung"] == ""


def test_xing_leere_begriffsliste_ohne_browserstart():
    """Ohne Begriffe darf kein Browser geöffnet werden."""
    assert xing.search([]) == []
    assert xing.search("") == []


def test_xing_zeigt_an_dass_playwright_fehlt(monkeypatch):
    """Fehlt Playwright, startet der Provider nicht (wird im Dispatch gemeldet)."""
    monkeypatch.setattr(browser, "available", lambda: False)
    assert xing.available() is False


# --------------------------------------------------------------------------
# Indeed
# --------------------------------------------------------------------------

def test_indeed_url_kodiert_begriff_und_ort():
    url = indeed.search_url("Testingenieur", "München")
    assert url.startswith("https://de.indeed.com/jobs?")
    assert "q=Testingenieur" in url
    assert "l=M%C3%BCnchen" in url


def test_indeed_leere_begriffsliste_ohne_browserstart():
    assert indeed.search([]) == []


def test_indeed_liest_karten_ueber_data_jk():
    gesamt = {}

    class _FakePage:
        def evaluate(self, script):
            gesamt["script"] = script
            return []

    indeed._karten(_FakePage())
    script = gesamt["script"]
    assert 'div.job_seen_beacon' in script
    assert "h3.jobTitle a[data-jk]" in script
    assert "company-name" in script
    assert "text-location" in script


def test_indeed_plz_wird_aus_dem_ort_entfernt():
    assert indeed._PLZ_RE.sub("", "80939 München").strip() == "München"
    assert indeed._PLZ_RE.sub("", "München").strip() == "München"


def test_indeed_ort_mit_hybrid_hinweis():
    """``Hybrides Arbeiten in 80634 München`` bleibt erkennbar als München."""
    from bewerbungsagent.commute import is_near_munich
    ort = indeed._PLZ_RE.sub("", "Hybrides Arbeiten in 80634 München").strip()
    assert is_near_munich(ort)


def test_indeed_job_setzt_quelle_und_volltext():
    job = indeed._job({"titel": "Testingenieur", "firma": "Acme", "ort": "München",
                       "url": "https://i.test/1", "beschreibung": "y" * 500})
    assert job["quelle"] == "Indeed"
    assert job["beschreibung"] == "y" * 500


def test_indeed_beschreibung_nutzt_den_klick_nicht_die_detail_url():
    """Regression: ``/viewjob?jk=…`` direkt endet in Cloudflare/„Sign In"."""
    import inspect

    quelle = inspect.getsource(indeed)
    assert "def _beschreibung_per_klick" in quelle
    # Es darf keine Funktion mehr geben, die die Detailseite direkt öffnet.
    assert "def _beschreibung(" not in quelle
    assert "_beschreibung(page," not in quelle


def test_indeed_beschreibung_klickt_die_karte_an():
    import inspect
    quelle = inspect.getsource(indeed._beschreibung_per_klick)
    assert "h3.jobTitle a" in quelle
    assert "simple-job-description-html" in quelle
