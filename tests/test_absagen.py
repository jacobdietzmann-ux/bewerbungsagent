"""Absage-Erkennung an echten Formulierungen (gekürzt, ohne Personennamen)."""

from __future__ import annotations

from bewerbungsagent.absagen import (
    auswerten,
    classify,
    firma_passt,
    iso_datum,
    match_mail,
    overlay_from_updates,
)

ALTEN = ("Your application at ALTEN",
         "Hello Jacob, Thank you very much for your trust ... Unfortunately, we regret to "
         "inform you today that we cannot consider your application further in the selection "
         "process. Often, minor nuances or very specific requirements in the profile are "
         "decisive ... we would like to include you in our talent pool")
QUANTUM = ("Your application at Quantum-Systems | Senior Payload Integration Engineer - UGV Platforms (m/f/d)",
           "Thank you very much for applying to the role Senior Payload Integration Engineer - UGV "
           "Platforms (m/f/d). From the huge amount of very good applications, we had to narrow "
           "down the candidates ... Unfortunately, we have to decline your application at this point.")
FERCHAU = ("Deine Bewerbung bei FERCHAU München City",
           "Hallo Jacob, für dein Interesse an einer Karriere mit FERCHAU ... müssen wir dir leider "
           "mitteilen, dass wir dich hinsichtlich der Besetzung der Position Versuchsingenieur "
           "Mechatronik (m/w/d) nicht länger berücksichtigen können, da es Kandidat:innen gab, die "
           "den Anforderungen an die ausgeschriebene Stelle näherkamen.")
ORIZON = ("Wir möchten Sie für kommende Jobangebote vormerken",
          "vielen Dank für Ihre Bewerbung als Testingenieur (m/w/d) IP-Netzwerkstrukturen, Defence "
          "... Leider hat sich unser Auftraggeber in diesem konkreten Fall für eine andere Person "
          "entschieden ... Wir nehmen Sie in unseren Talentpool auf")
IABG = ("Korrespondenz zu Ihrer Bewerbung vom 09.10.2026",
        "Sehr geehrter Herr Dietzmann, anbei erhalten Sie die Korrespondenz zu Ihrer Bewerbung in "
        "unserem Hause. Für Ihren weiteren Berufsweg wünschen wir Ihnen viel Erfolg.")
STEPSTONE = ("Jacob, es gibt News zu deiner Bewerbung für Senior IT-Testautomatisierer (m/w/d) Schwerpunkt KI & Pla...",
             "Du bist leider nicht weiter! Deine Bewerbung hat es bei Münchener Verein "
             "Versicherungsgruppe nicht in die nächste Runde geschafft. ... dass wir Sie nicht in "
             "die engere Auswahl nehmen können.")
XING_FEHLER = ("Deine Bewerbung ist leider nicht angekommen.",
               "Leider ist bei der Übermittlung deiner Bewerbung ein Fehler aufgetreten.")
EINGANG = ("Ihre Bewerbung bei HAWE",
           "vielen Dank für Ihre Bewerbung. Hiermit bestätigen wir den Eingang. Wir melden uns.")


class TestClassify:
    def test_echte_absagen(self):
        for subj, body in (ALTEN, QUANTUM, FERCHAU, ORIZON, STEPSTONE):
            k = classify(subj, body)
            assert k["absage"] and k["sicher"], subj

    def test_gruende(self):
        assert classify(*FERCHAU)["grund"] == "andere_kandidaten"
        assert classify(*ORIZON)["grund"] == "andere_kandidaten"
        assert classify(*QUANTUM)["grund"] == "andere_kandidaten"
        assert classify(*ALTEN)["grund"] == "profil_passt_nicht"

    def test_talentpool(self):
        assert classify(*ALTEN)["talentpool"]
        assert classify(*ORIZON)["talentpool"]
        assert not classify(*FERCHAU)["talentpool"]

    def test_iabg_ist_nur_schwaches_signal(self):
        k = classify(*IABG)
        assert k["absage"] and not k["sicher"]

    def test_keine_absagen(self):
        assert not classify(*XING_FEHLER)["absage"]
        assert not classify(*EINGANG)["absage"]
        assert not classify("Einladung zum Vorstellungsgespräch", "Wir freuen uns ...")["absage"]


def _app(key, firma, titel, status="sent"):
    return {"key": key, "firma": firma, "titel": titel, "status": status}


def _mail(subj, body, sender, mid="m1", date="2026-10-22T05:06:24Z"):
    return {"id": mid, "subject": subj, "body": body, "from": sender, "date": date}


