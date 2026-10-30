"""Fit-Scoring: vergleicht eine Stellenanzeige mit dem Skill-Profil.

Der Score ist bewusst transparent und deterministisch, damit der Bewerber die
Einschätzung nachvollziehen und ggf. manuell nachjustieren kann.
"""

from __future__ import annotations

import re

from .commute import all_locations_near_munich, is_multi_location
from .profile import Profile, normalize

# Signale im Stellentitel, die eine hardware-/systemnahe Ingenieursrolle belegen.
#
# Nötig für die *automatische* Unterlagenerzeugung: Ein hoher Score entsteht
# auch bei reinen Software-Rollen, weil Technologie-Begriffe wie ``embedded``,
# ``linux``, ``python`` und ``can`` aus dem Skill-Profil stammen. „Embedded
# Linux & Release Engineer" erreichte damit 73 % und bekam ungefragt Unterlagen.
# Ein Fit allein belegt also nicht, dass die *Rolle* passt.
#
# ``\w*test\w*`` statt ``\btest\w*``: sonst fällt „System**test** und
# Integrationsingenieur" durch, weil in „systemtest" kein Wortanfang vor
# „test" liegt. „integration" und „mechatronik" sind bewusst dabei — sonst
# würde „Payload Integration Engineer" blockiert, eine Rolle, die ausdrücklich
# gewünscht ist.
_ROLE_SIGNAL_RE = re.compile(
    r"\w*test\w*"          # Test, Systemtest, Testingenieur, Testkoordinator
    # ``\w*`` statt ``\b`` am Ende: deutsche Komposita kleben den Stamm an eine
    # Endung („Validierungsingenieur", „Erprobungsingenieur") — eine Wortgrenze
    # direkt nach dem Stamm würde diese Rollen fälschlich ausschließen.
    r"|\bverification\w*|\bvalidation\w*|\bverifikation\w*|\bvalidierung\w*"
    r"|\babsicherung\w*|\berprobung\w*|\bversuchsingenieur\w*"
    # Qualität/Quality (englisch wie deutsch): ``qualitat`` deckt die
    # NFKD-Normalisierung (ä → a) ab, ``qualitaet`` die ae-Transkription.
    r"|\bqualifikation\w*|\bqualifizierung\w*|\bqa\b"
    r"|\bquality\w*|\bqualitat\w*|\bqualitaet\w*"
    r"|\bpruef\w*|\bpruf\w*"          # Prüfstands-, Prüffeld-, Prüfingenieur
    # Domänenwörter, die eine technische Rolle belegen. Das ``(?!er)`` schließt
    # die Berufsbezeichnungen aus: „Elektroniker" ist ein Fertigungsberuf, keine
    # Testrolle. Vorher matchte ``\belektronik\w*`` das Wort, weil „elektronik"
    # ein Präfix von „elektroniker" ist — eine Hilti-Stelle „Elektroniker" bekam
    # dadurch bei 76 % Unterlagen. „Elektroniktests", „Elektrotechnik" und
    # „Mechatronik-Ingenieur" bleiben erlaubt; „Kfz-Mechatroniker" nicht.
    r"|\bmechatronik(?!er)\w*|\belektronik(?!er)\w*|\belektrotechnik(?!er)\w*"
    r"|\bintegration\w*"
    # Automobil-/Embedded-Domänen: ADAS, HPC und ECU belegen eine systemnahe
    # Hardware-/Testrolle (z. B. „ADAS & Autonomous HPC / ECU Specialist").
    r"|\badas\b|\bhpc\b|\becu\b"
)


# Architektur-/Beratungsrollen sind keine Test-/Absicherungsrolle — auch wenn
# der Titel ein Domänenwort wie „Integration" enthält. Genau daran scheiterte
# eine Stelle „Lead Integration Engineer (m/w/d) im Team Technology Consulting":
# sie erfüllte ``_ROLE_SIGNAL_RE`` über ``\bintegration\w*``, bekam bei 84 %
# Unterlagen und beschreibt tatsächlich Integrationsarchitektur (Kafka,
# REST/SOAP, Middleware, API-Governance) statt Test/Verifikation.
#
# ``integration`` bleibt trotzdem im Rollen-Muster: „Payload Integration
# Engineer", „HW/SW Integration Engineer" und „R&D Engineer - AI Integration"
# sind ausdrücklich gewünschte Rollen. Die Ausschluss-Regel greift deshalb nur,
# wenn **kein** Test-/Verifikationssignal im Titel steht — „Test-Architekt" oder
# „Architekt für Testautomatisierung" bleiben erlaubt.
_ARCHITEKTUR_RE = re.compile(
    r"\barchitekt\w*|\barchitect\w*|\bconsult\w*|\bberat\w*|\bpresales?\b",
    re.IGNORECASE,
)

