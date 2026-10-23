# -*- coding: utf-8 -*-
"""Tests für den JobLeads-Provider (``search.ats.jobleads``).

Die Fixtures sind echte Ausschnitte der JobLeads-Suchergebnisseite: die Karten
sind ``div.search-job-card`` mit ``data-testid``-Markern, der Ort steckt im
Slug der Anzeigen-URL, der Volltext kommt als ``JobPosting``-JSON-LD von der
Detailseite (mit ``nonce``-Attribut vor ``type``).
"""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.search import ats


_LIST_HTML = """
<html><body>
<div class="search-job-card mb-16">
  <span data-testid="job-card-date">vor 2 Tagen</span>
  <a data-testid="search-job-card-link"
     href="/de/job/system-test-engineer-m-w-d--munchen--abc123">
     System Test Engineer (m/w/d)
  </a>
  <span data-testid="search-job-card-company-name">PCS Systemtechnik GmbH</span>
  <span data-testid="job-card-chip-salary">EUR 70.000 - 100.000</span>
</div>
<div class="search-job-card mb-16">
  <a data-testid="search-job-card-link"
     href="https://www.jobleads.com/de/job/qa-engineer--garching-bei-munchen--def456">
     QA Engineer (m/w/d)
  </a>
  <span data-testid="search-job-card-company-name">Beispiel GmbH</span>
</div>
<div class="search-job-card mb-16">
  <a data-testid="search-job-card-link"
     href="/de/job/key-account-manager--munchen--ghi789">
     tracetronic GmbH: Key Account Manager VOLVO (m/w/d)
  </a>
  <span data-testid="search-job-card-company-name">tracetronic GmbH</span>
</div>
<div class="search-job-card mb-16">
  <a data-testid="search-job-card-link"
     href="/de/job/irgendwas--manching--jkl012">
     Irgendwas (m/w/d)
  </a>
  <span data-testid="search-job-card-company-name">Weit Weg AG</span>
</div>
</body></html>
"""

_DETAIL_HTML = (
    '<html><body>\n'
    '<script nonce="abc123" type="application/ld+json" id="jobPostingLdjson">\n'
    '{"@type": "JobPosting",\n'
    ' "title": "System Test Engineer (m/w/d)",\n'
    ' "description": "<p>Sie testen eingebettete Systeme und verantworten die '
    'Automatisierung unserer Testumgebung. Sie arbeiten eng mit der Entwicklung '
    'zusammen, erstellen Testpl&auml;ne und bewerten Messergebnisse.</p>'
    '<ul><li>Python</li><li>HiL</li><li>CAN</li></ul>'
    '<p>Wir bieten Ihnen eine unbefristete Stelle, flexible Arbeitszeiten und '
    'ein umfangreiches Weiterbildungsangebot in einem internationalen Umfeld.</p>"}\n'
    '</script>\n'
    '</body></html>\n'
)

# Der Provider verwirft Beschreibungen unter ``_MIN_DESCRIPTION`` Zeichen; das
# Fixture muss also so lang sein wie eine echte Anzeige.
_LD = ats._JOBLEADS_LD_RE.search(_DETAIL_HTML)
assert _LD is not None, "Fixture-JSON-LD nicht gefunden"
assert len(ats._texts(json.loads(_LD.group(1))["description"])) > ats._MIN_DESCRIPTION


class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ats.requests.HTTPError(f"HTTP {self.status_code}")


def _fake_get(monkeypatch, listing=_LIST_HTML, detail=_DETAIL_HTML, calls=None):
    def fake(url, **kwargs):
        if calls is not None:
            calls.append(url)
        # Detailseiten sind die ``/de/job/``-URLs.
        return _Resp(detail if "/de/job/" in url else listing)

    monkeypatch.setattr(ats.requests, "get", fake)


# --------------------------------------------------------------------------
# Orts-Slug
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url, erwartet", [
    ("https://www.jobleads.com/de/job/titel--munchen--hash", "München"),
    ("https://www.jobleads.com/de/job/t--garching-bei-munchen--h",
     "Garching bei München"),
    ("https://www.jobleads.com/de/job/t--furstenfeldbruck--h",
     "Fürstenfeldbruck"),
    ("https://www.jobleads.com/de/job/t--ottobrunn--h", "Ottobrunn"),
    ("https://www.jobleads.com/de/job/ohne-ort", ""),
])
def test_ort_aus_slug(url, erwartet):
    assert ats._jobleads_location(url) == erwartet


def test_urteile_ohne_umlaut_werden_lesbar():
    """JobLeads schreibt ``munchen`` — im Dashboard soll ``München`` stehen."""
    ort = ats._jobleads_location("https://www.jobleads.com/de/job/t--munchen--h")
    assert ort == "München"
    assert "Munchen" not in ort


# --------------------------------------------------------------------------
# URL-Builder
# --------------------------------------------------------------------------