class TestMatch:
    def test_firma_ueber_domain(self):
        apps = [_app("a", "ALTEN", "Testingenieur HiL"), _app("b", "STARK Defence", "Test Engineer")]
        app, _ = match_mail(_mail(*ALTEN, "notifications@alten.com"), apps)
        assert app["key"] == "a"

    def test_mehrere_stellen_derselben_firma_ueber_titel(self):
        apps = [_app("q1", "Quantum-Systems GmbH", "Senior Payload Integration Engineer - UGV Platforms (m/f/d)"),
                _app("q2", "Quantum-Systems", "Prototyping Engineer (m/f/d) – Test Benches & Validation"),
                _app("q3", "Quantum-Systems GmbH", "System Test Engineer (m/f/d)")]
        app, warum = match_mail(_mail(*QUANTUM, "abesic@quantum-systems.com"), apps)
        assert app["key"] == "q1", warum

    def test_mehrdeutig_bleibt_unklar(self):
        apps = [_app("f1", "FERCHAU", "Testingenieur (m/w/d)"),
                _app("f2", "FERCHAU", "Systemingenieur (m/w/d)")]
        app, _ = match_mail(_mail("Deine Bewerbung bei FERCHAU", "leider mitteilen ... Absage",
                                  "x@ferchau.com"), apps)
        assert app is None

    def test_plattform_absender_nutzt_text(self):
        apps = [_app("mv", "Münchener Verein Versicherungsgruppe", "Senior IT-Testautomatisierer (m/w/d)"),
                _app("x", "Stepstone GmbH", "Irgendwas")]
        app, _ = match_mail(_mail(*STEPSTONE, "info@email.stepstone.de"), apps)
        assert app["key"] == "mv"

    def test_nur_offene_bewerbungen(self):
        apps = [_app("a", "ALTEN", "Testingenieur", status="rejected"),
                _app("b", "ALTEN", "Testingenieur", status="docs")]
        app, _ = match_mail(_mail(*ALTEN, "notifications@alten.com"), apps)
        assert app is None

    def test_firma_passt_titel_nicht(self):
        apps = [_app("q3", "Quantum-Systems GmbH", "System Test Engineer (m/f/d)")]
        app, warum = match_mail(_mail(*QUANTUM, "abesic@quantum-systems.com"), apps)
        assert app is None and "Titel" in warum


def test_auswerten_und_overlay():
    apps = [_app("a", "ALTEN", "Testingenieur HiL"), _app("i", "IABG", "Systemingenieur")]
    mails = [_mail(*ALTEN, "notifications@alten.com", mid="1", date="2026-10-28T08:36:00Z"),
             _mail(*IABG, "kaczmarek@iabg.de", mid="2"),
             _mail(*EINGANG, "noreply@talent-soft.com", mid="3")]
    r = auswerten(mails, apps)
    assert [u["key"] for u in r["updates"]] == ["a"]
    assert r["updates"][0]["statusChangedAt"] == "2026-10-28"
    assert r["unklar"][0]["warum"] == "nur schwaches Absage-Signal"
    assert r["unklar"][0]["vorschlag"] == "i"
    assert r["keine_absage"] == 1
    ov = overlay_from_updates(r["updates"])
    assert ov == {"a": {"status": "rejected", "statusChangedAt": "2026-10-28",
                        "absage_grund": "profil_passt_nicht", "absage_talentpool": True}}


ARX_ANDERE_ROLLE = (
    "Your Application at ARX Robotics",
    "Thank you very much for your interest in ARX Robotics and for taking the time to submit "
    "your application for the Senior Embedded Software Test Engineer (m/f/d), Safety & Security "
    "Platform role. After careful review, we've decided not to move forward with your application.")
SOPRA = ("Deine Bewerbung als Testautomatisierer (m/w/d)",
         "Wir haben deine Unterlagen sorgf&auml;ltig gepr&uuml;ft und m&uuml;ssen dir leider "
         "mitteilen, dass wir dir die Position als Testautomatisierer (m/w/d) derzeit nicht "
         "anbieten k&ouml;nnen.")


def test_absage_fuer_andere_rolle_trifft_nicht_das_interview():
    apps = [_app("arx", "ARX Robotics", "Senior Test Engineer", status="interview")]
    app, warum = match_mail(_mail(*ARX_ANDERE_ROLLE, "no-reply@eu.greenhouse-mail.io"), apps)
    assert app is None, warum


def test_absage_fuer_genau_diese_rolle():
    apps = [_app("arx", "ARX Robotics", "Senior Test Engineer", status="interview"),
            _app("arx2", "ARX Robotics", "Senior Embedded Software Test Engineer (m/f/d), Safety & Security Platform")]
    app, _ = match_mail(_mail(*ARX_ANDERE_ROLLE, "no-reply@eu.greenhouse-mail.io"), apps)
    assert app["key"] == "arx2"