# Der harte Kern: Test/Verifikation/Validierung/Qualität/Prüfung — ohne die
# Domänenwörter (integration, mechatronik, elektronik, adas, hpc, ecu).
_TEST_KERN_RE = re.compile(
    r"\w*test\w*"
    r"|\bverification\w*|\bvalidation\w*|\bverifikation\w*|\bvalidierung\w*"
    r"|\babsicherung\w*|\berprobung\w*|\bversuchsingenieur\w*"
    r"|\bqualifikation\w*|\bqualifizierung\w*|\bqa\b"
    r"|\bquality\w*|\bqualitat\w*|\bqualitaet\w*"
    r"|\bpruef\w*|\bpruf\w*",
)


def has_role_signal(title: str | None) -> bool:
    """True, wenn der Titel auf eine Test-/Absicherungsrolle hindeutet."""
    t = normalize(title or "")
    if not _ROLE_SIGNAL_RE.search(t):
        return False
    architektur = bool(_ARCHITEKTUR_RE.search(t))
    test_kern = bool(_TEST_KERN_RE.search(t))
    return test_kern or not architektur


# Technologie-Stack, den Anzeigen als Anforderung nennen können. Der Abgleich
# ist bewusst eng: Sprachen, Frameworks, Messaging, Datenbanken, Container und
# Plattformen — also Begriffe, deren Fehlen die Ausübbarkeit der Rolle berührt.
# Reine Testwerkzeuge (CANoe, ECU-Test) fehlen absichtlich: die stehen im Profil
# und sind kein Ausschlusskriterium für Integrationsrollen.
#
# ``\brest\b`` fehlt bewusst — im Deutschen ist „der Rest" zu häufig, das würde
# jede zweite Anzeige als REST-Stelle zählen.
_STACK_TERMS: dict[str, str] = {
    "Java": r"\bjava\b(?!script)",
    "JavaScript": r"\bjavascript\b",
    "TypeScript": r"\btypescript\b",
    "Python": r"\bpython\b",
    "C++": r"\bc\+\+",
    "C#/.NET": r"\bc#\b|\.net\b",
    "Spring Boot": r"\bspring\s*boot\b",
    "Apache Camel": r"\bapache\s*camel\b",
    "Kafka": r"\bkafka\b",
    "RabbitMQ": r"\brabbit\s*mq\b|\brabbitmq\b",
    "SOAP": r"\bsoap\b",
    "SQL": r"\bsql\b",
    "Oracle": r"\boracle\b",
    "PostgreSQL": r"\bpostgres\w*",
    "MySQL": r"\bmysql\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "Postman": r"\bpostman\b",
    "SoapUI": r"\bsoapui\b",
    "Grafana": r"\bgrafana\b",
    "Guidewire": r"\bguidewire\b",
    "MATLAB/Simulink": r"\bmatlab\b|\bsimulink\b",
    "SAP": r"\bsap\b",
    "Salesforce": r"\bsalesforce\b",
    "React": r"\breact\b",
    "Angular": r"\bangular\b",
    "Node.js": r"\bnode\.?js\b",
}

# Höchstwert für Stellen, deren genannter Stack vollständig außerhalb des
# Profils liegt und deren Titel keinen Test-/Verifikationskern hat. 60 liegt
# unter dem Research-Fenster (65) und über der Ausblendegrenze (50): die Stelle
# bleibt auffindbar, ist aber kein Research- oder Bewerbungsfall.
STACK_CAP = 60

# Dasselbe Prinzip für Rollen, die keine Test-/Integrationsrolle sind: Ein
# „Principal Engineer – AI-Enabled Embedded Software" (NXP) oder ein
# „Senior Manager CAD Infrastructure" (Infineon) erreichte 100 %, weil der
# Keyword-Fit die Domänenüberschneidung (Embedded, Software, AI) belohnt — die
# ausgeübte Rolle ist aber Produktentwicklung, nicht Test/Absicherung.
ROLE_CAP = 60