def test_url_builder_kodiert_umlaute_und_setzt_koordinaten():
    url = ats.jobleads_url("Testingenieur", "München")
    assert "M%C3%BCnchen" in url
    assert "location_latitude=48.13" in url
    assert "location_longitude=11.57" in url
    assert "location_coordinates_radius=30000" in url


def test_url_builder_laesst_min_salary_standardmaessig_weg():
    """``minSalary`` filtert nicht hart, also nicht ungefragt mitschicken."""
    assert "minSalary" not in ats.jobleads_url("Testingenieur", "München")
    assert "minSalary=80000" in ats.jobleads_url(
        "Testingenieur", "München", min_salary=80000)


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------

def test_listing_liefert_firma_titel_ort_und_gehalt(monkeypatch):
    _fake_get(monkeypatch)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/M%C3%BCnchen/q/x")

    assert len(jobs) == 3, "Manching liegt nicht im Umkreis"
    pcs = jobs[0]
    assert pcs["titel"] == "System Test Engineer (m/w/d)"
    assert pcs["firma"] == "PCS Systemtechnik GmbH"
    assert pcs["ort"] == "München"
    assert pcs["gehalt"] == "EUR 70.000 - 100.000"
    assert pcs["gehalt_quelle"] == "Anzeige"
    assert pcs["quelle"] == "JobLeads"


def test_firma_kommt_aus_der_anzeige_nicht_aus_dem_provider(monkeypatch):
    """Sonst stehen alle Treffer unter einem Namen und der Filter ist nutzlos."""
    _fake_get(monkeypatch)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y",
                        firma="JobLeads")
    assert [j["firma"] for j in jobs] == [
        "PCS Systemtechnik GmbH", "Beispiel GmbH", "tracetronic GmbH"]


def test_firmenname_wird_nicht_doppelt_in_den_titel_gehaengt(monkeypatch):
    _fake_get(monkeypatch)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y")
    tracetronic = [j for j in jobs if j["firma"] == "tracetronic GmbH"][0]
    assert tracetronic["titel"] == "Key Account Manager VOLVO (m/w/d)"


def test_relativer_href_wird_zu_absoluter_url(monkeypatch):
    _fake_get(monkeypatch)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y")
    assert all(j["url"].startswith("https://www.jobleads.com/de/job/")
               for j in jobs)


def test_ohne_ortsfilter_bleiben_alle_treffer(monkeypatch):
    _fake_get(monkeypatch)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y",
                        only_near_munich=False)
    assert len(jobs) == 4
    assert "Weit Weg AG" in [j["firma"] for j in jobs]


# --------------------------------------------------------------------------
# Volltext
# --------------------------------------------------------------------------

def test_volltext_kommt_aus_dem_json_ld_der_detailseite(monkeypatch):
    """Das ``script``-Tag hat ein ``nonce``-Attribut vor ``type``."""
    _fake_get(monkeypatch)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y")
    assert "eingebettete Systeme" in jobs[0]["beschreibung"]
    assert "Python" in jobs[0]["beschreibung"]
    assert "<li>" not in jobs[0]["beschreibung"], "HTML muss entfernt sein"


def test_detailseite_wird_nur_fuer_treffer_im_umkreis_geladen(monkeypatch):
    """Sonst kostet jede weit entfernte Stelle einen unnötigen Request."""
    calls: list[str] = []
    _fake_get(monkeypatch, calls=calls)
    ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y")

    detail_calls = [u for u in calls if "/de/job/" in u]
    assert len(detail_calls) == 3
    assert not any("manching" in u for u in detail_calls)


def test_kaputte_detailseite_bricht_die_liste_nicht(monkeypatch):
    _fake_get(monkeypatch, detail="<html>kein JSON-LD</html>")
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y")
    assert len(jobs) == 3
    assert all(j["beschreibung"] == "" for j in jobs)


def test_ohne_volltext_werden_keine_detailseiten_geladen(monkeypatch):
    calls: list[str] = []
    _fake_get(monkeypatch, calls=calls)
    ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y",
                 with_description=False)
    assert [u for u in calls if "/de/job/" in u] == []


def test_max_jobs_begrenzt_die_treffer(monkeypatch):
    _fake_get(monkeypatch)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y", max_jobs=2)
    assert len(jobs) == 2


def test_leere_ergebnisseite_ergibt_leere_liste(monkeypatch):
    _fake_get(monkeypatch, listing="<html><body>Keine Treffer</body></html>")
    assert ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y") == []


def test_http_fehler_schlaegt_durch(monkeypatch):
    def fake(url, **kwargs):
        return _Resp("", status=503)

    monkeypatch.setattr(ats.requests, "get", fake)
    with pytest.raises(ats.requests.HTTPError):
        ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y")


