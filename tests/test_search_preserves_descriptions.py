"""Regressionstest: ein Suchlauf darf geladene Anzeigentexte nicht verlieren.

``run_search`` ersetzt ``jobs.json`` vollständig, die Suchprovider liefern aber
nur Titel und URL. Der Volltext kommt erst über ``fetch_descriptions`` und lag
danach nur in SQLite. Ohne Rückgriff auf den Bestand bewertete das folgende
Matching die Stellen nur nach dem Titel — 61 Stellen fielen von ihrem echten Fit
auf 0–10 % zurück.
"""

from __future__ import annotations

from bewerbungsagent.pipeline import _preserve_descriptions


def _job(url: str, firma: str = "Acme", titel: str = "Testingenieur") -> dict:
    return {"url": url, "firma": firma, "titel": titel}


def _state(**apps) -> dict:
    return {"applications": list(apps.values())}


def _app(url: str, **over) -> dict:
    app = {"key": url, "firma": "Acme", "titel": "Testingenieur"}
    app.update(over)
    return app


class TestPreserveDescriptions:
    def test_uebernimmt_text_aus_dem_bestand(self):
        jobs = [_job("https://x/1")]
        state = _state(a=_app("https://x/1", beschreibung="Aufgaben: HiL-Tests"))

        _preserve_descriptions(jobs, state)

        assert jobs[0]["beschreibung"] == "Aufgaben: HiL-Tests"

    def test_frischer_text_gewinnt(self):
        """Ein neu geladener Text (z. B. aus dem ATS) wird nicht überschrieben."""
        jobs = [_job("https://x/1")]
        jobs[0]["beschreibung"] = "Neuer Volltext aus dem ATS"
        state = _state(a=_app("https://x/1", beschreibung="Alter Text"))

        _preserve_descriptions(jobs, state)

        assert jobs[0]["beschreibung"] == "Neuer Volltext aus dem ATS"

    def test_neue_stelle_bleibt_unberuehrt(self):
        jobs = [_job("https://x/neu")]

        _preserve_descriptions(jobs, _state(a=_app("https://x/1", beschreibung="Alt")))

        assert "beschreibung" not in jobs[0]

    def test_leere_beschreibung_im_bestand_wird_nicht_kopiert(self):
        jobs = [_job("https://x/1")]
        state = _state(a=_app("https://x/1", beschreibung="   "))

        _preserve_descriptions(jobs, state)

        assert not jobs[0].get("beschreibung")

    def test_verfuegbarkeit_wird_uebernommen(self):
        """Einmal geprüft „abgelaufen" darf nicht auf „unbekannt" zurückfallen."""
        jobs = [_job("https://x/1")]
        state = _state(a=_app("https://x/1", verfuegbar=False,
                              verfuegbar_grund="Anzeige abgelaufen"))

        _preserve_descriptions(jobs, state)

        assert jobs[0]["verfuegbar"] is False
        assert jobs[0]["verfuegbar_grund"] == "Anzeige abgelaufen"

    def test_ohne_bestand_passiert_nichts(self):
        jobs = [_job("https://x/1")]
        assert _preserve_descriptions(jobs, {}) == jobs
        assert _preserve_descriptions(jobs, {"applications": []}) == jobs

    def test_fallback_key_ohne_url(self):
        """Ältere Einträge ohne URL werden über Firma|Titel wiedergefunden."""
        from bewerbungsagent.pipeline import _job_key
        job = {"firma": "Acme", "titel": "Testingenieur"}
        state = _state(a={"key": _job_key(job), "firma": "Acme",
                          "titel": "Testingenieur", "beschreibung": "Text"})

        _preserve_descriptions([job], state)

        assert job["beschreibung"] == "Text"