# Software-Entwicklung ist eine Stufe weiter entfernt als Hardware-nahe
# Entwicklung: Profil ist Test/Integration/Absicherung, nicht Produktcode.
# 45 liegt unter der Ausblendegrenze (50) — solche Stellen verschwinden aus
# Dashboard und Research, bleiben aber in der Datenbank.
SOFTWARE_CAP = 45

# Domänen- und Rollenwörter für die Software-Rolle. Die Rollenwörter stehen
# ohne führende Wortgrenze, damit deutsche Komposita greifen:
# „Softwareingenieur", „Softwareentwickler", „Systementwickler".
_SOFTWARE_DOMAIN_RE = re.compile(
    r"\bsoftware\w*|\bfirmware\w*|\bbackend\w*|\bfrontend\w*|\bfull[-\s]?stack\w*"
    r"|\bcloud\w*|\bdevops\w*|\bweb\w*|\bmobile\w*|\bandroid\w*"
)
_SOFTWARE_ROLE_RE = re.compile(
    r"entwickler\w*|\bdeveloper\w*|\bengineer\w*|ingenieur\w*|architekt\w*"
    r"|\barchitect\w*|programmierer\w*|\bprogrammer\w*"
)


def is_software_role(title: str | None) -> bool:
    """True, wenn der Titel eine Software-Entwicklungsrolle ohne Testbezug nennt."""
    t = normalize(title or "")
    if _TEST_KERN_RE.search(t):
        return False
    return bool(_SOFTWARE_DOMAIN_RE.search(t) and _SOFTWARE_ROLE_RE.search(t))

# Bestätigte Lücken, die eine Stelle tragen: Steht die Technologie im Titel,
# ist die Rolle ohne sie nicht ausübbar („Testingenieur C++"). Der Deckel liegt
# bei 60 % — unter dem Research-Fenster, über der Ausblendegrenze.
HARD_GAP_CAP = 60
_HARD_GAP_RE = {
    "c++": re.compile(r"\bc\+\+", re.I),
    "c#": re.compile(r"\bc#", re.I),
    "java": re.compile(r"\bjava\b(?!script)", re.I),
}

# Domänenwörter, die eine Entwickler-/Produktrolle anzeigen …
_DEV_DOMAIN_RE = re.compile(
    r"\bsoftware\w*|\bfirmware\w*|\bembedded\w*|\bbackend\w*|\bfrontend\w*"
    r"|\bfull[\s-]?stack\w*|\bweb\w*|\bmobile\w*|\bcloud\w*|\bdevops\w*"
    r"|\bdata\b|\bml\b|\bai\b|\bmachine\s+learning\b|\brobotik\w*|\brobotics?\b"
    r"|\bchip\w*|\bfpga\w*|\bhalbleiter\w*|\bsemiconductor\w*|\bcad\b"
)

# … und die Rollenwörter, die daraus eine Stelle machen (kein „System",
# „Integration" oder „Test" — die bleiben außen vor).
_DEV_ROLE_RE = re.compile(
    r"entwickler\w*|\bdeveloper\w*|\bengineer\w*|ingenieur\w*|\barchitekt\w*|\barchitect\w*"
    r"|\bdesigner\w*|\bmanager\w*|\bleiter\w*|\blead\b|\bhead\b"
)


def is_development_role(title: str | None) -> bool:
    """True, wenn der Titel eine Entwickler-/Produktrolle ohne Testbezug nennt.

    „Software Test Engineer", „Testingenieur Embedded Software" und
    „Entwicklungsingenieur Testsysteme" bleiben erlaubt: Sie tragen einen
    Test-Kern. „Systemingenieur" und „Integrationsingenieur" bleiben ebenfalls
    erlaubt — dort fehlt ein Domänenwort aus ``_DEV_DOMAIN_RE``.
    """
    t = normalize(title or "")
    if _TEST_KERN_RE.search(t):
        return False
    return bool(_DEV_DOMAIN_RE.search(t) and _DEV_ROLE_RE.search(t))

# Erst ab drei genannten Stack-Begriffen wird gedeckelt. Eine Anzeige, die nur
# MATLAB nennt („Embedded Software Engineer"), ist damit kein Ausschluss — ein
# einzelner Werkzeugname neben einem passenden Profil ist eine Einarbeitung,
# keine falsche Rolle.
MIN_STACK_TERMS = 3


