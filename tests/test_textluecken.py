"""Stellen ohne Anzeigentext dürfen nicht still verschwinden (ADR-055).

Am 07.11.2026 waren 53 ausgeblendete Rollentreffer betroffen. Zwei Ursachen:
``fetch`` kennt nur den letzten Suchlauf, und Mail-Leads haben keine URL.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import bewerbungsagent.search as suche
from bewerbungsagent import auswahl, pipeline
from bewerbungsagent.config import Config
from bewerbungsagent.db import USER_DELETE_REASON
from bewerbungsagent.pipeline import _job_key, _merge_state, _textluecken
from bewerbungsagent.search import manual
from fetch_descriptions import _is_expired, _is_expired_redirect


def _vor(tage: int) -> str:
    return (datetime.now().astimezone() - timedelta(days=tage)).isoformat(timespec="seconds")


def _lead(firma="HENSOLDT", titel="Testingenieur (m/w/d)", **mehr) -> dict:
    return {"firma": firma, "titel": titel, "ort": "", "url": "", "beschreibung": "",
            "quelle": manual.MAIL_LEAD, "herkunft": "JobLeads", "gefunden": "2026-11-05", **mehr}


def _bestand(key="https://example.test/1", **mehr) -> dict:
    return {"key": key, "url": key, "firma": "Beispiel GmbH", "titel": "Testingenieur (m/w/d)",
            "quelle": "StepStone", "status": "neu", "score": 10, "created": _vor(3),
            "deleted": True, "deleted_reason": "FIT < 50 %", **mehr}


@pytest.fixture
def config(tmp_path: Path, tmp_config: dict) -> Config:
    tmp_config["search"]["enabled"] = True
    (tmp_path / "data").mkdir(exist_ok=True)
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(pfad)


class TestFirmaPasst:
    @pytest.mark.parametrize("a, b", [
        ("Bertrandt Group", "Bertrandt AG"),
        ("Agile Robots SE", "Agilerobotsse"),
        ("Rohde & Schwarz GmbH & Co.", "Rohde & Schwarz GmbH & Co. KG"),
        ("indie Semiconductor FFO GmbH", "indie.inc"),
        ("SOFTWARE ENGINEERING GmbH", "Software Engineering GmbH"),
    ])
    def test_gleiche_firma(self, a, b):
        assert manual.firma_passt(a, b)

    @pytest.mark.parametrize("a, b", [
        ("MAN", "Mannheim GmbH"),          # zu kurz für den Anfangsvergleich
        ("Seg Muc", "SEG Automotive"),
        ("Expleo", "Akkodis"),
        ("", "Akkodis"),
    ])
    def test_andere_firma(self, a, b):
        assert not manual.firma_passt(a, b)


class TestTitelPasst:
    @pytest.mark.parametrize("a, b", [
        ("Software Tester (m/w/d)", "Software Tester (w/m/d)"),
        ("Testingenieur (all genders)", "Testingenieur m/w/d"),
        ("RF IC Design Validation and Test Engineer",
         "Senior RF IC Design Validation and Test Engineer"),
    ])
    def test_gleicher_titel(self, a, b):
        assert manual.titel_passt(a, b)

    @pytest.mark.parametrize("a, b", [
        # Echte Fehlzuordnungen aus der Messung vom 07.11.2026.
        ("Mechatronics and Hardware Test Engineer (m/f/d)", "Mechatronics Test Engineer (m/f/d)"),
        ("Senior Software Quality Engineer (w/m/d)", "Senior Software Engineer / Architect"),
    ])
    def test_aehnlich_reicht_nicht(self, a, b):
        assert not manual.titel_passt(a, b)

    def test_gekuerzter_titel_vergleicht_den_anfang(self):
        lang = "Testingenieur Verifikation, Validierung und Integration (m/w/d)"
        assert manual.titel_passt("Testingenieur Verifikation, Validierung un...", lang)
        assert not manual.titel_passt("Testingenieur Elektronik, Validierung un...", lang)

    def test_ein_gekuerztes_einzelwort_reicht_nicht(self):
        assert not manual.titel_passt("Testingenieur Veri...", "Testingenieur (m/w/d)")


class TestLeadsVerknuepfen:
    def test_url_und_ort_landen_im_import(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        pfad.write_text(json.dumps([_lead()]), encoding="utf-8")
        anzeige = {"firma": "Hensoldt Sensors GmbH", "titel": "Testingenieur (m/w/x)",
                   "url": "https://www.xing.com/jobs/1", "ort": "Taufkirchen", "quelle": "XING"}
        assert manual.leads_verknuepfen(pfad, [anzeige], date(2026, 11, 7)) == 1
        eintrag = json.loads(pfad.read_text(encoding="utf-8"))[0]
        assert eintrag["url"] == "https://www.xing.com/jobs/1"
        assert eintrag["ort"] == "Taufkirchen"
        assert eintrag["url_quelle"] == "XING"
        assert eintrag["url_gesucht"] == "2026-11-07"

    def test_ohne_treffer_wird_nur_die_suche_vermerkt(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        pfad.write_text(json.dumps([_lead()]), encoding="utf-8")
        assert manual.leads_verknuepfen(pfad, [], date(2026, 11, 7)) == 0
        eintrag = json.loads(pfad.read_text(encoding="utf-8"))[0]
        assert eintrag["url"] == ""
        assert eintrag["url_gesucht"] == "2026-11-07"

    def test_handgepflegte_eintraege_bleiben_unveraendert(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        hand = {"firma": "HENSOLDT", "titel": "Testingenieur (m/w/d)", "quelle": "Import"}
        pfad.write_text(json.dumps([hand, _lead()]), encoding="utf-8")
        manual.leads_verknuepfen(pfad, [], date(2026, 11, 7))
        assert json.loads(pfad.read_text(encoding="utf-8"))[0] == hand

    def test_frisch_gesuchte_leads_bleiben_aussen_vor(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        pfad.write_text(json.dumps([_lead(url_gesucht="2026-11-05"),
                                    _lead(firma="Expleo", url_gesucht="2026-10-30"),
                                    _lead(firma="Akkodis", url="https://x.test/1")]),
                        encoding="utf-8")
        offen = manual.offene_leads(pfad, date(2026, 11, 7))
        assert [j["firma"] for j in offen] == ["Expleo"]

    def test_suchbegriff_ohne_klammern_und_kuerzung(self):
        assert manual.suchbegriff(_lead(titel="Testingenieur (m/w/d) Verifikation...")) \
            == "HENSOLDT Testingenieur Verifikation"


class TestLeadBehaeltSeinenBestandseintrag:
    """Eine gefundene URL füllt den Lead, statt einen zweiten Eintrag anzulegen."""

    def test_manual_nennt_den_bestandsschluessel(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        pfad.write_text(json.dumps([_lead(url="https://www.xing.com/jobs/1"), _lead(firma="B")]),
                        encoding="utf-8")
        mit_url, ohne_url = manual.search(pfad)
        assert mit_url["bestand_key"] == "hensoldt|testingenieur (m/w/d)"
        assert "bestand_key" not in ohne_url

    def test_key_bleibt_und_text_kommt_an(self):
        lead = {"key": "hensoldt|testingenieur (m/w/d)", "firma": "HENSOLDT",
                "titel": "Testingenieur (m/w/d)", "quelle": manual.MAIL_LEAD, "url": "", "ort": "",
                "status": "neu", "score": 8}
        job = {"bestand_key": lead["key"], "firma": "HENSOLDT", "titel": lead["titel"],
               "url": "https://www.xing.com/jobs/1", "ort": "Taufkirchen", "score": 74,
               "beschreibung": "Echter Anzeigentext"}
        job["key"] = _job_key(job)
        assert job["key"] == lead["key"]
        ergebnis = _merge_state({"applications": [lead]}, [job])["applications"]
        assert len(ergebnis) == 1
        assert ergebnis[0]["url"] == "https://www.xing.com/jobs/1"
        assert ergebnis[0]["ort"] == "Taufkirchen"
        assert ergebnis[0]["beschreibung"] == "Echter Anzeigentext"
        assert ergebnis[0]["score"] == 74

    def test_vorhandene_url_wird_nicht_ueberschrieben(self):
        alt = {"key": "k", "url": "https://alt.test/1", "ort": "München", "status": "neu"}
        neu = {"key": "k", "url": "https://neu.test/2", "ort": "Berlin", "score": 10}
        ergebnis = _merge_state({"applications": [alt]}, [neu])["applications"][0]
        assert ergebnis["url"] == "https://alt.test/1"
        assert ergebnis["ort"] == "München"


class TestResolveMailLeads:
    def _import(self, config: Config, *leads) -> Path:
        pfad = config.import_path()
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(json.dumps(list(leads)), encoding="utf-8")
        return pfad

    def _xing(self, monkeypatch, ergebnis):
        aufrufe = []

        def suchen(terms, **kw):
            aufrufe.append((terms, kw))
            if isinstance(ergebnis, Exception):
                raise ergebnis
            return ergebnis

        monkeypatch.setattr(suche.xing, "available", lambda: True)
        monkeypatch.setattr(suche.xing, "search", suchen)
        return aufrufe

    def test_alle_begriffe_laufen_in_einer_sitzung_ohne_texte(self, config, monkeypatch):
        self._import(config, _lead(), _lead(firma="Expleo"))
        aufrufe = self._xing(monkeypatch, [])
        ergebnis = suche.resolve_mail_leads(config)
        assert ergebnis == {"gesucht": 2, "gefunden": 0, "fehler": []}
        assert len(aufrufe) == 1
        assert aufrufe[0][0] == ["HENSOLDT Testingenieur", "Expleo Testingenieur"]
        assert aufrufe[0][1]["with_description"] is False

    def test_fehlschlag_laesst_den_lead_offen(self, config, monkeypatch):
        pfad = self._import(config, _lead())
        self._xing(monkeypatch, RuntimeError("HTTP 429"))
        ergebnis = suche.resolve_mail_leads(config)
        assert ergebnis["gesucht"] == 0
        assert ergebnis["fehler"] == ["xing: HTTP 429"]
        assert "url_gesucht" not in json.loads(pfad.read_text(encoding="utf-8"))[0]

    def test_deaktivierter_provider_wird_nicht_gefragt(self, config, monkeypatch):
        self._import(config, _lead())
        aufrufe = self._xing(monkeypatch, [])
        suche.resolve_mail_leads(config, {"xing": {"deaktiviert": True}})
        assert aufrufe == []

    def test_leere_providerliste_schaltet_die_suche_ab(self, config, monkeypatch):
        self._import(config, _lead())
        config.data["search"]["lead_url_provider"] = []
        aufrufe = self._xing(monkeypatch, [])
        assert suche.resolve_mail_leads(config)["gesucht"] == 0
        assert aufrufe == []


class TestRunSearchVerwirftBekannteLeads:
    def test_aehnlich_geschriebene_anzeige_verdraengt_den_lead(self, tmp_path, tmp_config):
        (tmp_path / "data").mkdir(exist_ok=True)
        pfad = tmp_path / "config.json"
        pfad.write_text(json.dumps(tmp_config), encoding="utf-8")
        konfig = Config(pfad)
        konfig.import_path().write_text(json.dumps([
            _lead(firma="Bertrandt Group", titel="Softwaretester (m/w/d)"),
            {"firma": "Bertrandt AG", "titel": "Softwaretester (m/w/x)", "quelle": "Import",
             "url": "https://example.test/1", "beschreibung": "Text"},
        ]), encoding="utf-8")
        jobs, _fehler, _n = suche.run_search(konfig, None)
        assert [j["quelle"] for j in jobs] == ["Import"]


class TestTextluecken:
    def _luecken(self, *apps, jobs=()):
        return _textluecken({"applications": list(apps)}, list(jobs))

    def test_ausgeblendeter_rollentreffer_laeuft_wieder_mit(self):
        luecken = self._luecken(_bestand())
        assert [j["url"] for j in luecken] == ["https://example.test/1"]
        assert luecken[0]["quelle"] == "StepStone"
        assert _job_key(luecken[0]) == "https://example.test/1"

    def test_stelle_aus_dem_suchlauf_kommt_nicht_doppelt(self):
        assert self._luecken(_bestand(), jobs=[{"url": "https://example.test/1"}]) == []

    @pytest.mark.parametrize("mehr", [
        {"beschreibung": "Vorhandener Text"},
        {"verfuegbar": False},
        {"url": ""},
        {"titel": "Vertriebsleiter (m/w/d)"},                 # kein Rollensignal
        {"titel": "Werkstudent Testing (m/w/d)"},
        {"titel": "System Engineer Cloud & Integration"},     # Software-Deckel
        {"status": "rejected"},                               # eingefroren (ADR-039)
        {"deleted_reason": USER_DELETE_REASON},
        {"created": _vor(auswahl.TEXT_NACHLADEN_TAGE + 1)},
        {"created": None},
    ])
    def test_kein_nachladen(self, mehr):
        assert self._luecken(_bestand(**mehr)) == []

    def test_lauf_haengt_die_luecken_an_und_zaehlt_sie_getrennt(self, config, monkeypatch):
        class Lager:
            def get_meta(self, *_a):
                return {}

            def set_meta(self, *_a):
                return None

            def load_state(self):
                return {"applications": [_bestand()]}

        monkeypatch.setattr(pipeline, "_store", lambda _c: Lager())
        monkeypatch.setattr(pipeline, "_tageslauf_definitionen", lambda _c: [("Standard", None)])
        monkeypatch.setattr(pipeline, "_search", lambda *_a, **_k: ([], [], 0))
        monkeypatch.setattr(pipeline, "resolve_mail_leads",
                            lambda *_a: {"gesucht": 0, "gefunden": 0, "fehler": []})
        monkeypatch.setattr(pipeline, "_enrich_job_context", lambda *_a: {})
        ergebnis = pipeline.run_searches(config, None)
        assert ergebnis["count"] == 0
        assert ergebnis["textluecken"] == 1
        geschrieben = json.loads(config.jobs_path().read_text(encoding="utf-8"))
        assert [j["url"] for j in geschrieben] == ["https://example.test/1"]


class TestAblaufErkennung:
    def test_entfernte_arbeitnow_anzeige(self):
        assert _is_expired("Jobs in Germany\nThis job posting has been removed\n\nIt may")

    def test_linkedin_weiterleitung_auf_eine_trefferliste(self):
        url = ("https://de.linkedin.com/jobs/softwaretester-stellen"
               "?trk=expired_jd_redirect&position=1")
        assert _is_expired_redirect(url) == "trk=expired_jd_redirect"

    @pytest.mark.parametrize("url", ["https://www.linkedin.com/jobs/view/4456943036", "", None])
    def test_normale_adresse_ist_nicht_abgelaufen(self, url):
        assert _is_expired_redirect(url) is None


class TestPrueffallTextFehlt:
    """Regel aus ADR-055, vom Nutzer am 08.11.2026 mit 14 Tagen Frist freigegeben."""

    @pytest.fixture(autouse=True)
    def _offline(self, monkeypatch):
        monkeypatch.setattr(pipeline, "enrich_commute", lambda apps, *_a, **_k: {"total": len(apps)})
        monkeypatch.setattr(pipeline, "enrich_salary", lambda apps: {})
        monkeypatch.setattr(pipeline, "_generate_one", lambda *_a, **_k: [])

    def _lauf(self, config, *apps):
        from bewerbungsagent.db import Store
        Store(config.db_path()).save_state({"applications": list(apps)})
        ergebnis = pipeline.run_enrich(config, None)
        stand = {a["key"]: a for a in Store(config.db_path()).load_state()["applications"]}
        return ergebnis, stand

    def _stelle(self, key="k1", **mehr):
        return {"key": key, "url": f"https://example.test/{key}", "firma": "Beispiel GmbH",
                "titel": "Testingenieur HiL (m/w/d)", "quelle": "StepStone", "status": "neu",
                "score": 12, "created": _vor(3), "pendelzeit_min": 20, **mehr}

    def test_rollentreffer_ohne_text_bleibt_als_prueffall(self, config):
        ergebnis, stand = self._lauf(config, self._stelle())
        assert not stand["k1"].get("deleted")
        assert stand["k1"]["text_fehlt"] is True
        assert ergebnis["text_fehlt"] == 1
        assert ergebnis["deleted_fit_under_50"] == 0

    def test_frueher_ausgeblendet_kommt_als_prueffall_zurueck(self, config):
        _e, stand = self._lauf(config, self._stelle(deleted=True, deleted_reason="FIT < 50 %"))
        assert not stand["k1"].get("deleted")
        assert stand["k1"]["text_fehlt"] is True

    def test_nach_der_frist_ausgeblendet_mit_eigenem_grund(self, config):
        _e, stand = self._lauf(config, self._stelle(created=_vor(auswahl.TEXT_FEHLT_TAGE + 1)))
        assert stand["k1"]["deleted"] is True
        assert stand["k1"]["deleted_reason"] == "Text fehlt seit über 14 Tagen"
        assert "text_fehlt" not in stand["k1"]

    def test_abgelaufene_anzeige_nennt_den_grund(self, config):
        _e, stand = self._lauf(config, self._stelle(verfuegbar=False))
        assert stand["k1"]["deleted_reason"] == "Anzeige abgelaufen (ohne Text)"

    @pytest.mark.parametrize("mehr", [
        {"beschreibung": "Echter Anzeigentext"},     # bewertet, nicht mehr nur der Titel
        {"titel": "Vertriebsleiter (m/w/d)"},       # kein Rollensignal
    ])
    def test_sonst_gilt_die_ausblendgrenze(self, config, mehr):
        _e, stand = self._lauf(config, self._stelle(**mehr))
        assert stand["k1"]["deleted_reason"] == "FIT < 50 %"

    def test_pendelweg_bleibt_harte_grenze(self, config):
        _e, stand = self._lauf(config, self._stelle(pendelzeit_min=120))
        assert stand["k1"]["deleted"] is True
        assert stand["k1"]["deleted_reason"].startswith("Pendelweg")

    @pytest.mark.parametrize("mehr", [
        {"beschreibung": "Echter Anzeigentext"},     # Fit ist bewertet, nicht nur der Titel
        {"titel": "Psychologe (m/w/d)"},            # kein Rollensignal
    ])
    def test_pendel_wieder_frei_aber_fit_zu_schwach(self, config, mehr):
        alt = self._stelle(deleted=True, deleted_reason="Pendelweg > 30 min",
                           deleted_code="pendel", **mehr)
        _e, stand = self._lauf(config, alt)
        assert stand["k1"]["deleted"] is True
        assert stand["k1"]["deleted_reason"] == "FIT < 50 %"
        assert "text_fehlt" not in stand["k1"]

    def test_pendel_wieder_frei_rollentreffer_ohne_text_wird_prueffall(self, config):
        alt = self._stelle(deleted=True, deleted_reason="Pendelweg > 30 min", deleted_code="pendel")
        _e, stand = self._lauf(config, alt)
        assert not stand["k1"].get("deleted")
        assert stand["k1"]["text_fehlt"] is True

    def test_research_filter_laesst_den_prueffall_stehen(self, config):
        _e, stand = self._lauf(config, self._stelle(status="research"))
        assert not stand["k1"].get("deleted")

    def test_mit_text_entscheiden_wieder_die_baender(self, config):
        _e, stand = self._lauf(config, self._stelle(beschreibung="Text", score=67))
        assert not stand["k1"].get("deleted")
        assert "text_fehlt" not in stand["k1"]

    def test_mail_lead_neben_seiner_anzeige_wird_dublette(self, config):
        lead = {"key": "hensoldt|testingenieur (m/w/d)", "firma": "HENSOLDT",
                "titel": "Testingenieur (m/w/d)", "quelle": manual.MAIL_LEAD, "status": "neu",
                "score": 8, "created": _vor(1)}
        anzeige = self._stelle("k2", firma="Hensoldt Sensors GmbH", titel="Testingenieur (m/w/x)",
                               beschreibung="Text", score=58)
        ergebnis, stand = self._lauf(config, lead, anzeige)
        assert ergebnis["lead_dubletten"] == 1
        assert stand[lead["key"]]["deleted_reason"] == \
            "Dublette: dieselbe Stelle wie Hensoldt Sensors GmbH (StepStone)"

    def test_vom_nutzer_geloeschter_lead_bleibt_unberuehrt(self, config):
        lead = {"key": "x|testingenieur", "firma": "X GmbH", "titel": "Testingenieur",
                "quelle": manual.MAIL_LEAD, "status": "neu", "created": _vor(1),
                "deleted": True, "deleted_reason": USER_DELETE_REASON}
        anzeige = self._stelle("k2", firma="X GmbH", titel="Testingenieur", beschreibung="Text")
        _e, stand = self._lauf(config, lead, anzeige)
        assert stand[lead["key"]]["deleted_reason"] == USER_DELETE_REASON

    def test_messgroesse_zaehlt_die_umbenennung_weiter_mit(self):
        apps = [
            {"deleted": True, "deleted_reason": "FIT < 50 %", "titel": "Testingenieur"},
            {"deleted": True, "deleted_reason": "Text fehlt seit über 14 Tagen",
             "titel": "Testingenieur"},
            {"deleted": True, "deleted_reason": "FIT < 50 %", "titel": "Testingenieur",
             "beschreibung": "Text"},                                   # bewertet
            {"deleted": True, "deleted_reason": "Anzeige abgelaufen (ohne Text)",
             "titel": "Testingenieur", "verfuegbar": False},
            {"deleted": True, "deleted_reason": "FIT < 50 %", "titel": "Vertrieb"},
            {"text_fehlt": True, "titel": "Testingenieur"},             # sichtbar
        ]
        assert auswahl.stille_rollentreffer(apps) == 2


class TestDashboardPrueffall:
    def test_prueffall_steht_in_eigener_liste_nicht_in_der_tabelle(self, tmp_path, monkeypatch):
        import re

        from bewerbungsagent import dashboard
        monkeypatch.setattr(dashboard, "AGENT_ROOT", tmp_path)
        ziel = tmp_path / "d.html"
        app = {"key": "k", "firma": "HENSOLDT", "titel": "Testingenieur", "status": "neu",
               "score": 8, "quelle": manual.MAIL_LEAD, "text_fehlt": True}
        dashboard.build_dashboard({"applications": [app]}, ziel)
        html = ziel.read_text(encoding="utf-8")
        daten = json.loads(re.search(r"const DATA = (\[.*?\]);", html, re.S).group(1)
                           .replace("<\\/", "</"))
        assert daten[0]["textFehlt"] is True
        assert daten[0]["visible"] is False
        assert daten[0]["quelle"] == manual.MAIL_LEAD
        assert 'id="pruefPanel"' in html and "function renderPruef" in html
