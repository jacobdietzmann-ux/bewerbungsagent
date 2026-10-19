"""Tests für die Bereinigung des Bestands (``run_enrich``).

Regel: Stellen, für die bereits Unterlagen erzeugt wurden, sind eine bewusste
Entscheidung und werden **nicht** wegen eines niedrigen FIT ausgeblendet.
Die harte Pendelweg-Grenze gilt weiterhin für alle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungsagent.config import Config
from bewerbungsagent.db import Store
from bewerbungsagent.pipeline import run_enrich, run_generate
from bewerbungsagent.storage import save_json


def _job(key: str, **over) -> dict:
    app = {
        "key": key,
        "firma": "Beispiel GmbH",
        "titel": "Testingenieur",
        "url": f"https://example.test/{key}",
        "status": "docs",
        "score": 30,
        "pendel_modus": "Auto",
        "pendelzeit_min": 25,
        "pendeldistanz_km": 20.0,
    }
    app.update(over)
    return app


@pytest.fixture
def config(tmp_path: Path, tmp_config: dict) -> Config:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(path)


@pytest.fixture(autouse=True)
def _kein_netzwerk(monkeypatch):
    """Pendelweg/Gehalt nicht neu berechnen — der Test setzt die Werte selbst.

    ``run_enrich`` würde sonst per Nominatim/OSRM arbeiten und die vorgegebene
    Pendelzeit überschreiben (ohne ``ort`` sogar auf ``None``).
    """
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                        lambda apps, data_dir, home_address=None, contact_email=None,
                               office_overrides=None: {"total": len(apps)})
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary",
                        lambda apps: {"kept": 0, "estimated": 0})


@pytest.fixture(autouse=True)
def generated_calls(monkeypatch):
    """Dokumenterzeugung abfangen.

    Die Tests prüfen die Auswahl-Logik, nicht das PDF-Setzen — und die
    Auto-Erzeugung würde sonst ein echtes Profil verlangen.
    """
    calls: list[dict] = []
    def _fake(config, profile, app, template=None):
        calls.append(app)
        return []

    monkeypatch.setattr("bewerbungsagent.pipeline._generate_one", _fake)
    return calls


def _run(config: Config, apps: list[dict]) -> dict:
    Store(config.db_path()).save_state({"applications": apps})
    return run_enrich(config, None)


class TestDocumentedJobsKeepVisible:
    def test_niedriger_fit_ohne_unterlagen_wird_ausgeblendet(self, config):
        result = _run(config, [_job("ohne-unterlagen")])
        assert result["deleted_fit_under_50"] == 1

    def test_niedriger_fit_mit_unterlagen_bleibt_sichtbar(self, config):
        """Kernregel: erzeugte Dokumente = bewusste Entscheidung."""
        apps = [_job("mit-unterlagen", dokumente={"de": {"anschreiben": "x.pdf"}})]
        result = _run(config, apps)
        assert result["deleted_fit_under_50"] == 0
        state = Store(config.db_path()).load_state()
        assert not state["applications"][0].get("deleted")

    def test_bereits_ausgeblendete_dokumentierte_werden_zurueckgeholt(self, config):
        """Einmalige Reparatur: frühere Läufe haben sie allein wegen FIT versteckt."""
        apps = [_job("alt", deleted=True, dokumente={"de": {}})]
        result = _run(config, apps)
        assert result["restored_documented"] == 1
        state = Store(config.db_path()).load_state()
        assert not state["applications"][0].get("deleted")
        assert not state["applications"][0].get("deleted_reason")

    def test_pendelweg_bleibt_harte_grenze(self, config):
        """Auch mit Unterlagen: zu weiter Pendelweg bleibt ausgeblendet."""
        apps = [_job("weit", pendelzeit_min=200, dokumente={"de": {}})]
        result = _run(config, apps)
        state = Store(config.db_path()).load_state()
        assert state["applications"][0].get("deleted") is True
        assert "Pendelweg" in state["applications"][0].get("deleted_reason", "")
        assert result["restored_documented"] == 0

    def test_versendete_stellen_werden_nicht_angefasst(self, config):
        apps = [_job("gesendet", status="sent", score=5)]
        result = _run(config, apps)
        assert result["deleted_fit_under_50"] == 0
        state = Store(config.db_path()).load_state()
        assert not state["applications"][0].get("deleted")


class TestAutoGenerationRoleGuard:
    """Ein hoher Fit allein belegt keine passende Rolle.

    „Embedded Linux & Release Engineer" erreichte 73 % über generische
    Technologie-Treffer (embedded, linux, python) und bekam ungefragt Unterlagen.
    """

    def test_software_rolle_ohne_rollen_signal_wird_uebersprungen(self, config, generated_calls):
        apps = [_job("sw", titel="Embedded Linux & Release Engineer (m/f/d)", score=80)]
        result = _run(config, apps)
        assert generated_calls == []
        assert len(result["skipped_role"]) == 1

    def test_testrolle_wird_automatisch_beworben(self, config, generated_calls):
        apps = [_job("test", titel="Senior Embedded Systems Test Engineer", score=80)]
        _run(config, apps)
        assert len(generated_calls) == 1

    @pytest.mark.parametrize("titel", [
        "Payload Integration Engineer - UGV Platforms",   # ausdrücklich gewünscht
        "Systemtest und Integrationsingenieur",
        "Systems Engineer (m/w/d) - Schwerpunkt Mechatronik",
    ])
    def test_erwaehlte_rollen_bleiben_erlaubt(self, config, generated_calls, titel):
        _run(config, [_job("ok", titel=titel, score=80)])
        assert len(generated_calls) == 1

    def test_manueller_auftrag_ist_nicht_betroffen(self, config, generated_calls):
        """``run_generate`` erzeugt weiterhin für jede explizit gewählte Stelle —
        auch wenn der Titel kein Rollen-Signal hat."""
        match = {**_job("sw", titel="Linux Software Engineer", score=80), "id": 7,
                 "fit_geschaetzt": "hoch"}
        save_json(config.matches_path(), [match])
        run_generate(config, None, job_ids=[7])
        assert [a["titel"] for a in generated_calls] == ["Linux Software Engineer"]


class TestMengenlaufRoleGuard:
    """Der Mengenlauf braucht denselben Rollen-Schutz wie die Auto-Erzeugung.

    Das war ein echter Bug: der Graph rief ``run_generate`` auf, das den Filter
    nicht hatte. Für 20 Software-/Hardware-Rollen (Broadcast Engineer, Technischer
    Autor, HPC Systems Administrator, …) entstanden Unterlagen und ihr Status
    sprang von ``neu`` auf ``docs``.
    """

    def _matches(self, config, *titel):
        save_json(config.matches_path(),
                  [{**_job(f"m{i}", titel=t, score=80), "id": i + 1, "fit_geschaetzt": "hoch"}
                   for i, t in enumerate(titel)])

    def test_rolle_ohne_signal_wird_uebersprungen(self, config, generated_calls):
        self._matches(config, "Broadcast Engineer / Medieningenieur (m/w/d)")
        result = run_generate(config, None)
        assert generated_calls == []
        assert len(result["skipped_role"]) == 1

    def test_testrolle_wird_erzeugt(self, config, generated_calls):
        self._matches(config, "Senior Embedded Systems Test Engineer")
        run_generate(config, None)
        assert [a["titel"] for a in generated_calls] == ["Senior Embedded Systems Test Engineer"]

    def test_gemischter_lauf_trennt_korrekt(self, config, generated_calls):
        self._matches(config, "Softwareentwickler (gn) C++ / Rust", "Systemtest-Ingenieur")
        result = run_generate(config, None)
        assert [a["titel"] for a in generated_calls] == ["Systemtest-Ingenieur"]
        assert [a["titel"] for a in result["skipped_role"]] == ["Softwareentwickler (gn) C++ / Rust"]


class TestDeletedFlagIsReevaluated:
    """Ein Ausblende-Grund muss noch gelten — sonst bleibt die Stelle für immer weg.

    Beim Nachladen der Anzeigentexte lagen 14 zuvor gelöschte Stellen plötzlich
    bei 50–68 %, weil sie ohne Text maximal 38 % erreichen konnten.
    """

    def test_fit_grund_entfallen_macht_wieder_sichtbar(self, config):
        apps = [_job("alt", deleted=True, deleted_reason="FIT < 50 %", score=62)]
        result = _run(config, apps)
        assert result["restored_reason"] == 1
        assert not Store(config.db_path()).load_state()["applications"][0].get("deleted")

    def test_fit_grund_gilt_weiter_bleibt_ausgeblendet(self, config):
        apps = [_job("weiter", deleted=True, deleted_reason="FIT < 50 %", score=30)]
        result = _run(config, apps)
        assert result["restored_reason"] == 0
        assert Store(config.db_path()).load_state()["applications"][0].get("deleted")

    def test_weit_entfernte_stelle_bleibt_auch_mit_altem_grund_ausgeblendet(self, config):
        apps = [_job("weit", deleted=True, deleted_reason="Pendelweg > 90 min",
                     score=80, pendelzeit_min=200)]
        result = _run(config, apps)
        assert result["restored_reason"] == 0
        assert Store(config.db_path()).load_state()["applications"][0].get("deleted")

    def test_unbekannte_herkunft_bleibt_unangetastet(self, config):
        """Ohne Begründung lässt sich nicht prüfen, ob sie noch gilt."""
        apps = [_job("unklar", deleted=True, score=80)]
        _run(config, apps)
        assert Store(config.db_path()).load_state()["applications"][0].get("deleted")


class TestUserCriteriaAreUntouched:
    """Vom Nutzer gesetzte Kriterien sind eine Entscheidung, kein Zustand."""

    @pytest.mark.parametrize("reason", [
        "Fit <= 60 Prozent (Nutzerkriterium)",
        "Fit unter 60 Prozent (Neubewertung 10.10.2026)",
        "Nicht passende Rolle (kein technisches Profil)",
    ])
    def test_nutzerkriterium_bleibt_auch_bei_hohem_fit(self, config, reason):
        apps = [_job("k", deleted=True, deleted_reason=reason, score=90)]
        result = _run(config, apps)
        assert result["restored_reason"] == 0
        assert result["restored_documented"] == 0
        assert Store(config.db_path()).load_state()["applications"][0].get("deleted")


class TestStaleCommuteReason:
    def test_veralteter_pendel_grund_wird_neu_bewertet(self, config):
        """Alter Grund (``Pendelweg > 90 min``), aber die Strecke wurde neu auf
        25 min berechnet — der Grund gilt nicht mehr und die Stelle kommt zurück."""
        apps = [_job("airbus", deleted=True, deleted_reason="Pendelweg > 90 min",
                     score=78, pendelzeit_min=25)]
        result = _run(config, apps)
        assert result["restored_reason"] == 1
        assert not Store(config.db_path()).load_state()["applications"][0].get("deleted")

    def test_aktuelle_grenze_bleibt_wirksam(self, config):
        apps = [_job("weit", deleted=True, deleted_reason="Pendelweg > 90 min",
                     score=78, pendelzeit_min=120)]
        assert _run(config, apps)["restored_reason"] == 0
        assert Store(config.db_path()).load_state()["applications"][0].get("deleted")


class TestActiveApplicationsAreNeverHidden:
    """Versendete Bewerbungen dokumentieren echte Aktivität.

    Drei davon (u. a. AIRBUS „Systemingenieur" mit 78 %) waren durch ein
    veraltetes ``deleted``-Flag im Dashboard unsichtbar, obwohl die
    Bereinigungslogik aktive Status grundsätzlich ausnimmt.
    """

    @pytest.mark.parametrize("status", ["sent", "followup", "interview", "rejected"])
    def test_altes_flag_wird_entfernt(self, config, status):
        apps = [_job("aktiv", status=status, deleted=True,
                     deleted_reason="Pendelzeit ueber 30 Minuten", score=78)]
        result = _run(config, apps)
        assert result["restored_active"] == 1
        assert not Store(config.db_path()).load_state()["applications"][0].get("deleted")

    def test_pendelweg_grenze_gilt_trotzdem_fuer_neue_stellen(self, config):
        """Die harte Grenze verhindert weiterhin das Anlegen neuer Stellen."""
        apps = [_job("weit", status="neu", pendelzeit_min=200)]
        result = _run(config, apps)
        assert result["deleted_commute"] == 1


class TestStudentRolesAlwaysHidden:
    """Werkstudent/Praktikant/Auszubildender werden kategorisch ausgeblendet —
    auch mit Unterlagen oder bei hohem FIT, weil die Rolle selbst falsch ist."""

    def test_werkstudent_wird_auch_mit_dokumenten_ausgeblendet(self, config):
        apps = [_job("werk", titel="Werkstudent (m/w/d) Testautomatisierung",
                     score=60, dokumente={"de": {"anschreiben": "x.pdf"}})]
        result = _run(config, apps)
        assert result["deleted_student"] == 1
        app = Store(config.db_path()).load_state()["applications"][0]
        assert app.get("deleted") is True
        assert "Studenten-/Praktikumsstelle" in app["deleted_reason"]

    def test_praktikant_bei_hohem_fit_ausgeblendet(self, config):
        apps = [_job("prakti", titel="Praktikant Testautomatisierung (m/w/d)", score=80)]
        result = _run(config, apps)
        assert result["deleted_student"] == 1

    def test_abgeschlossener_werkstudent_wird_auch_ausgeblendet(self, config):
        """Ein fehladressierter Studenten-Eintrag ist kein wertvoller Verlauf."""
        apps = [_job("alt", titel="Werkstudent Testautomatisierung",
                     status="rejected", score=60,
                     dokumente={"de": {"anschreiben": "x.pdf"}})]
        result = _run(config, apps)
        assert result["deleted_student"] == 1
        app = Store(config.db_path()).load_state()["applications"][0]
        assert app.get("deleted") is True

    def test_echte_testrolle_bleibt_unangetastet(self, config):
        apps = [_job("test", titel="System Test Engineer (m/f/d)", score=80)]
        result = _run(config, apps)
        assert result["deleted_student"] == 0
        app = Store(config.db_path()).load_state()["applications"][0]
        assert not app.get("deleted")


class TestFitBaender:
    """50–64 % → ``research``, ab 65 % → ``docs``.

    Ein Anschreiben für einen 55-%-Treffer kostet Zeit und geht fast nie durch.
    Zuvor lag die Unterlagen-Schwelle bei 50 %, und ``run_enrich`` hatte die 50
    fest verdrahtet — die Konfiguration war dort wirkungslos.
    """

    def test_mittleres_band_bekommt_keine_unterlagen(self, config, generated_calls):
        _run(config, [_job("mittel", score=60)])
        assert generated_calls == []

    def test_ab_65_prozent_werden_unterlagen_erzeugt(self, config, generated_calls):
        _run(config, [_job("hoch", score=65)])
        assert [a["titel"] for a in generated_calls] == ["Testingenieur"]

    def test_grenze_bei_64_keine_unterlagen(self, config, generated_calls):
        _run(config, [_job("knapp", score=64)])
        assert generated_calls == []

    def test_bereits_erzeugte_unterlagen_im_mittelband_werden_zurueckgenommen(self, config):
        apps = [_job("alt", score=60, status="docs",
                     dokumente={"anschreiben_de": "x/Anschreiben.pdf"})]
        result = _run(config, apps)
        assert [z["titel"] for z in result["zurueckgenommen"]] == ["Testingenieur"]
        app = Store(config.db_path()).load_state()["applications"][0]
        assert app["status"] == "research"
        # Die Dateien bleiben referenziert — es wird nichts gelöscht.
        assert app["dokumente"]

    def test_versendete_stelle_im_mittelband_bleibt_docs(self, config):
        """Echte Aktivität wird nicht nachträglich kleingerechnet."""
        apps = [_job("gesendet", score=60, status="docs", sentAt="2026-10-14T18:30:00",
                     dokumente={"anschreiben_de": "x/Anschreiben.pdf"})]
        result = _run(config, apps)
        assert result["zurueckgenommen"] == []
        assert Store(config.db_path()).load_state()["applications"][0]["status"] == "docs"

    def test_interview_im_mittelband_bleibt(self, config):
        apps = [_job("iv", score=55, status="docs", interviewDate="2026-11-03",
                     dokumente={"anschreiben_de": "x/Anschreiben.pdf"})]
        result = _run(config, apps)
        assert result["zurueckgenommen"] == []

    def test_hoeherer_fit_bleibt_docs(self, config):
        apps = [_job("hoch", score=72, status="docs",
                     dokumente={"anschreiben_de": "x/Anschreiben.pdf"})]
        result = _run(config, apps)
        assert result["zurueckgenommen"] == []
        assert Store(config.db_path()).load_state()["applications"][0]["status"] == "docs"

    def test_konfiguration_steuert_die_schwelle(self, config, generated_calls, monkeypatch):
        """``min_fit_for_generation: mittel`` senkt sie wieder auf 50 %."""
        config.data["documents"]["min_fit_for_generation"] = "mittel"
        _run(config, [_job("mittel", score=55)])
        assert [a["titel"] for a in generated_calls] == ["Testingenieur"]

    def test_unter_50_wird_ausgeblendet_nicht_research(self, config):
        """Unter 50 % bleibt es beim Ausblenden — das ist kein Research-Fall."""
        result = _run(config, [_job("zu wenig", score=45)])
        assert result["deleted_fit_under_50"] == 1
        app = Store(config.db_path()).load_state()["applications"][0]
        assert app.get("deleted") is True
        assert app["deleted_reason"] == "FIT < 50 %"


class TestMengenlaufFitBand:
    """``run_generate`` muss dieselbe Schwelle nutzen wie ``run_enrich``."""

    def _matches(self, config, *jobs):
        save_json(config.matches_path(),
                  [{**j, "id": i + 1, "fit_geschaetzt": "mittel"}
                   for i, j in enumerate(jobs)])

    def test_mittelband_wird_uebersprungen(self, config, generated_calls):
        self._matches(config, _job("mittel", score=60))
        run_generate(config, None)
        assert generated_calls == []

    def test_ab_65_wird_erzeugt(self, config, generated_calls):
        self._matches(config, _job("hoch", score=66))
        result = run_generate(config, None)
        assert [a["titel"] for a in generated_calls] == ["Testingenieur"]
        assert result["jobs_processed"] == 1

    def test_ohne_score_zaehlt_fit_pct(self, config, generated_calls):
        """Legacy-Importe haben ``fit_pct`` statt ``score``."""
        self._matches(config, _job("legacy", score=0, fit_pct=70))
        run_generate(config, None)
        assert len(generated_calls) == 1
