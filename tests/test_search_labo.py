"""Tests für den jobs.labo.de-Provider (``search.labo``).

Die HTML-Ausschnitte sind echte Fragmente der Seite (23.10.2026). Drei
Eigenheiten sind hier festgehalten, weil sie beim Parsen sonst still zu falschen
Daten führen:

1. Bei ``itemCompany`` stehen ``data-*``-Attribute **vor** ``class`` — ein Regex
   auf ``class`` direkt nach dem Tag-Namen findet die Firma nicht.
2. Titel enthalten weiche Trennzeichen (``&shy;`` / ``&#173;``), die mitten im
   Wort als Artefakt erscheinen würden.
3. Die Detailseite hat **kein** JSON-LD; der Text steht in
   ``div.jwtpl-jobaded-dataTextField``-Blöcken.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.search import labo

_KARTE = """
<div class="jwtpl-hili-item jwtpl-hili-itemAjaxCount jwtpl-hili-applyTypeExtern"
     data-jwtpl-hili-applyUrl="https://jobs.labo.de/apply/abc">
  <a class="jwtpl-hili-itemLink" href="https://jobs.labo.de/job/testingenieur-m-w-d.123456789.html"
     target="_blank" data-jwtpl-hili-urlinfos="jssi=1">
    <div class="jwtpl-hili-col1"><span class="jwtpl-hili-itemFav" title="merken"></span></div>
    <div class="jwtpl-hili-col2">
      <span class="jwtpl-hili-itemTitel">Test&shy;ingenieur (m&shy;/&shy;w&shy;/&shy;d)</span>
      <span class="jwtpl-hili-itemDate">23.10.2026</span>
      <span data-jwtpl-hili-advProfUrl="" data-jwtpl-hili-advProfId="0"
            class="jwtpl-hili-itemCompany jwtpl-hili-itemCompanyHasProfil0">Beispiel GmbH</span>
      <span class="jwtpl-hili-itemLocation"><span>München</span></span>
    </div>
  </a>