# Die gespeicherte SPA-DOM (MHTML) schreibt ein Vue-Scope-Attribut **vor**
# ``class``; ein Parser, der ``<div class="search-job-card`` erwartet, findet
# dort null Karten. Beide Varianten müssen funktionieren.
_SCOPED_LIST_HTML = """
<html><body><div class="search-list-content" role="list">
<div data-v-cb046f9e="" class="search-job-card relative rounded-lg border-2"
     data-testid="search-job-card" role="listitem" aria-posinset="1">
  <a data-v-cb046f9e="" data-testid="search-job-card-link"
     class="absolute inset-0" target="_blank"
     href="https://www.jobleads.com/de/job/system-test-engineer--munchen--e600a3a3">
     System Test Engineer (m/w/d)
  </a>
  <h2 id="v-1-4-58-0-0-title"><span>System Test Engineer (m/w/d)</span></h2>
  <span data-testid="search-job-card-company-name">PCS Systemtechnik GmbH</span>
  <span data-testid="job-card-chip-salary">EUR 70,000 - 100,000</span>
  <span data-testid="job-card-date">6 days ago</span>
</div>
<div data-v-cb046f9e="" class="search-job-card relative rounded-lg border-2"
     data-testid="search-job-card" role="listitem" aria-posinset="2">
  <a data-v-cb046f9e="" data-testid="search-job-card-link"
     class="absolute inset-0" target="_blank"
     href="https://www.jobleads.com/de/job/qa-engineer--garching-bei-munchen--def456">
     QA Engineer (m/w/d)
  </a>
  <h2 id="v-1-4-58-0-1-title"><span>QA Engineer (m/w/d)</span></h2>
  <span data-testid="search-job-card-company-name">Beispiel GmbH</span>
</div>
</div></body></html>
"""


def test_karten_mit_vue_scope_attribut_vor_class_werden_erkannt():
    cards = ats._jobleads_cards(_SCOPED_LIST_HTML)
    assert len(cards) == 2
    assert cards[0].lstrip().startswith("<div")


def test_gespeicherte_dom_liefert_dieselben_felder(monkeypatch):
    _fake_get(monkeypatch, listing=_SCOPED_LIST_HTML)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y",
                        with_description=False)
    assert len(jobs) == 2
    erster = jobs[0]
    assert erster["titel"] == "System Test Engineer (m/w/d)"
    assert erster["firma"] == "PCS Systemtechnik GmbH"
    assert erster["ort"] == "München"
    assert erster["gehalt"] == "EUR 70,000 - 100,000"


def test_kartenmarker_verwechselt_link_nicht_mit_container():
    """``search-job-card-link`` darf nicht als Container gezählt werden."""
    html = '<div data-testid="search-job-card" class="search-job-card">'
    html += '<a data-testid="search-job-card-link" href="/de/job/a--munchen--x">A</a></div>'
    assert len(ats._jobleads_cards(html)) == 1


# --------------------------------------------------------------------------
# Drosselung (HTTP 429)
# --------------------------------------------------------------------------

def test_429_wird_erneut_versucht_und_liefert_den_volltext(monkeypatch):
    """Cloudflare drosselt Bursts kurz; ein Fehlversuch darf den Text nicht kosten."""
    monkeypatch.setattr(ats.time, "sleep", lambda _s: None)
    aufrufe = []

    def fake(url, **kwargs):
        aufrufe.append(url)
        if len(aufrufe) == 1:
            return _Resp("", status=429)
        return _Resp(_DETAIL_HTML)

    monkeypatch.setattr(ats.requests, "get", fake)
    text = ats._jobleads_description(
        "https://www.jobleads.com/de/job/t--munchen--h", None)
    assert "Automatisierung" in text
    assert len(aufrufe) == 2


def test_dauerhaftes_429_endet_nach_den_versuchen(monkeypatch):
    monkeypatch.setattr(ats.time, "sleep", lambda _s: None)
    aufrufe = []

    def fake(url, **kwargs):
        aufrufe.append(url)
        return _Resp("", status=429)

    monkeypatch.setattr(ats.requests, "get", fake)
    assert ats._jobleads_description(
        "https://www.jobleads.com/de/job/t--munchen--h", None) == ""
    assert len(aufrufe) == ats._JOBLEADS_RETRIES


def test_drosselung_bremst_die_liste_nicht_aus(monkeypatch):
    """Ein 429 auf der Detailseite darf den ganzen Suchlauf nicht abbrechen."""
    monkeypatch.setattr(ats.time, "sleep", lambda _s: None)
    zustand = {"detail": 0}

    def fake(url, **kwargs):
        if "/de/job/" in url:
            zustand["detail"] += 1
            # Jede zweite Detailseite drosselt einmal.
            if zustand["detail"] % 2 == 1:
                return _Resp("", status=429)
            return _Resp(_DETAIL_HTML)
        return _Resp(_LIST_HTML)

    monkeypatch.setattr(ats.requests, "get", fake)
    jobs = ats.jobleads("https://www.jobleads.com/de/jobs/l/x/q/y")
    assert len(jobs) == 3
    assert all(len(j["beschreibung"]) >= 200 for j in jobs)


