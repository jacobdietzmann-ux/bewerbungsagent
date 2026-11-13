"""Einladungen/Zusagen: erkennen, zuordnen und den Dashboard-Status prüfen."""

from __future__ import annotations

from bewerbungsagent.absagen import art_of, positives

APP_SENT = {
    "key": "renesas|test automation engineer",
    "firma": "Renesas Electronics",
    "titel": "Test Automation Engineer (m/w/d)",
    "status": "sent",
    "deleted": False,
}
APP_DOCS = {**APP_SENT, "key": "renesas|test automation engineer 2", "status": "docs"}

EINLADUNG = {
    "id": "4711",
    "date": "Fri, 30 Oct 2026 10:00:00 +0100",
    "from": "Talent Team <talent@renesas.com>",
    "subject": "Einladung zum Vorstellungsgespräch – Test Automation Engineer (m/w/d)",
    "body": "Gerne möchten wir Sie zu einem Vorstellungsgespräch einladen. "
            "Bitte nennen Sie uns zwei Terminvorschläge.",
}

ZUSAGE = {
    "id": "4712",
    "date": "Fri, 30 Oct 2026 11:00:00 +0100",
    "from": "Personal <personal@renesas.com>",
    "subject": "Ihre Zusage – Test Automation Engineer (m/w/d)",
    "body": "Vielen Dank für Ihre Bewerbung. Wir freuen uns, Ihnen die Stelle anzubieten. "
            "Der Arbeitsvertrag liegt bei.",
}

EINGANG = {
    "id": "4713",
    "date": "Fri, 30 Oct 2026 12:00:00 +0100",
    "from": "Talent Team <talent@renesas.com>",
    "subject": "Ihre Bewerbung bei Renesas",
    "body": "Vielen Dank für Ihre Bewerbung. Hiermit bestätigen wir den Eingang.",
}

ABSAGE = {
    "id": "4714",
    "date": "Fri, 30 Oct 2026 13:00:00 +0100",
    "from": "Talent Team <talent@renesas.com>",
    "subject": "Ihre Bewerbung bei Renesas",
    "body": "Leider können wir Ihre Bewerbung nicht weiter berücksichtigen.",
}


class TestArtOf:
    def test_einladung(self):
        assert art_of(EINLADUNG["subject"], EINLADUNG["body"]) == "einladung"

    def test_zusage(self):
        assert art_of(ZUSAGE["subject"], ZUSAGE["body"]) == "angebot"

    def test_eingangsbestaetigung_ist_keine_einladung(self):
        assert art_of(EINGANG["subject"], EINGANG["body"]) == ""

    def test_absage_gewinnt(self):
        assert art_of(ABSAGE["subject"], ABSAGE["body"]) == ""
        assert art_of("Einladung zum Gespräch", "Leider müssen wir Ihnen absagen.") == ""

    def test_negierte_einladung_ist_keine(self):
        assert art_of("Ihre Bewerbung", "Leider können wir Sie nicht zu einem Gespräch "
                                        "einladen. Es gab passendere Kandidaten.") == ""

    def test_fortschritt_braucht_bewerbungskontext(self):
        assert art_of("Your application at Quantum-Systems",
                      "you are now one step further in the application process") == "fortschritt"
        assert art_of("Newsletter", "you are now one step further") == ""

    def test_feier_einladung_ist_keine_zusage(self):
        # „Zusage" ist auch die Antwort auf eine private Einladung (real:
        # Limonadenfeier, 06.11.2026) — ohne Bewerbungskontext kein Angebot.
        assert art_of("Limonadenfeier (ehem. Weihnachtsfeier) Einladung 26.11.2026",
                      "Bitte gebt uns bis 15.11. Bescheid. Zusage oder Absage?") == ""
        # Die echte Mail (IGEL) sagt „Wir Laden Dich zu der Limonadenfeier ein":
        # das Einladungsmuster „laden … ein" greift, ohne Event-Filter wäre das
        # ein Bewerbungstermin.
        assert art_of("Limonadenfeier (ehem. Weihnachtsfeier) Einladung 26.11.2026",
                      "Wir Laden Dich zu der Limonadenfeier ein. Treffpunkt BMW Welt, "
                      "Dresscode: Smart, Beginn mit Glühwein auf der Terrasse.") == ""
        # Ein echter Termin bleibt ein Termin, auch wenn ein Event erwähnt wird.
        assert art_of("Einladung zum Vorstellungsgespräch",
                      "Wir laden Sie zu einem Vorstellungsgespräch ein; den Kick-off "
                      "im Team besprechen wir dort.") == "einladung"

    def test_eingangsbestaetigung_ist_kein_fortschritt(self):
        assert art_of("Application Received – Filics",
                      "Thank you for submitting your application. We will be in touch soon "
                      "regarding next steps.") == ""


class TestPositives:
    def test_einladung_auf_versendete_bewerbung(self):
        r = positives([EINLADUNG], [APP_SENT])
        assert len(r) == 1
        assert r[0]["key"] == APP_SENT["key"]
        assert r[0]["ok"] is True
        assert r[0]["hinweis"] == "Dashboard: Versendet"
        assert r[0]["mail_id"] == "4711"
        assert r[0]["datum"] == "2026-10-30"

    def test_einladung_auf_unterlagen_status_wird_gemeldet(self):
        r = positives([EINLADUNG], [APP_DOCS])
        assert len(r) == 1
        assert r[0]["key"] == APP_DOCS["key"]
        assert r[0]["ok"] is False
        assert "docs" in r[0]["hinweis"]

    def test_unbekannte_firma_wird_gemeldet(self):
        r = positives([EINLADUNG], [])
        assert len(r) == 1
        assert r[0]["key"] is None
        assert r[0]["ok"] is False
        assert "keine passende Bewerbung" in r[0]["hinweis"]

    def test_keine_meldung_ohne_einladung(self):
        assert positives([EINGANG, ABSAGE], [APP_SENT]) == []

    def test_interview_status_gilt_als_versendet(self):
        app = {**APP_SENT, "status": "interview"}
        r = positives([EINLADUNG], [app])
        assert r[0]["ok"] is True

    def test_rejected_gilt_als_versendet(self):
        # Eine Absage setzt eine versendete Bewerbung voraus — kein Befund.
        app = {**APP_SENT, "status": "rejected"}
        r = positives([EINLADUNG], [app])
        assert r[0]["ok"] is True

    def test_kalender_digest_wird_ignoriert(self):
        mail = {**EINLADUNG, "from": "Google Calendar <calendar-notification@google.com>"}
        assert positives([mail], [APP_SENT]) == []


def test_einladung_nennt_den_echten_status():
    """SII stand auf Interview, der Bericht meldete trotzdem „versendet" (13.11.2026)."""
    r = positives([EINLADUNG], [{**APP_SENT, "status": "interview"}])
    assert r[0]["ok"] is True
    assert r[0]["hinweis"] == "Dashboard: Interview"