</div>
"""

_LISTE = ("<html><body><div class='jwtpl-hili-list'>" + _KARTE + _KARTE.replace(
    "testingenieur-m-w-d.123456789", "systemtest.987654321").replace(
    "Beispiel GmbH", "Zweite AG")
    + "</div>"
    '<div class="jwtpl-hilipage-block">'
    '<span class="jwtpl-hilipage-pageView">1</span>'
    '<a class="jwtpl-hilipage-nextBt jwtpl-hilipage-nextBtActive1" '
    'href="https://jobs.labo.de/suchergebnis?jmyc=3&amp;jssc=20#gjt1">weiter</a>'
    "</div></body></html>")


def _detail(text: str, titel="Testingenieur (m/w/d)", firma="Beispiel GmbH",
            ort="München") -> str:
    return (
        '<div class="jwtpl-jobaded-block">'
        f'<div class="jwtpl-jobaded-dataMainTitle"><strong>{titel}</strong></div>'
        f'<div class="jwtpl-jobaded-dataMainCompany"><a href="#">{firma}</a></div>'
        f'<div class="jwtpl-jobaded-dataMainLocation">{ort}</div>'
        '<div class="jwtpl-jobaded-dataJobAdTask jwtpl-jobaded-dataTextField">'
        f"<ul><li>{text}</li></ul></div>"
        '<div class="jwtpl-jobaded-dataJobAdProfile jwtpl-jobaded-dataTextField">'
        f"<p>{text}</p></div>"
        "</div>")


# --------------------------------------------------------------------------
# Trefferliste
# --------------------------------------------------------------------------

def test_liste_parst_titel_firma_ort_und_datum():
    eintraege = labo.parse_list(_LISTE)
    assert len(eintraege) == 2
    erster = eintraege[0]
    assert erster["titel"] == "Testingenieur (m/w/d)"
    assert erster["firma"] == "Beispiel GmbH"
    assert erster["ort"] == "München"
    assert erster["datum"] == "23.10.2026"
    assert erster["url"].endswith("testingenieur-m-w-d.123456789.html")
    assert eintraege[1]["firma"] == "Zweite AG"


def test_weiche_trennzeichen_werden_entfernt():
    """``&shy;`` mitten im Wort würde im Dashboard als Artefakt stehen."""
    titel = labo.parse_list(_LISTE)[0]["titel"]
    assert "\u00ad" not in titel
    assert titel == "Testingenieur (m/w/d)"


def test_firma_steht_hinter_data_attributen():
    """Regression: ``class`` steht bei ``itemCompany`` nicht am Tag-Anfang."""
    block = _KARTE
    assert 'data-jwtpl-hili-advProfId="0"\n            class="jwtpl-hili-itemCompany' in block
    assert labo.parse_list(_LISTE)[0]["firma"] == "Beispiel GmbH"


def test_ohne_firma_bleibt_das_feld_leer():
    html = _KARTE.replace('class="jwtpl-hili-itemCompany jwtpl-hili-itemCompanyHasProfil0"', "")
    eintraege = labo.parse_list(html)
    assert len(eintraege) == 1
    assert eintraege[0]["firma"] == ""


def test_kaputte_karte_ohne_link_wird_uebersprungen():
    html = '<div class="jwtpl-hili-item "><span class="jwtpl-hili-itemTitel">X</span></div>'
    assert labo.parse_list(html) == []


def test_relative_urls_werden_absolut():
    html = _KARTE.replace(
        "https://jobs.labo.de/job/testingenieur-m-w-d.123456789.html",
        "/job/testingenieur-m-w-d.123456789.html")
    assert labo.parse_list(html)[0]["url"].startswith("https://jobs.labo.de/job/")


# --------------------------------------------------------------------------
# Paginierung
# --------------------------------------------------------------------------

def test_naechste_seite_kommt_aus_dem_knopf():
    """Die URL enthält eine Sitzungs-ID — sie darf nicht nachgebaut werden."""
    url = labo.next_page(_LISTE)
    assert "jssc=20" in url
    assert url.startswith("https://jobs.labo.de/suchergebnis")


def test_ohne_weiter_knopf_gibt_es_keine_naechste_seite():
    assert labo.next_page("<html><body>Ende</body></html>") == ""


def test_inaktiver_weiter_knopf_ohne_href():
    html = '<a class="jwtpl-hilipage-nextBt jwtpl-hilipage-nextBtActive0" href="">x</a>'
    assert labo.next_page(html) == ""


# --------------------------------------------------------------------------
# Detailseite
# --------------------------------------------------------------------------

def test_beschreibung_kommt_aus_den_textfeldern():
    lang = "Sie testen eingebettete Systeme und dokumentieren Messergebnisse. " * 6
    text = labo.parse_description(_detail(lang))
    assert "eingebettete Systeme" in text
    assert len(text) >= labo._MIN_DESCRIPTION


def test_zu_kurzer_text_gilt_als_keine_beschreibung():
    assert labo.parse_description(_detail("kurz")) == ""


def test_kopf_der_detailseite_wird_gelesen():
    kopf = labo.parse_detail(_detail("x" * 300, titel="Systemtest (m/w/d)",
                                     firma="Andere AG", ort="Ottobrunn"))
    assert kopf == {"titel": "Systemtest (m/w/d)", "firma": "Andere AG",
                    "ort": "Ottobrunn"}


def test_leere_detailseite_ergibt_leere_felder():
    assert labo.parse_detail("<html></html>") == {"titel": "", "firma": "", "ort": ""}


# --------------------------------------------------------------------------
# Suche (ohne Netzwerk)
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise labo.requests.HTTPError(f"HTTP {self.status_code}")


def _fake(monkeypatch, seiten: dict[str, str | int], aufrufe: list[tuple] | None = None):
    """Ersetzt ``Session.get`` und protokolliert ``(url, params)``."""

    def fake_get(self, url, params=None, **kwargs):
        if aufrufe is not None:
            aufrufe.append((url, dict(params or {})))
        for muster, antwort in seiten.items():
            if muster in url:
                if isinstance(antwort, int):
                    return _Resp("", status=antwort)
                return _Resp(antwort)
        return _Resp("", status=404)

    monkeypatch.setattr(labo.requests.Session, "get", fake_get)


def test_suche_liefert_firma_ort_und_volltext(monkeypatch):
    lang = "Sie testen eingebettete Systeme und dokumentieren Messergebnisse. " * 6
    _fake(monkeypatch, {"/suchergebnis": _LISTE, "/job/": _detail(lang)})
    jobs = labo.search("Testingenieur", location="München")
    assert len(jobs) == 2
    assert jobs[0]["firma"] == "Beispiel GmbH"
    assert jobs[0]["quelle"] == "Labo"
    assert len(jobs[0]["beschreibung"]) >= labo._MIN_DESCRIPTION


def test_jeder_begriff_ist_eine_eigene_anfrage(monkeypatch):
    """Das Portal kennt keine Suche über mehrere Begriffe."""
    aufrufe: list[tuple] = []
    _fake(monkeypatch, {"/suchergebnis": _LISTE, "/job/": _detail("x" * 300)},
          aufrufe)
    labo.search(["Testingenieur", "Test Engineer"], location="München",
                with_description=False)
    listen = [p for u, p in aufrufe if u.endswith("/suchergebnis")]
    assert [p.get("jsjr") for p in listen] == ["Testingenieur", "Test Engineer"]
    assert all(p.get("jsjo") == "München" for p in listen)


def test_ohne_ort_wird_kein_ortsparameter_gesetzt(monkeypatch):
    aufrufe: list[tuple] = []
    _fake(monkeypatch, {"/suchergebnis": _LISTE}, aufrufe)
    labo.search("Testingenieur", location="", with_description=False)
    assert "jsjo" not in aufrufe[0][1]


def test_doppelte_treffer_werden_dedupliziert(monkeypatch):
    _fake(monkeypatch, {"/suchergebnis": _LISTE, "/job/": _detail("x" * 300)})
    jobs = labo.search(["Testingenieur", "Testingenieur2"], with_description=False)
    assert len(jobs) == 2          # beide Begriffe liefern dieselben zwei Karten


def test_ohne_volltext_werden_keine_detailseiten_geladen(monkeypatch):
    aufrufe: list[tuple] = []
    _fake(monkeypatch, {"/suchergebnis": _LISTE}, aufrufe)
    jobs = labo.search("Testingenieur", with_description=False)
    assert jobs and all(j["beschreibung"] == "" for j in jobs)
    assert not any("/job/" in u for u, _ in aufrufe)


def test_leere_begriffsliste_ergibt_leere_liste(monkeypatch):
    aufrufe: list[tuple] = []
    _fake(monkeypatch, {"/suchergebnis": _LISTE}, aufrufe)
    assert labo.search([]) == []
    assert aufrufe == []


def test_fehlgeschlagene_liste_bricht_nicht_ab(monkeypatch):
    _fake(monkeypatch, {"/suchergebnis": 500, "/job/": _detail("x" * 300)})
    assert labo.search("Testingenieur") == []