def stack_gap(profile: Profile, text: str) -> tuple[list[str], list[str]]:
    """Genannter Technologie-Stack und davon nicht im Profil belegte Begriffe.

    Rückgabe: ``(gefunden, fehlend)`` als sortierte Anzeigenamen. Beide Listen
    sind leer, wenn die Anzeige keinen der Begriffe nennt.
    """
    t = normalize(text or "")
    gefunden = [name for name, rx in _STACK_TERMS.items() if re.search(rx, t)]
    belegt = profile.evidence_text
    fehlend = [name for name in gefunden if not re.search(_STACK_TERMS[name], belegt)]
    return sorted(gefunden), sorted(fehlend)


# Studenten-/Praktikums-/Ausbildungsrollen sind für einen Vollzeit-Ingenieur
# kategorisch irrelevant — sie werden gar nicht erst angelegt (keine Unterlagen,
# kein Eintrag im Dashboard). ``\b`` verhindert False-Positives wie „internal"
# (nur „intern“) oder „Systems“ (nur „student“).
_STUDENT_ROLE_RE = re.compile(
    r"\bwerkstudent\w*"                  # Werkstudent/-in/-en
    r"|\bworking\s+student\w*"
    r"|\bpraktikant\w*|\bpraktikum\b|\bpraktika\b"
    r"|\bauszubildende\w*|\bausbildung\w*"
    r"|\bapprentice\w*"
    r"|\bintern\b|\binternship\w*"
    r"|\btrainee\w*"
    r"|\bstudent\b|\bstudents\b|\bstudentische\w*",
    re.IGNORECASE,
)


def is_student_role(title: str | None) -> bool:
    """True, wenn der Titel eine Studenten-/Praktikums-/Ausbildungsrolle ist."""
    return bool(_STUDENT_ROLE_RE.search(title or ""))


# Facharbeiter-/Technikerrollen („Techniker", „Systemtechniker",
# „Elektrotechniker", „Technician") sind keine Ingenieursstellen: sie verlangen
# in der Regel eine Ausbildung statt eines Studiums und zielen nicht auf
# Test-/Systemverantwortung. Sie werden aus dem Bestand ausgeblendet.
#
# Bewusst NICHT getroffen: „Technik", „Technische", „Technology" — das sind
# Sachgebiete, keine Berufsbezeichnungen („Technischer Projektleiter" bleibt
# eine Ingenieursrolle).
_TECHNICIAN_ROLE_RE = re.compile(
    r"\w*techniker\w*"        # Techniker, Systemtechniker, Elektrotechniker
    r"|\btechnician\w*",      # Technician, Technicians
    re.IGNORECASE,
)


def is_technician_role(title: str | None) -> bool:
    """True, wenn der Titel eine Facharbeiter-/Technikerrolle ist."""
    return bool(_TECHNICIAN_ROLE_RE.search(title or ""))


def _job_text(job: dict) -> tuple[str, str]:
    title = job.get("titel") or job.get("title") or ""
    desc = (
        job.get("beschreibung")
        or job.get("description")
        or job.get("snippet")
        or ""
    )
    return title, desc