def test_html_entities():
    k = classify(*SOPRA)
    assert k["absage"] and k["sicher"]
    apps = [_app("s", "Sopra Steria", "Testautomatisierer (m/w/d)")]
    app, _ = match_mail(_mail(*SOPRA, "notifications@careers.soprasteria.com"), apps)
    assert app["key"] == "s"


INGSERV = ("Ingserv GmbH: Ihre Bewerbung",
           "Leider haben wir keine positive Rückmeldung von unserem Kunden erhalten, da er sich "
           "anders entschieden hat. Daher können wir Ihnen momentan keine Position Ihrer "
           "Qualifikation entsprechend anbieten.")
MSG = ("Deine Bewerbung auf die Position Test Automation Engineer (all genders)",
       "Leider müssen wir dir mitteilen, dass wir deine Bewerbung im weiteren Bewerbungsprozess "
       "in unserem Unternehmen nicht berücksichtigen können. msg systems ag")
DB = ("Rückmeldung zu Ihrer Bewerbung: Planungsingenieur:in für Qualifizierung als "
      "Prüfsachverständige:r Plan- und Abnahmeprüfung (581530)",
      "Leider können wir Sie nicht für die gewünschte Stelle berücksichtigen und müssen Ihnen "
      "daher absagen. In diesem Fall hat Ihr Profil nicht so gut gepasst. Deutsche Bahn AG")


def test_ingserv_kunde_entschieden_und_interview_wird_vorgelegt():
    k = classify(*INGSERV)
    assert k["absage"] and k["sicher"] and k["grund"] == "andere_kandidaten"
    apps = [_app("ing", "INGSERV", "Systems Engineer komplexe technische Systeme", status="interview")]
    r = auswerten([_mail(*INGSERV, "x@ingserv.de")], apps)
    assert r["updates"] == []
    assert r["unklar"][0]["vorschlag"] == "ing"
    assert "Interview" in r["unklar"][0]["warum"]


def test_tosca_wird_nicht_ueber_teiltitel_zugeordnet():
    apps = [_app("t", "msg systems ag", "TOSCA Test Automation Engineer (all genders)")]
    app, _ = match_mail(_mail(*MSG, "candidate-x@jobs.msg.group"), apps)
    assert app is None


def test_konzernabsender_ueber_langen_titel():
    apps = [_app("db", "DB InfraGO AG", "Planungsingenieur:in für Qualifizierung als "
                 "Prüfsachverständige:r Plan- und Abnahmeprüfung")]
    app, warum = match_mail(_mail(*DB, "karriere@deutschebahn.com"), apps)
    assert app and app["key"] == "db", warum
    assert classify(*DB)["grund"] == "profil_passt_nicht"


def test_abgeschnittener_stepstone_titel():
    apps = [_app("mv", "Münchener Verein Versicherungsgruppe",
                 "Senior IT-Testautomatisierer (m/w/d) Schwerpunkt KI & Playwright"),
            _app("x", "Münchener Verein Versicherungsgruppe", "Senior IT-Projektleiter (m/w/d)")]
    app, warum = match_mail(_mail(*STEPSTONE, "info@email.stepstone.de"), apps)
    assert app and app["key"] == "mv", warum


HELSING = ("Regarding your Helsing application",
           "Thank you for your interest in Helsing, and the time you have invested in your "
           "application for the Multimodal Sensing Test Engineer position. After careful "
           "consideration, we have chosen to move forward with other candidates who more closely "
           "align with the requirements of the current opening.")
QS_WEITER = ("Your application at Quantum-Systems | Senior Payload Integration Engineer - UGV Platforms (m/f/d)",
             "Thank you for applying for the position as Senior Payload Integration Engineer - UGV "
             "Platforms (m/f/d). We would like to let you know that you are now one step further in "
             "the application process. We have forwarded your CV to our specialist department.")


def test_helsing_andere_kandidaten():
    k = classify(*HELSING)
    assert k["absage"] and k["sicher"] and k["grund"] == "andere_kandidaten"


def test_weitergekommen_ist_keine_absage():
    assert not classify(*QS_WEITER)["absage"]


def test_neuere_positive_nachricht_verhindert_absage():
    apps = [_app("q1", "Quantum-Systems GmbH", "Senior Payload Integration Engineer - UGV Platforms (m/f/d)")]
    mails = [_mail(*QUANTUM, "abesic@quantum-systems.com", mid="a", date="2026-10-22T05:00:00Z"),
             _mail(*QS_WEITER, "ahesse@quantum-systems.com", mid="b", date="2026-10-28T06:00:00Z")]
    r = auswerten(mails, apps)
    assert r["updates"] == []
    assert "positive Nachricht" in r["unklar"][0]["warum"]


