"""Mail-Leads im manuellen Import (``search/manual.py``, ``run_search``).

Leads aus Job-Mails haben nur Firma + Titel. Sie dürfen eine vollständige
Anzeige derselben Stelle nie verdrängen, und der Import darf von Hand gepflegte
Einträge nicht anfassen.
"""

from __future__ import annotations

import json
from datetime import date

from bewerbungsagent.search import manual


def _lese(pfad):
    return json.loads(pfad.read_text(encoding="utf-8"))


class TestMergeMailLeads:
    def test_neue_leads_werden_aufgenommen(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        neu = manual.merge_mail_leads(
            pfad, [{"firma": "Expleo", "titel": "Testarchitekt (m/w/d)", "quelle": "Xing"}],
            heute=date(2026, 11, 5))
        assert neu == 1
        eintrag = _lese(pfad)[0]
        assert eintrag["quelle"] == manual.MAIL_LEAD
        assert eintrag["herkunft"] == "Xing"
        assert eintrag["gefunden"] == "2026-11-05"
        assert eintrag["url"] == ""  # nie Tracking-/SSO-Links aus Mails übernehmen

    def test_jobleads_leads_werden_nicht_mehr_aufgenommen(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        neu = manual.merge_mail_leads(pfad, [
            {"firma": "Expleo", "titel": "Testarchitekt (m/w/d)", "quelle": "JobLeads"},
            {"firma": "Zeta", "titel": "Test Engineer", "quelle": "Xing"},
        ], heute=date(2026, 11, 5))
        assert neu == 1
        assert [j["firma"] for j in _lese(pfad)] == ["Zeta"]

    def test_alte_jobleads_leads_im_import_werden_entfernt(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        pfad.write_text(json.dumps([
            {"firma": "Alt", "titel": "Tester", "quelle": manual.MAIL_LEAD,
             "herkunft": "JobLeads", "gefunden": "2026-11-04"},
            {"firma": "Hand", "titel": "Tester", "quelle": "Import"},
        ]), encoding="utf-8")
        manual.merge_mail_leads(pfad, [], heute=date(2026, 11, 5))
        assert [j["firma"] for j in _lese(pfad)] == ["Hand"]

    def test_andere_mail_links_werden_verworfen(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        manual.merge_mail_leads(pfad, [
            {"firma": "A", "titel": "Test A", "url": "https://www.xing.com/m/eM0ojA8V6AZmcpUBi8zLgP"},
            {"firma": "B", "titel": "Test B", "url": "https://click.stepstone.de/f/a/abc~~/def"},
            {"firma": "C", "titel": "Test C", "url": "https://www.jobleads.com/de/job/x?kuuid=x"},
        ], heute=date(2026, 11, 5))
        assert [j["url"] for j in _lese(pfad)] == ["", "", ""]

    def test_bekannter_lead_bekommt_keine_fremde_url(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        lead = {"firma": "Expleo", "titel": "Testarchitekt (m/w/d)"}
        manual.merge_mail_leads(pfad, [lead], heute=date(2026, 11, 5))
        url = "https://www.xing.com/m/abc"
        assert manual.merge_mail_leads(pfad, [{**lead, "url": url}], heute=date(2026, 11, 6)) == 0
        eintrag = _lese(pfad)[0]
        assert eintrag["url"] == ""  # keine übernommene URL mehr
        assert eintrag["gefunden"] == "2026-11-05"

    def test_doppelte_und_unvollstaendige_werden_uebersprungen(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        lead = {"firma": "Expleo", "titel": "Testarchitekt (m/w/d)", "quelle": "Xing"}
        assert manual.merge_mail_leads(pfad, [lead], heute=date(2026, 11, 5)) == 1
        gleich_anders_geschrieben = {"firma": "EXPLEO", "titel": "testarchitekt (m/w/d)"}
        leer = {"firma": "", "titel": "Ohne Firma"}
        assert manual.merge_mail_leads(
            pfad, [gleich_anders_geschrieben, leer], heute=date(2026, 11, 6)) == 0
        assert len(_lese(pfad)) == 1

    def test_handgepflegte_eintraege_bleiben(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        pfad.write_text(json.dumps([{"firma": "Hand", "titel": "Von Hand", "quelle": "Import",
                                     "beschreibung": "Text"}]), encoding="utf-8")
        manual.merge_mail_leads(pfad, [{"firma": "Neu AG", "titel": "Etwas"}],
                                heute=date(2026, 11, 5))
        assert [j["firma"] for j in _lese(pfad)] == ["Hand", "Neu AG"]

    def test_alte_mail_leads_werden_entfernt_manuelle_nicht(self, tmp_path):
        pfad = tmp_path / "import_jobs.json"
        pfad.write_text(json.dumps([
            {"firma": "Alt", "titel": "Alt", "quelle": manual.MAIL_LEAD, "gefunden": "2026-09-01"},
            {"firma": "Hand", "titel": "Alt", "quelle": "Import", "gefunden": "2026-01-01"},
        ]), encoding="utf-8")
        manual.merge_mail_leads(pfad, [], heute=date(2026, 11, 5))
        assert [j["firma"] for j in _lese(pfad)] == ["Hand"]


class TestReihenfolgeInRunSearch:
    """Der Mail-Lead kommt zuletzt: eine vollständige Anzeige gewinnt gegen den Platzhalter."""

    def _lauf(self, tmp_path, jobs):
        from pathlib import Path

        from bewerbungsagent.config import Config
        from bewerbungsagent.profile import Profile
        from bewerbungsagent.search import run_search
        fixture = Path(__file__).resolve().parent / "fixtures" / "profil-demo.json"
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "profil-demo.json").write_text(fixture.read_text(encoding="utf-8"),
                                                   encoding="utf-8")
        (tmp_path / "config.json").write_text(json.dumps({
            "profile_json": str(tmp_path / "profil-demo.json"),
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "output"),
            "search": {"enabled": False, "providers": ["manual"], "query_terms": [],
                       "location": "München"},
        }), encoding="utf-8")
        (tmp_path / "data" / "import_jobs.json").write_text(
            json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        profil = Profile(json.loads((tmp_path / "profil-demo.json").read_text(encoding="utf-8")))
        return run_search(Config(tmp_path / "config.json"), profil)

    def test_mail_lead_ohne_gegenstueck_bleibt(self, tmp_path):
        jobs, _fehler, _n = self._lauf(tmp_path, [
            {"firma": "Expleo", "titel": "Testautomatisierungsarchitekt (m/w/d)",
             "quelle": manual.MAIL_LEAD, "gefunden": "2026-11-05"}])
        assert [j["quelle"] for j in jobs] == [manual.MAIL_LEAD]

    def test_volle_anzeige_verdraengt_den_platzhalter(self, tmp_path):
        jobs, _fehler, _n = self._lauf(tmp_path, [
            # Platzhalter steht in der Datei zuerst …
            {"firma": "Expleo", "titel": "Testautomatisierungsarchitekt (m/w/d)",
             "quelle": manual.MAIL_LEAD, "gefunden": "2026-11-05"},
            # … die echte Anzeige danach.
            {"firma": "Expleo", "titel": "Testautomatisierungsarchitekt (m/w/d)",
             "quelle": "Import", "url": "https://example.com/job/1",
             "beschreibung": "Python, HiL, CI/CD"},
        ])
        assert len(jobs) == 1
        assert jobs[0]["quelle"] == "Import"
        assert "Python" in jobs[0]["beschreibung"]
