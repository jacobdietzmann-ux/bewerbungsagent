"""Absagen aus E-Mails erkennen, der Bewerbung zuordnen und den Grund festhalten.

Eingabe ist eine Liste von Mails (``id``, ``date``, ``from``, ``subject``,
``body``) — woher sie kommen, ist egal: Hermes-Mailcheck (``google_api.py``),
Gmail-Export oder ein Claude-Lauf über den Gmail-Connector. Das Modul greift
selbst nicht auf Gmail zu und schreibt nichts; ``agent.py absagen --apply``
übernimmt das Ergebnis über ``Store.apply_overlay`` (nur Nutzerfelder).

Grundsätze:

* **Lieber nicht zuordnen als falsch zuordnen.** Eine Absage wird nur auf eine
  Bewerbung gebucht, wenn Firma und (bei mehreren offenen Stellen derselben
  Firma) Titel belastbar passen. Alles andere landet in ``unklar``.
* **Kein Zurückstufen.** Nur offene Bewerbungen (``sent``, ``followup``,
  ``interview``) werden auf ``rejected`` gesetzt.
* **Grund ist eine Kategorie, kein Freitext.** Damit lässt sich später zählen,
  *warum* Bewerbungen scheitern (andere Kandidaten, Profil, Stelle weg).

Die Muster stammen aus echten Absagen (ALTEN, Quantum-Systems, FERCHAU, Orizon,
IABG, StepStone-Weiterleitung; Stand 01.11.2026).
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from datetime import timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

from .profile import normalize

OFFENE_STATUS = ("sent", "followup", "interview")

# Starke Absage-Formulierungen (auf ``normalize``-Text: klein, ohne Umlaute
# als Sonderzeichen). Eine davon genügt.
_ABSAGE_STARK = [
    r"nicht (?:weiter|laenger|langer|mehr) beruecksichtig", r"nicht (?:weiter|laenger|langer|mehr) berucksichtig",
    r"nicht in die (?:engere auswahl|naechste runde|nachste runde)",
    r"(?:bewerbung|ihnen|dir) (?:leider )?(?:eine )?absag", r"\babsage\b",
    r"bewerbung (?:an dieser stelle |leider )*ablehnen",
    r"leider (?:mitteilen|mitzuteilen)", r"keine positiven nachrichten",
    r"fuer (?:einen|eine) andere[n]? (?:kandidat|person|bewerber)",
    r"fur (?:einen|eine) andere[n]? (?:kandidat|person|bewerber)",
    r"fuer andere (?:kandidat|bewerber)", r"fur andere (?:kandidat|bewerber)",
    r"du bist leider nicht weiter", r"keine positive (?:ruckmeldung|rueckmeldung)",
    r"(?:kunde|kunden|auftraggeber)\w* .{0,60}anders entschieden",
    r"(?:keine|nicht die) .{0,60}position .{0,60}anbieten", r"position .{0,80}nicht anbieten",
    r"nicht (?:weiter )?verfolgen", r"leider absagen", r"(?:mussen|muessen) .{0,30}absagen",
    r"nicht (?:fur|fuer) die .{0,40}stelle beruecksichtig|nicht (?:fur|fuer) die .{0,40}stelle berucksichtig",
    r"bewerbung .{0,60}nicht beruecksichtigen|bewerbung .{0,60}nicht berucksichtigen", r"nicht fuer sie entschieden", r"nicht fur sie entschieden",
    r"unfortunately", r"we regret", r"regret to inform",
    r"not (?:to )?(?:move|moving|proceed|proceeding) forward",
    r"decline your application", r"cannot consider your application",
    r"not be (?:moving|proceeding)", r"decided to (?:pursue|proceed with) other",
    r"position has been filled", r"no longer (?:being )?consider",
    r"move forward with other candidates",
    r"(?:chosen|decided) to (?:move forward|proceed|continue|go) with other",
]

# Schwaches Signal: typische Schlussformel einer Absage ohne ausdrückliche
# Ablehnung (IABG: „anbei die Korrespondenz … für Ihren weiteren Berufsweg
# viel Erfolg" — die eigentliche Absage steckt im PDF-Anhang).
_ABSAGE_SCHWACH = [
    r"(?:fuer|fur) (?:ihren|deinen) weiteren (?:beruflichen |berufs)?weg",
    r"(?:alles gute|viel erfolg) (?:fuer|fur) (?:ihre|deine) (?:weitere|berufliche) zukunft",
    r"all the best in your (?:future|job search|career)",
    r"every success in your future",
]

# Diese Mails sind keine Absage einer Bewerbung, auch wenn „leider" vorkommt.
_KEINE_ABSAGE = [
    r"bewerbung ist leider nicht angekommen",      # XING: technischer Fehler
    r"eingangsbestaetigung", r"eingangsbestatigung",
    r"(?:we have|we've) received your application",
    r"einladung zum? (?:vorstellungs|interview|gespraech|gesprach)",
    r"invitation to (?:an )?interview",
]

_GRUENDE = [
    ("andere_kandidaten", [
        r"andere[nr]? (?:kandidat|person|bewerber)", r"other candidates?",
        r"naeher ?kamen|naher ?kamen|naeherkamen|naherkamen", r"(?:noch )?(?:etwas )?passender",
        r"closer (?:match|fit)", r"vielzahl (?:der )?(?:sehr guten )?bewerbung",
        r"huge (?:amount|number) of", r"narrow down", r"eingrenzen",
        r"auftraggeber\w* .{0,60}entschieden", r"kunde\w* .{0,60}entschieden",
    ]),
    ("profil_passt_nicht", [
        r"anforderungen (?:nicht|der stelle nicht)", r"profil (?:nicht|passt nicht)",
        r"nicht (?:ausreichend|vollstaendig|vollstandig) (?:passt|entspricht|erfuell|erfull)",
        r"(?:requirements|qualifications) (?:do not|don't|did not) (?:match|meet)",
        r"specific requirements", r"erfahrung (?:in|im|mit) .{0,40}(?:fehlt|nicht)",
        r"profil (?:nicht so gut|nicht ausreichend) gepasst",
        r"keine .{0,40}qualifikation\w* entsprechende position",
    ]),
    ("stelle_weg", [
        r"(?:stelle|position|vakanz) (?:wurde |ist )?(?:bereits )?(?:besetzt|vergeben|zurueckgezogen|zuruckgezogen)",
        r"position has been (?:filled|closed|cancelled|canceled)", r"nicht mehr (?:vakant|verfuegbar|verfugbar)",
        r"on hold", r"projekt .{0,40}(?:abgesagt|gestoppt|verschoben)",
    ]),
]

# Fortschritt im Prozess. Kommt eine solche Mail zur selben Stelle *nach* der
# Absage, wird die Absage nicht gebucht (Quantum-Systems: zwei Ausschreibungen
# derselben Rolle — eine abgesagt, die andere „one step further").
_POSITIV = [
    r"one step further", r"einen schritt weiter", r"next (?:round|step)",
    r"(?:forwarded|weitergeleitet) .{0,60}(?:specialist|fachabteilung|fachbereich|hiring)",
    r"einladung zu", r"invit(?:e|ation) (?:you )?to (?:an? )?(?:interview|call|meeting)",
    r"(?:termin|gespraech|gesprach|interview) .{0,40}vereinbaren",
]

_TALENTPOOL = [r"talent ?pool", r"vormerken", r"in kontakt bleiben", r"stay in touch",
               r"kuenftige|kunftige|zukuenftige|zukunftige|future (?:roles|positions|opportunities)"]

# „Angenommen" heißt: die Mail bringt die Bewerbung voran — Einladung zum Gespräch
# oder Zusage. Beides setzt voraus, dass die Bewerbung tatsächlich raus ist; steht
# sie im Dashboard noch auf „Unterlagen", ist der Status falsch.
_ANGEBOT = [
    r"vertragsangebot", r"arbeitsvertrag .{0,40}(?:sende|erhalten|zu)",
    r"we are (?:pleased|happy|delighted) to offer", r"offer letter",
]
# „Zusage" allein reicht nicht — das ist auch die Antwort auf eine Feier-Einladung
# („Limonadenfeier … Einladung 26.11.2026 / Zusage"). Nur mit Bewerbungskontext.
_ANGEBOT_SCHWACH = [r"\bzusage\b"]
# Einladungen brauchen eine Gesprächs-/Terminformulierung. Blosse Floskeln
# („nächste Schritte", „kennenlernen", „Termin") reichen nicht: damit wurden
# Eingangsbestätigungen, XING-Versandmeldungen und Jobcenter-Videotermine zu
# „Einladungen" (real gemessen am 05.11.2026).
# ``normalize`` faltet Umlaute auf den Grundbuchstaben („Gespräch" → „gesprach"),
# nicht auf „ae" — Muster müssen beide Formen abdecken.
_GESPRAECH = r"(?:gespraech|gesprach)"

_EINLADUNG = [
    # eindeutige Einladungsformulierungen — brauchen keinen weiteren Kontext
    rf"einladung zum? (?:vorstellungs)?(?:{_GESPRAECH}|interview)",
    rf"(?:vorstellungs|bewerbungs){_GESPRAECH} .{{0,40}}(?:\bam\b|termin|einladung|freuen)",
    rf"ein erstes .{{0,30}}(?:{_GESPRAECH}|interview)",
    rf"(?:online.?|telefon.?)?interview (?:mit ihnen )?fuhren",
    r"laden (?:wir )?(?:sie|dich) (?:hiermit |herzlich |gerne )?(?:zu|ein)",
    r"nennen sie mir .{0,40}terminvorschl",
    r"invit(?:e|ation) (?:you )?to (?:an? )?(?:interview|call|meeting)",
]
# Schwache Formulierungen: nur mit Bewerbungskontext („Ihre Bewerbung"/„application").
# Ohne das wurden Jobcenter-Videotermine und Job-Newsletter zu Einladungen.
_EINLADUNG_SCHWACH = [
    r"terminvorschl(?:aege|age|ag)",
    r"termin .{0,30}(?:per |uber )?(?:webex|teams|zoom|video|telefon)",
]

# Fortschritt im Prozess, aber noch kein Termin. Nur mit Bewerbungskontext.
_FORTSCHRITT = [
    r"one step further", r"einen schritt weiter", r"next round",
    r"(?:forwarded|weitergeleitet) .{0,60}(?:specialist|fachabteilung|fachbereich|hiring)",
]
_APPKONTEXT = [r"\bbewerbung\b", r"\bapplication\b", r"\bbewerbungsprozess\b"]
# Betriebs- und Teamevents sehen wie Einladungen aus („Wir Laden Dich zu der
# Limonadenfeier ein", IGEL 06.11.2026 — echtes Beispiel). Kein Bewerbungstermin,
# solange nicht ausdrücklich von Gespräch/Interview die Rede ist.
_VERANSTALTUNG = [
    r"weihnachtsfeier", r"limonadenfeier", r"firmenfeier", r"sommerfest",
    r"jahresabschlussfeier", r"betriebsausflug", r"team ?event", r"teamabend",
    r"save[- ]the[- ]date", r"\bdresscode\b", r"gl(?:ue|u)hwein", r"kick-?off",
]
# Absage-Floskeln, die wie eine Einladung aussehen („leider können wir Sie nicht
# zu einem Gespräch einladen").
_NEGATION = [
    rf"nicht .{{0,40}}(?:einladen|einen termin)",
    r"(?:kein|keinen) (?:termin|gespraechstermin|interviewtermin)",
    rf"nicht zu einem .{{0,30}}(?:{_GESPRAECH}|interview)",
    r"leider .{0,60}(?:kein|keinen) .{0,25}termin",
]


# Status, bei denen das Dashboard „versendet" sagt (interview = nach dem Versand).
# „versendet" heißt: die Bewerbung ist raus. Auch ``rejected`` (eine Absage setzt
# eine versendete Bewerbung voraus) — offen sind nur ``neu``/``research``/``docs``.
POSITIV_STATUS = ("sent", "followup", "interview", "rejected")

# Absender, die keine Bewerbungs-Einladung schicken: Kalender-Digests, Job-Alerts,
# Newsletter. Sie nennen „Termin"/„Meeting" und rutschen sonst durch.
_AUSGENOMMEN = (
    "calendar-notification@", "calendar@google.com", "notifications@", "newsletter@",
    "no-reply@google.com", "no-reply@xing", "jobs@mail.xing.com", "info@jobleads",
)


# Absender-Domains von Plattformen: die Domain sagt nichts über die Firma.
_PLATTFORM_DOMAINS = (
    "stepstone", "personio", "successfactors", "greenhouse", "workday", "smartrecruiters",
    "lever.co", "recruitee", "softgarden", "talent-soft", "jobs.msg.group", "xing",
    "linkedin", "indeed", "join.com", "recruitmail", "career.x1f", "bamboohr", "onlyfy",
)

_STOP = {"gmbh", "mbh", "ag", "se", "kg", "co", "group", "germany", "deutschland", "the",
         "und", "and", "engineering", "technology", "technologies", "services", "solutions",
         "consulting", "systems", "international", "holding", "connecting", "people"}


def _any(patterns: Iterable[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _norm(text: str | None) -> str:
    t = html.unescape(text or "").replace("\xa0", " ")
    return " ".join(normalize(t).split())


def classify(subject: str | None, body: str | None) -> dict:
    """``{"absage": bool, "sicher": bool, "grund": str, "talentpool": bool}``."""
    text = _norm(f"{subject or ''}\n{body or ''}")
    if _any(_KEINE_ABSAGE, text) and not _any(_ABSAGE_STARK, text):
        return {"absage": False, "sicher": True, "grund": "", "talentpool": False}
    stark = _any(_ABSAGE_STARK, text)
    schwach = not stark and _any(_ABSAGE_SCHWACH, text)
    if not (stark or schwach):
        return {"absage": False, "sicher": True, "grund": "", "talentpool": False}
    grund = "unbekannt"
    for name, muster in _GRUENDE:
        if _any(muster, text):
            grund = name
            break
    return {"absage": True, "sicher": stark, "grund": grund,
            "talentpool": _any(_TALENTPOOL, text)}


def _firm_tokens(firma: str | None) -> list[str]:
    """Kennzeichnende Wörter eines Firmennamens („Quantum-Systems GmbH" → quantum)."""
    t = _norm(firma).replace("-", " ").replace("&", " ")
    return [w for w in re.split(r"[^a-z0-9]+", t) if len(w) >= 3 and w not in _STOP]


def _sender_domain(sender: str | None) -> str:
    m = re.search(r"@([\w.-]+)", sender or "")
    return (m.group(1) if m else "").lower()


def firma_passt(app: dict, mail: dict) -> bool:
    """Firma der Bewerbung kommt in Absender-Domain, Betreff oder Mailanfang vor."""
    tokens = _firm_tokens(app.get("firma"))
    if not tokens:
        return False
    domain = _sender_domain(mail.get("from"))
    plattform = any(p in domain for p in _PLATTFORM_DOMAINS)
    if not plattform:
        dom = domain.replace("-", "").replace(".", " ")
        if any(tok in dom.replace(" ", "") for tok in tokens[:1]):
            return True
    kopf = _norm(f"{mail.get('subject') or ''} {(mail.get('body') or '')[:1500]}").replace("-", " ")
    # Ganze Wörter: „alten" steckt sonst in „erhalten".
    return bool(re.search(rf"\b{re.escape(tokens[0])}\b", kopf))


# Titelwörter ohne Unterscheidungskraft (kommen in fast jeder Mail vor).
_TITEL_GENERISCH = {"all", "genders", "gender", "engineer", "ingenieur", "senior", "junior",
                    "lead", "manager", "the", "und", "and", "fur", "fuer", "for", "mit", "with",
                    "bereich", "schwerpunkt"}


def _titel_score(titel: str | None, text: str) -> float:
    """Anteil der kennzeichnenden Titelwörter, die als ganzes Wort in der Mail stehen."""
    t = _norm(re.sub(r"\(.*?\)", " ", titel or ""))
    worte = [w for w in re.split(r"[^a-z0-9+#]+", t)
             if len(w) >= 3 and w not in _TITEL_GENERISCH]
    if not worte:
        return 0.0
    woerter = set(re.split(r"[^a-z0-9+#]+", text.replace("-", " ")))
    return sum(1 for w in worte if w in woerter) / len(worte)


_GENDER = re.compile(r"\(?\b(?:[mwfdx]\s*/\s*){2}[mwfdx]\b\)?|\(?all genders?\)?|\(gn\)", re.I)


def _kern_titel(titel: str | None) -> str:
    t = _GENDER.sub(" ", titel or "")
    t = re.sub(r"\(.*?\)", " ", t)
    return " ".join(_norm(t).replace("-", " ").replace("–", " ").split())


def titel_passt(app: dict, text: str) -> bool:
    """Steht genau diese Stelle in der Mail?

    Streng, weil die Folgen asymmetrisch sind: ARX sagte für vier *andere*
    Rollen ab („Senior Embedded Software Test Engineer" …), während
    „Senior Test Engineer" im Interview stand. Nach Abzug generischer Wörter
    bleibt dort nur „test" — das kommt in jeder dieser Mails vor. Deshalb:
    Kerntitel als Ganzes in der Mail **oder** ≥ 2 kennzeichnende Wörter und
    ≥ 60 % davon getroffen.
    """
    kern = _kern_titel(app.get("titel"))
    flach = " ".join(text.replace("-", " ").replace("–", " ").split())
    if kern and re.search(rf"(?<![a-z0-9]){re.escape(kern)}(?![a-z0-9])", flach):
        return True
    if kern and _abgeschnitten_passt(kern, flach):
        return True
    worte = [w for w in re.split(r"[^a-z0-9+#]+", kern) if len(w) >= 3 and w not in _TITEL_GENERISCH]
    # 80 %: „TOSCA Test Automation Engineer" darf eine Absage für
    # „Test Automation Engineer" (msg, dreimal) nicht übernehmen (2/3 = 67 %).
    return len(worte) >= 2 and _titel_score(app.get("titel"), text) >= 0.8


def _abgeschnitten_passt(kern: str, text: str) -> bool:
    """StepStone kürzt Betreffs („… Schwerpunkt KI & Pla..."): Präfixvergleich.

    Ein Stück vor „..."/„…" passt, wenn seine letzten ≥ 4 Wörter den Anfang des
    Kerntitels bilden und das letzte (angeschnittene) Wort ein Wortanfang ist.
    """
    kern_w = kern.split()
    for m in re.finditer(r"([^.…]{10,200}?)\s*(?:\.\.\.|…)", text):
        frag = _kern_titel(m.group(1)).split()
        for i in range(len(frag)):
            tail = frag[i:]
            if len(tail) < 4 or len(tail) > len(kern_w):
                continue
            if kern_w[:len(tail) - 1] == tail[:-1] and kern_w[len(tail) - 1].startswith(tail[-1]):
                return True
    return False


def _nennt_titel(mail: dict) -> bool:
    """Nennt die Mail eine konkrete Stelle (Gender-Tag oder „role/Position als …")?"""
    roh = f"{mail.get('subject') or ''} {mail.get('body') or ''}"
    if _GENDER.search(roh):
        return True
    t = _norm(roh)
    return bool(re.search(r"\bfor the .{3,80}? role\b|\b(?:position|stelle) als [a-z]"
                          r"|\bbewerbung als [a-z]|\brole (?:of|as) ", t))


def match_mail(mail: dict, apps: list[dict],
               statuses: tuple[str, ...] | None = OFFENE_STATUS,
               allow_title_only: bool = True) -> tuple[dict | None, str]:
    """Ordnet eine Absage-Mail genau einer offenen Bewerbung zu.

    ``statuses=None`` prüft alle nicht gelöschten Bewerbungen — für Einladungen,
    bei denen der Dashboard-Status selbst der Befund ist („steht noch auf
    Unterlagen"). ``allow_title_only=False`` schaltet den Rückfall „langer Titel
    ohne Firmennamen im Absender" ab: für Einladungen ist eine falsche Zuordnung
    schlimmer als keine (real: Fernride-Mail landete bei Quantum-Systems).
    Rückgabe ``(bewerbung, grund)``; ``bewerbung`` ist ``None``, wenn keine oder
    keine eindeutige Zuordnung möglich ist (``grund`` sagt warum).
    """
    offen = [a for a in apps if not a.get("deleted")
             and (statuses is None or a.get("status") in statuses)]

    firma = [a for a in offen if firma_passt(a, mail)]
    text = _norm(f"{mail.get('subject') or ''} {mail.get('body') or ''}")
    if not firma:
        # Plattform-/Konzernabsender ohne Firmennamen der Anzeige (DB InfraGO
        # schreibt als „Deutsche Bahn", StepStone leitet weiter): ein langer,
        # vollständig genannter Titel ist dann eindeutig genug.
        lang = [a for a in offen if len(_kern_titel(a.get("titel")).split()) >= 4
                and titel_passt(a, text)]
        if allow_title_only and len(lang) == 1:
            return lang[0], "eindeutiger Titel (Firma nicht im Absender)"
        return None, "keine offene Bewerbung bei dieser Firma"

    passend = [a for a in firma if titel_passt(a, text)]
    if len(passend) == 1:
        return passend[0], "Firma + Titel"
    if len(passend) > 1:
        return None, f"{len(passend)} offene Bewerbungen passen zum Titel"
    if len(firma) == 1 and not _nennt_titel(mail):
        # Die Mail nennt keine Stelle (z. B. „Your application at ALTEN") und es
        # gibt genau eine offene Bewerbung bei der Firma.
        return firma[0], "eindeutig über Firma"
    if len(firma) == 1:
        return None, "Firma passt, Titel in der Mail weicht ab"
    return None, f"{len(firma)} offene Bewerbungen bei der Firma, Titel nicht eindeutig"


def iso_datum(wert: object) -> str:
    """Mail-Datum als ISO-Zeitstempel (UTC), damit Sortieren und Vergleichen stimmen.

    Gmail-Header kommen als RFC 2822 („Mon, 27 Oct 2026 10:00:00 +0100"),
    Connector-Exporte schon als ISO. Unlesbares bleibt unverändert.
    """
    text = str(wert or "").strip()
    if not text or text[:4].isdigit():
        return text
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return text
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds") + "Z"


def auswerten(mails: list[dict], apps: list[dict]) -> dict:
    """Klassifiziert alle Mails und ordnet Absagen offenen Bewerbungen zu.

    Rückgabe: ``{"updates": [...], "unklar": [...], "keine_absage": n,
    "schon_erfasst": n}``. ``updates`` hat das Format von
    ``scripts/apply_status.py`` plus ``absage_grund``/``absage_talentpool``.
    """
    updates: list[dict] = []
    unklar: list[dict] = []
    keine = 0
    bereits = 0
    gebucht: set[str] = set()
    positiv = []
    mails = [{**m, "date": iso_datum(m.get("date"))} for m in mails]
    for mail in mails:
        t = _norm(f"{mail.get('subject') or ''} {mail.get('body') or mail.get('plaintextBody') or ''}")
        if _any(_POSITIV, t) and not classify(mail.get("subject"), t)["absage"]:
            positiv.append((str(mail.get("date") or ""), t))
    for mail in sorted(mails, key=lambda m: str(m.get("date") or "")):
        body = mail.get("body") or mail.get("plaintextBody") or mail.get("snippet") or ""
        sender = mail.get("from") or mail.get("sender") or ""
        m = {**mail, "body": body, "from": sender}
        k = classify(m.get("subject"), body)
        if not k["absage"]:
            keine += 1
            continue
        app, warum = match_mail(m, [a for a in apps if a.get("key") not in gebucht])
        if app is None and match_mail(m, apps, statuses=("rejected",))[0] is not None:
            # Die Absage ist längst gebucht (z. B. manuell nachgezogen): nicht
            # jeden Tag erneut als Prüffall melden.
            bereits += 1
            continue
        if app is not None and app.get("status") == "interview":
            # Nach einem Gespräch nie automatisch umstellen — erst bestätigen.
            unklar.append({"mail_id": m.get("id"), "datum": str(m.get("date") or "")[:10],
                           "von": sender, "betreff": m.get("subject"), "grund": k["grund"],
                           "talentpool": k["talentpool"], "sicher": k["sicher"],
                           "warum": "Bewerbung steht auf Interview — bitte bestätigen",
                           "vorschlag": app.get("key")})
            continue
        info = {"mail_id": m.get("id"), "datum": str(m.get("date") or "")[:10],
                "von": sender, "betreff": m.get("subject"), "grund": k["grund"],
                "talentpool": k["talentpool"], "sicher": k["sicher"]}
        if app is None or not k["sicher"]:
            unklar.append({**info, "warum": warum if app is None else "nur schwaches Absage-Signal",
                           "vorschlag": (app or {}).get("key")})
            continue
        spaeter = [d for d, t in positiv if d > str(m.get("date") or "") and titel_passt(app, t)]
        if spaeter:
            unklar.append({**info, "warum": f"neuere positive Nachricht zur Stelle ({spaeter[0][:10]})",
                           "vorschlag": app.get("key")})
            continue
        gebucht.add(app["key"])
        updates.append({
            "key": app["key"], "firma": app.get("firma"), "titel": app.get("titel"),
            "status": "rejected", "statusChangedAt": info["datum"],
            "absage_grund": k["grund"], "absage_talentpool": k["talentpool"],
            "zuordnung": warum, "mail_id": m.get("id"), "betreff": m.get("subject"),
        })
    return {"updates": updates, "unklar": unklar, "keine_absage": keine,
            "schon_erfasst": bereits}


def ratio(a: str, b: str) -> float:  # pragma: no cover - Hilfsfunktion für Analysen
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


_ZITAT = [
    r"(?im)^\s*(?:von|from):\s*\"?jacob dietzmann",
    r"(?im)-{2,}\s*urspr(?:ü|u)ngliche nachricht",
    r"(?im)^am .{0,80}schrieb .{0,80}:$",
]


def _ohne_zitat(body: str | None) -> str:
    """Schneidet die zitierte Vorgeschichte ab.

    In Antworten steht der eigene Text mit im Body („Gerne können wir einen
    Termin für ein Gespräch vereinbaren. Mit freundlichen Grüßen Jacob
    Dietzmann"). Ohne Schnitt liest der Erkenner die eigene Formulierung als
    Einladung des Absenders — real passiert bei zwei StepStone-Antworten.
    """
    text = body or ""
    schnitt = len(text)
    for muster in _ZITAT:
        m = re.search(muster, text)
        if m:
            schnitt = min(schnitt, m.start())
    return text[:schnitt]


def art_of(subject: str | None, body: str | None) -> str:
    """Art einer „angenommenen" Mail: ``angebot``, ``einladung``, ``fortschritt`` oder ``""``.

    Absagen und Absage-Floskeln gewinnen immer — „leider können wir Sie nicht zu
    einem Gespräch einladen" ist keine Einladung.
    """
    if classify(subject, body)["absage"]:
        return ""
    text = _norm(f"{subject or ''}\n{_ohne_zitat(body)}")
    if _any(_NEGATION, text):
        return ""
    if _any(_VERANSTALTUNG, text) and not _any(
            [rf"(?:vorstellungs|bewerbungs){_GESPRAECH}", r"\binterview\b"], text):
        return ""
    if _any(_ANGEBOT, text) or (_any(_APPKONTEXT, text) and _any(_ANGEBOT_SCHWACH, text)):
        return "angebot"
    if _any(_EINLADUNG, text):
        return "einladung"
    if _any(_APPKONTEXT, text) and _any(_EINLADUNG_SCHWACH + _FORTSCHRITT, text):
        return "einladung" if _any(_EINLADUNG_SCHWACH, text) else "fortschritt"
    return ""


def positives(mails: list[dict], apps: list[dict]) -> list[dict]:
    """Einladungen/Zusagen samt Dashboard-Prüfung.

    Jede Mail wird einer Bewerbung zugeordnet (Firma + Titel, ohne Statusfilter —
    gerade eine falsch stehengebliebene Bewerbung soll auffallen). ``ok`` ist
    ``True``, wenn das Dashboard „versendet" zeigt (``sent``/``followup``/
    ``interview``/``rejected``); sonst nennt ``hinweis`` den tatsächlichen Status.
    ``mail_id`` ist die IMAP-UID des Mailchecks — damit die Mail als gelesen
    markiert werden kann.
    """
    out: list[dict] = []
    alle = [a for a in apps if not a.get("deleted")]
    for mail in mails:
        body = mail.get("body") or mail.get("plaintextBody") or mail.get("snippet") or ""
        sender = mail.get("from") or mail.get("sender") or ""
        if any(m in sender.lower() for m in _AUSGENOMMEN):
            continue
        art = art_of(mail.get("subject"), body)
        if not art:
            continue
        app, warum = match_mail({**mail, "body": body, "from": sender}, alle,
                                statuses=None, allow_title_only=False)
        info = {
            "mail_id": mail.get("id"),
            "datum": str(iso_datum(mail.get("date")))[:10],
            "von": sender,
            "betreff": mail.get("subject"),
            "art": art,
            "zuordnung": warum,
        }
        if app is None:
            out.append({**info, "key": None, "firma": None, "titel": None, "status": None,
                        "ok": False,
                        "hinweis": f"keine passende Bewerbung im Bestand ({warum})"})
            continue
        status = app.get("status") or ""
        ok = status in POSITIV_STATUS
        out.append({
            **info,
            "key": app.get("key"),
            "firma": app.get("firma"),
            "titel": app.get("titel"),
            "status": status,
            "ok": ok,
            "hinweis": "" if ok else f"Dashboard steht auf '{status}' statt 'versendet'",
        })
    return out


def overlay_from_updates(updates: list[dict],
                         now: Callable[[], str] | None = None) -> dict:
    """``{key: {status, statusChangedAt, absage_grund, absage_talentpool}}`` für ``apply_overlay``."""
    out = {}
    for u in updates:
        out[u["key"]] = {"status": "rejected",
                         "statusChangedAt": u.get("statusChangedAt") or (now() if now else ""),
                         "absage_grund": u.get("absage_grund") or "unbekannt",
                         "absage_talentpool": bool(u.get("absage_talentpool"))}
    return out