def _as_minutes(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Bonus absteigend nach realer Pendelzeit. Die Obergrenze bleibt +10, damit die
# Score-Skala unverändert interpretierbar bleibt.
_COMMUTE_BONUS = ((30, 10), (45, 8), (60, 6), (75, 4), (90, 2))


def location_bonus_for(job: dict, location: str | None = None) -> int:
    """Standort-Bonus (0–10) aus dem **echten Pendelweg**.

    Vorher wurde nur der Ortsname verglichen („munchen" irgendwo im Feld
    ``ort``). Das bewertete Vororte falsch: Ismaning (9 min) und Gräfelfing
    (29 min) bekamen 0 Punkte, München (25 min) 10 — obwohl die Fahrzeit der
    eigentliche Maßstab ist und bereits berechnet vorliegt.

    Mehr-Standort-Angaben bekommen **keinen** Bonus, wenn ein genannter Ort
    außerhalb der Metropolregion liegt: „bundesweit, Düsseldorf, Frankfurt,
    Hamburg, München" belegt keine Nähe, und ein einzelner Stadtname in der
    Aufzählung ist kein Arbeitsort. Vorher gab der Teilstring-Treffer +10 —
    auch für Stellen, die als ``Remote`` erkannt wurden, weil „bundesweit" in
    den Remote-Markern stand. „München, Starnberg" behält den Bonus: dort
    liegen alle genannten Orte im Umkreis.
    """
    ort_raw = job.get("ort") or job.get("location") or ""
    if is_multi_location(ort_raw) and not all_locations_near_munich(ort_raw):
        return 0
    if (job.get("pendel_modus") or "") == "Remote":
        return 10
    minutes = _as_minutes(job.get("pendelzeit_min"))
    if minutes is not None:
        return next((bonus for limit, bonus in _COMMUTE_BONUS
                     if minutes <= limit), 0)

    ort = normalize(ort_raw)
    loc = normalize(location or "")
    # "munich"/"munchen" gleich behandeln (englische vs. deutsche Schreibung).
    ort, loc = ort.replace("munich", "munchen"), loc.replace("munich", "munchen")
    if loc and ort and (loc in ort or ort in loc):
        return 10
    return 0


def fit_value(job: dict) -> int:
    """Der gespeicherte Fit-Wert (0–100) einer Stelle.

    Eine Stelle kann zwei Felder tragen: ``fit_pct`` (aus dem Alt-Dashboard
    importiert) und ``score`` (vom eigenen Scoring). Beide werden hier zu *einem*
    Wert zusammengeführt, damit Filtern, Löschen und Tabelle nie auseinander-
    laufen:

    * ``fit_pct`` fehlt → ``score``.
    * ``fit_pct == 0`` bei vorhandenem ``score`` → ``score``. Null bedeutet in
      den Alt-Daten „nicht bewertet", nicht „schlechtester Wert"; 12 importierte
      Einträge hätten sonst 0 % statt ihrer echten 7–18 % gezeigt.
    * sonst ``fit_pct`` (bewusst: die Werte des Alt-Dashboards bleiben erhalten).
    """
    fit_pct = job.get("fit_pct")
    score = job.get("score")
    try:
        score_v = round(float(score)) if score is not None else 0
    except (TypeError, ValueError):
        score_v = 0
    if fit_pct is None:
        return score_v
    try:
        fit_v = round(float(fit_pct))
    except (TypeError, ValueError):
        return score_v
    if fit_v == 0 and score_v > 0:
        return score_v
    return fit_v


def score_job(profile: Profile, job: dict, location: str | None = None,
              hard_gaps: list[str] | None = None,
              weak_skills: list[str] | None = None) -> dict:
    """Berechnet Score (0–100), Kategorie und Begründung für einen Job."""
    title, desc = _job_text(job)

    # Grundkenntnisse zählen nicht als Alleinstellungsmerkmal: Sie geben keine
    # Titel-/Text-/Wortpunkte. Im Profil und in den Unterlagen bleiben sie
    # stehen — nur der Fit bewertet sie nicht.
    weak = {normalize(str(t)) for t in (weak_skills or ()) if str(t).strip()}
    title_hits = [h for h in profile.keywords_in(title) if h not in weak]
    body_hits = [h for h in profile.keywords_in(desc) if h not in weak]
    # ``words_in()`` liefert eine Menge — als sortierte Liste, damit das Feld
    # JSON-serialisierbar ist (``word_hits`` wird seit der Score-Offenlegung
    # gespeichert).
    word_hits = [w for w in sorted(profile.words_in(f"{title} {desc}")) if w not in weak]


    # Gewichtung: Titel-Treffer zählen am stärksten, gefolgt vom Anzeigentext;
    # die Inhaltswort-Überschneidungen geben den „weichen" Ausschlag. 6/4/2
    # statt 7/3/1 mildert die Titel-Dominanz und hebt Jobs im mittleren Bereich,
    # die über Text- und Wort-Überschneidungen relevant sind, aber keinen
    # wortwörtlichen Titel-Treffer haben.
    raw = 6 * len(title_hits) + 4 * len(body_hits) + 2 * len(word_hits)
    score = min(100, raw)

    location_bonus = location_bonus_for(job, location)
    score = min(100, score + location_bonus)

    # Stack-Abgleich: Nennt die Anzeige Technologien, die im Profil überhaupt
    # nicht vorkommen, und ist der Titel keine Test-/Verifikationsrolle, dann
    # ist die Keyword-Überschneidung kein Fit. Beispiel: „Lead Integration
    # Engineer (m/w/d) im Team Technology Consulting" kam über generische Wörter
    # wie „Integration", „Schnittstellen" und „Anforderungen" auf 74 %, obwohl
    # Java, Spring Boot, Kafka, SOAP und Guidewire im Profil nicht belegt sind.
    stack_found, stack_missing = stack_gap(profile, f"{title} {desc}")
    stack_cap = None
    if (len(stack_found) >= MIN_STACK_TERMS and len(stack_missing) == len(stack_found)
            and not _TEST_KERN_RE.search(normalize(title))):
        stack_cap = STACK_CAP
        score = min(score, stack_cap)

    role_cap = None
    if is_software_role(title):
        role_cap = SOFTWARE_CAP
        score = min(score, role_cap)
    elif is_development_role(title):
        role_cap = ROLE_CAP
        score = min(score, role_cap)

    # Bestätigte Lücke im Titel: Ohne C++ ist eine C++-Rolle nicht ausübbar,
    # auch wenn die übrigen Wörter passen.
    hard_gap = None
    for term in hard_gaps or ():
        rx = _HARD_GAP_RE.get(str(term).strip().lower())
        if rx and rx.search(title) and not rx.search(profile.evidence_raw):
            hard_gap = str(term)
            score = min(score, HARD_GAP_CAP)
            break

    if score >= 65:
        category = "hoch"
    elif score >= 40:
        category = "mittel"
    else:
        category = "niedrig"

    matched = sorted(set(title_hits + body_hits))
    begruendung = _reasoning(category, len(title_hits), len(body_hits), len(word_hits),
                             location_bonus, _as_minutes(job.get("pendelzeit_min")))
    if stack_cap:
        begruendung += (
            f" Deckel {stack_cap} %: kein Test-/Verifikationskern im Titel und keiner der "
            f"genannten Stack-Begriffe im Profil ({', '.join(stack_missing[:6])})."
        )
    if role_cap:
        if role_cap == SOFTWARE_CAP:
            begruendung += (
                f" Deckel {role_cap} %: Software-Entwicklungsrolle ohne Testbezug im Titel."
            )
        else:
            begruendung += (
                f" Deckel {role_cap} %: Entwickler-/Produktrolle ohne Testbezug im Titel."
            )
    if hard_gap:
        begruendung += (
            f" Deckel {HARD_GAP_CAP} %: {hard_gap} im Titel, aber nicht im Profil belegt."
        )

    return {
        "score": score,
        "fit_geschaetzt": category,
        "begruendung": begruendung,
        "matched_skills": matched,
        "title_hits": title_hits,
        "body_hits": body_hits,
        # ``word_hits`` floss immer in den Score ein (2 Punkte je Treffer),
        # wurde aber nicht gespeichert — ein Score von 84 % ließ sich damit
        # nicht mehr nachrechnen. Jetzt ist die Rechnung vollständig:
        # 6*title + 4*body + 2*word + location_bonus.
        "word_hits": word_hits,
        "location_bonus": location_bonus,
        "stack_found": stack_found,
        "stack_missing": stack_missing,
        "stack_cap": stack_cap,
        "role_cap": role_cap,
        "hard_gap": hard_gap,
    }


def _reasoning(category: str, title_hits: int, body_hits: int, word_hits: int,
               loc_bonus: int, commute: float | None = None) -> str:
    parts = []
    if title_hits:
        parts.append(f"{title_hits} Profil-Begriff(e) direkt im Stellentitel")
    if body_hits:
        parts.append(f"{body_hits} Übereinstimmung(en) im Anzeigentext")
    if word_hits:
        parts.append(f"{word_hits} weitere Inhaltswort-Überschneidungen")
    if loc_bonus:
        if commute is not None:
            parts.append(f"Pendelweg {commute:.0f} min")
        else:
            parts.append("Standort passt")
    base = "; ".join(parts) if parts else "kaum Überschneidung mit dem Profil"
    return f"Fit {category}: {base}."


def match_jobs(profile: Profile, jobs: list[dict], location: str | None = None,
               hard_gaps: list[str] | None = None,
               weak_skills: list[str] | None = None) -> list[dict]:
    """Reichert eine Jobliste um Fit-Scoring an (neue Liste, Jobs unverändert)."""
    matched = []
    for job in jobs:
        result = score_job(profile, job, location=location, hard_gaps=hard_gaps,
                           weak_skills=weak_skills)
        row = dict(job)
        row.update(result)
        matched.append(row)
    matched.sort(key=lambda j: j["score"], reverse=True)
    return matched
