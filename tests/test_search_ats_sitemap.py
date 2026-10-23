"""Tests für den generischen Sitemap-Provider (``search.ats.sitemap_jobboard``).

Der Provider deckt Karriereseiten ab, die weder ein bekanntes ATS noch einen
JSON-Endpunkt haben, aber eine ``sitemap.xml`` mit Anzeigen-URLs ausliefern —
live verifiziert an E.ON (``jobs.eon.com``).

Zwei Eigenschaften sind kritisch und werden hier festgehalten:

1. **Der Ortsfilter greift vor dem Laden der Detailseiten.** Eine Weltfirma hat
   hunderte Anzeigen; ohne Vorfilter würde jede einzeln geladen.
2. **Die Sitemap ist oft unvollständig/veraltet.** E.ON listete 9
   München-Anzeigen, vier davon antworteten mit HTTP 404. Solche Einträge werden
   übersprungen, ohne den Lauf abzubrechen.
"""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.search import ats


def _sitemap(urls: list[str]) -> str:
    eintraege = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{eintraege}'
            '</urlset>')


def _detail(titel: str, *, org: str = "Beispiel GmbH", ort: str = "München",
            beschreibung: str | None = None, typ="JobPosting") -> str:
    posting = {
        "@context": "https://schema.org",
        "@type": typ,
        "title": titel,
        "hiringOrganization": {"@type": "Organization", "name": org},
        "jobLocation": {"@type": "Place", "address": {
            "@type": "PostalAddress", "addressLocality": ort}},
        "description": beschreibung if beschreibung is not None
        else f"<p>Wir suchen dich für {titel}.</p>" + "<p>Aufgaben und Profil.</p>" * 20,
    }
    return ('<html><body><script type="application/ld+json">'
            f'{json.dumps(posting)}</script></body></html>')


class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ats.requests.HTTPError(f"HTTP {self.status_code}")


def _fake_requests(monkeypatch, seiten: dict[str, str | int], aufrufe: list[str] | None = None):
    def fake(url, **kwargs):
        if aufrufe is not None:
            aufrufe.append(url)
        antwort = seiten.get(url)
        if antwort is None:
            return _Resp("", status=404)
        if isinstance(antwort, int):
            return _Resp("", status=antwort)
        return _Resp(antwort)

    monkeypatch.setattr(ats.requests, "get", fake)


# --------------------------------------------------------------------------
# JSON-LD lesen
# --------------------------------------------------------------------------

def test_jobposting_aus_jsonld_wird_erkannt():
    postings = ats._jsonld_job_postings(_detail("Test Engineer (m/w/d)"))
    assert len(postings) == 1
    assert postings[0]["title"] == "Test Engineer (m/w/d)"


def test_mehrere_bloecke_und_nur_jobposting():
    """Breadcrumb/Organisation stehen mit auf der Seite und dürfen nicht stören."""
    html = ('<script type="application/ld+json">{"@type": "BreadcrumbList"}</script>'
            + _detail("Erste Stelle")
            + _detail("Zweite Stelle"))
    titel = [p["title"] for p in ats._jsonld_job_postings(html)]
    assert titel == ["Erste Stelle", "Zweite Stelle"]


def test_type_als_liste_wird_erkannt():
    posting = {"@type": ["JobPosting", "Thing"], "title": "X"}
    html = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
    assert len(ats._jsonld_job_postings(html)) == 1


def test_kaputtes_json_wird_uebersprungen():
    html = ('<script type="application/ld+json">{kaputt</script>'
            + _detail("Gültig"))
    assert len(ats._jsonld_job_postings(html)) == 1


def test_ohne_jsonld_leere_liste():
    assert ats._jsonld_job_postings("<html><body>kein ld</body></html>") == []


@pytest.mark.parametrize("location, erwartet", [
    ({"address": {"addressLocality": "München"}}, "München"),
    ([{"address": {"addressLocality": "Ottobrunn"}}], "Ottobrunn"),
    ({"name": "Garching"}, "Garching"),
    ({"address": {"addressRegion": "Bayern"}}, "Bayern"),
    ({}, ""),
    (None, ""),
])
def test_ort_aus_joblocation(location, erwartet):
    assert ats._jsonld_ort({"jobLocation": location}) == erwartet


# --------------------------------------------------------------------------
# Board einlesen
# --------------------------------------------------------------------------

_SITEMAP_URL = "https://jobs.example.com/sitemap.xml"

_SEITEN = {
    _SITEMAP_URL: _sitemap([
        "https://jobs.example.com/de/job/Test-Engineer-m_w_d-Muenchen/846",
        "https://jobs.example.com/de/job/Werkstudent-Operations-Muenchen/711",
        "https://jobs.example.com/de/job/Business-Officer-Essen/864",
        "https://jobs.example.com/de/job/Technician-Kent/246588",
        "https://jobs.example.com/de/ueber-uns",
    ]),
    "https://jobs.example.com/de/job/Test-Engineer-m_w_d-Muenchen/846":
        _detail("Test Engineer (m/w/d)", org="E.ON Drive Germany GmbH"),
    "https://jobs.example.com/de/job/Werkstudent-Operations-Muenchen/711":
        _detail("Werkstudent Operations (m/w/d)", org="E.ON Energie Deutschland GmbH"),
    "https://jobs.example.com/de/job/Business-Officer-Essen/864":
        _detail("Business Officer (m/f/d)", org="E.ON SE", ort="Essen"),
    "https://jobs.example.com/de/job/Technician-Kent/246588":
        _detail("Shift Technician", org="E.ON UK", ort="Kent"),
}