def test_rfc_datum_aus_gmail_header_wird_iso():
    assert iso_datum("Mon, 27 Oct 2026 10:00:00 +0100") == "2026-10-27T09:00:00Z"
    assert iso_datum("2026-10-22T05:00:00Z") == "2026-10-22T05:00:00Z"
    assert iso_datum("") == ""
    apps = [_app("h", "Helsing GmbH", "Multimodal Sensing Test Engineer")]
    r = auswerten([_mail(*HELSING, "no-reply@helsing.ai", date="Thu, 30 Oct 2026 16:12:03 +0100")], apps)
    assert r["updates"][0]["statusChangedAt"] == "2026-10-30"


def test_positive_nachricht_mit_rfc_datum_verhindert_absage():
    apps = [_app("q1", "Quantum-Systems GmbH", "Senior Payload Integration Engineer - UGV Platforms (m/f/d)")]
    mails = [_mail(*QUANTUM, "abesic@quantum-systems.com", mid="a", date="Wed, 22 Oct 2026 07:00:00 +0200"),
             _mail(*QS_WEITER, "ahesse@quantum-systems.com", mid="b", date="Tue, 28 Oct 2026 07:00:00 +0100")]
    r = auswerten(mails, apps)
    assert r["updates"] == []
    assert "2026-10-28" in r["unklar"][0]["warum"]


def test_bereits_gebuchte_absage_wird_nicht_erneut_als_prueffall_gemeldet():
    """Nach dem Buchen derselben Absage bleibt die Mail im Scan, ist aber erledigt.

    Real: Quantum-Systems sagte am 04.11. für „Test Automation Engineer" ab; die
    Bewerbung stand im Bestand noch auf ``docs`` und wurde manuell auf
    ``rejected`` gezogen. Ohne diesen Zweig meldet der Mailcheck die Mail danach
    jeden Tag erneut als „unklar".
    """
    apps = [_app("qs", "Quantum-Systems GmbH", "Test Automation Engineer (m/f/d)", status="rejected")]
    mail = _mail("Your application at Quantum-Systems | Test Automation Engineer (m/f/d)",
                 "Unfortunately, we have to decline your application at this point.",
                 "ahesse@quantum-systems.com")
    r = auswerten([mail], apps)
    assert r["updates"] == []
    assert r["unklar"] == []
    assert r["schon_erfasst"] == 1


SII_EINLADUNG = (
    "AW: Ihre Bewerbung als Software Test Engineer Verteidigungsindustrie - offene Fragen",
    "Guten Tag Herr Dietzmann, gerne möchte KNDS mit Ihnen bzgl. obiger Stelle ein erstes "
    "Online-Interview führen. Wäre Montag, 09.11.2026, um 15:30 Uhr per Webex möglich?")


def test_generisches_firmenwort_matcht_nicht_auf_fremden_absender():
    """„Software Engineering GmbH" (token „software") passte sonst auf jede Mail.

    Real 10.11.2026: eine SII-Einladung zog 18 statt 3 Firmen und blieb dadurch
    ohne Zuordnung.
    """
    mail = _mail(*SII_EINLADUNG, "sandra.domenighini@sii-germany.com")
    assert firma_passt(_app("se", "Software Engineering GmbH", "Software Test Engineer (m/w/d)"), mail) is False


def test_firmenwort_als_teilwort_der_domain_zaehlt_nicht():
    """„man" steckt in „sii-germany.com" — Domain wird segmentweise verglichen."""
    mail = _mail(*SII_EINLADUNG, "sandra.domenighini@sii-germany.com")
    assert firma_passt(_app("man", "MAN Truck & Bus", "Systemingenieur"), mail) is False
    assert firma_passt(_app("sii", "SII Consulting Services", "Software Test Engineer (m/w/x) "
                                                             "Verteidigungsindustrie"), mail) is True


def test_spezifischster_titel_gewinnt_bei_mehreren_treffern():
    apps = [_app("t1", "SII Consulting Services", "Test Engineer (m/w/d)"),
            _app("t2", "SII Consulting Services GmbH", "Software Test Engineer (m/w/d)"),
            _app("t3", "SII Consulting Services", "Software Test Engineer (m/w/x) Verteidigungsindustrie")]
    app, warum = match_mail(_mail(*SII_EINLADUNG, "sandra.domenighini@sii-germany.com"), apps)
    assert app is not None and app["key"] == "t3"
    assert "spezifischster" in warum