def test_sitemap_liefert_stellen_mit_firma_ort_und_volltext(monkeypatch):
    _fake_requests(monkeypatch, _SEITEN)
    jobs = ats.sitemap_jobboard(_SITEMAP_URL, "E.ON", url_must_contain="muenchen")
    assert [j["titel"] for j in jobs] == ["Test Engineer (m/w/d)",
                                          "Werkstudent Operations (m/w/d)"]
    erster = jobs[0]
    # Der Arbeitgeber kommt aus dem JSON-LD, nicht aus dem Konfigurationsnamen:
    # unter „E.ON" würden sonst alle Konzerntöchter verschwinden.
    assert erster["firma"] == "E.ON Drive Germany GmbH"
    assert erster["ort"] == "München"
    assert len(erster["beschreibung"]) >= ats._MIN_DESCRIPTION


def test_ortsfilter_greift_vor_dem_laden_der_detailseiten(monkeypatch):
    """Ohne Vorfilter würde eine Weltfirma hunderte Detailseiten laden."""
    aufrufe: list[str] = []
    _fake_requests(monkeypatch, _SEITEN, aufrufe)
    ats.sitemap_jobboard(_SITEMAP_URL, "E.ON", url_must_contain="muenchen")
    details = [u for u in aufrufe if "/job/" in u]
    assert len(details) == 2          # nur die beiden München-Anzeigen
    assert all("muenchen" in u.lower() for u in details)


def test_ohne_filter_werden_alle_jobs_geladen(monkeypatch):
    _fake_requests(monkeypatch, _SEITEN)
    jobs = ats.sitemap_jobboard(_SITEMAP_URL, "E.ON")
    assert len(jobs) == 4
    assert {j["ort"] for j in jobs} == {"München", "Essen", "Kent"}


def test_nicht_job_urls_werden_ignoriert(monkeypatch):
    aufrufe: list[str] = []
    _fake_requests(monkeypatch, _SEITEN, aufrufe)
    ats.sitemap_jobboard(_SITEMAP_URL, "E.ON")
    assert not any("ueber-uns" in u for u in aufrufe)


def test_tote_anzeige_404_bricht_den_lauf_nicht_ab(monkeypatch):
    """Live beobachtet: 4 von 9 Sitemap-Einträgen waren bereits gelöscht."""
    seiten = dict(_SEITEN)
    seiten["https://jobs.example.com/de/job/Werkstudent-Operations-Muenchen/711"] = 404
    _fake_requests(monkeypatch, seiten)
    jobs = ats.sitemap_jobboard(_SITEMAP_URL, "E.ON", url_must_contain="muenchen")
    assert [j["titel"] for j in jobs] == ["Test Engineer (m/w/d)"]


def test_seite_ohne_jsonld_wird_uebersprungen(monkeypatch):
    seiten = dict(_SEITEN)
    seiten["https://jobs.example.com/de/job/Test-Engineer-m_w_d-Muenchen/846"] = \
        "<html><body>nur Hülle, Daten per JS</body></html>"
    _fake_requests(monkeypatch, seiten)
    jobs = ats.sitemap_jobboard(_SITEMAP_URL, "E.ON", url_must_contain="muenchen")
    assert [j["titel"] for j in jobs] == ["Werkstudent Operations (m/w/d)"]


def test_ohne_volltext_laesst_sich_der_fetch_sparen(monkeypatch):
    _fake_requests(monkeypatch, _SEITEN)
    jobs = ats.sitemap_jobboard(_SITEMAP_URL, "E.ON", url_must_contain="muenchen",
                                with_description=False)
    assert jobs and all(j["beschreibung"] == "" for j in jobs)


def test_max_jobs_begrenzt_die_detailseiten(monkeypatch):
    aufrufe: list[str] = []
    _fake_requests(monkeypatch, _SEITEN, aufrufe)
    ats.sitemap_jobboard(_SITEMAP_URL, "E.ON", max_jobs=2)
    assert len([u for u in aufrufe if "/job/" in u]) == 2


def test_leere_sitemap_ergibt_leere_liste(monkeypatch):
    _fake_requests(monkeypatch, {_SITEMAP_URL: _sitemap([])})
    assert ats.sitemap_jobboard(_SITEMAP_URL, "E.ON") == []


def test_sitemap_http_fehler_schlaegt_durch(monkeypatch):
    _fake_requests(monkeypatch, {_SITEMAP_URL: 503})
    with pytest.raises(ats.requests.HTTPError):
        ats.sitemap_jobboard(_SITEMAP_URL, "E.ON")


# --------------------------------------------------------------------------
# Verdrahtung im Board-Dispatch
# --------------------------------------------------------------------------

def test_dispatch_kennt_sitemap(monkeypatch):
    _fake_requests(monkeypatch, _SEITEN)
    boards = [{"firma": "E.ON", "ats": "sitemap", "sitemap": _SITEMAP_URL,
               "url_must_contain": "muenchen"}]
    jobs, errors = ats.search(boards)
    assert [j["titel"] for j in jobs] == ["Test Engineer (m/w/d)",
                                          "Werkstudent Operations (m/w/d)"]
    assert any("2 im Umkreis" in e for e in errors)


def test_dispatch_meldet_fehlende_sitemap():
    jobs, errors = ats.search([{"firma": "E.ON", "ats": "sitemap"}])
    assert jobs == []
    assert any("sitemap fehlt" in e for e in errors)


def test_dispatch_filtert_zu_weite_orte(monkeypatch):
    """Kent/Essen liegen außerhalb München und dürfen nicht im Ergebnis landen."""
    _fake_requests(monkeypatch, _SEITEN)
    boards = [{"firma": "E.ON", "ats": "sitemap", "sitemap": _SITEMAP_URL}]
    jobs, _errors = ats.search(boards, only_near_munich=True)
    assert {j["ort"] for j in jobs} == {"München"}
