"""Fit-Scoring: vergleicht eine Stellenanzeige mit dem Skill-Profil.

Der Score ist bewusst transparent und deterministisch, damit der Bewerber die
Einschätzung nachvollziehen und ggf. manuell nachjustieren kann.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    r"|\bstudent\b|\bstudents\b|\bstudentische\w*"
    # Abschluss-/Doktorarbeiten: „Master Thesis", „Masterthesis",
    # „Masterarbeit", „Abschlussarbeit", „PhD Thesis", „Doktorand".
    r"|\bmaster\s*-?\s*thesis\b|\bbachelor\s*-?\s*thesis\b|\bthesis\b"
    r"|\w*abschlussarbeit\w*|\bmasterarbeit\w*|\bbachelorarbeit\w*"
    r"|\bdoktorand\w*|\bph\.?\s?d\b",
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
    r"|\btechnician\w*"       # Technician, Technicians
    # Ausbildungsberufe: „Mechatroniker", „Kfz-Mechatroniker", „Elektroniker",
    # „Fahrzeugbaumechaniker", „Monteur". „Elektronikentwickler" bleibt frei
    # (kein „elektroniker" im Wort).
    r"|\w*mechatroniker\w*|\belektroniker\w*|\w*mechaniker\w*"
    r"|\bmonteur\w*|\bfacharbeiter\w*",
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


# --------------------------------------------------------------------------
# Domänen-Vorfilter bei der Suche (vormals ``triage.py``)
# --------------------------------------------------------------------------
# Entscheidet anhand von Titel und Firma, ohne die Anzeige zu laden, in drei
# Klassen: ``relevant`` (klares Technik-Signal), ``reject`` (eindeutig andere
# Domäne: Vertrieb, Pflege, Fahrer …) und ``unsure`` (der Fit entscheidet). Bewusst
# breiter als ``has_role_signal``: Von 230 Bewerbungen hatten 58 kein Rollensignal
# im Titel (Systemingenieur, Requirements Engineer), wären mit der engen Prüfung
# also schon bei der Suche verloren gegangen (gemessen am 11.11.2026).

RELEVANT = "relevant"
UNSURE = "unsure"
REJECT = "reject"

# --- Technische Domäne: alles, was eine Ingenieursrolle belegen kann ---------
# Bewusst breit: ein Treffer hier heißt nur „technisch möglich", nicht „passt".
_TECH_SIGNAL = re.compile(
    r"\w*engineer\w*|\w*ingenieur\w*"
    r"|\bentwickl\w*|\bdeveloper\w*|\bprogrammier\w*|\barchitekt\w*|\barchitect\w*"
    r"|\bsoftware\w*|\bsystem\w*|\bsystems\b"
    r"|\btest\w*|\bvalidier\w*|\bverifik\w*|\bverif\w*|\babsicherung\w*|\berprobung\w*"
    r"|\bqualitaet\w*|\bqualitat\w*|\bquality\b|\bsotif\b|\bsafety\b|\bsecurity\b"
    r"|\bcyber\w*|\bintegrat\w*|\bautomatisier\w*|\bautomation\b"
    r"|\bmechatronik\w*|\belektro\w*|\belectr\w*|\bhardware\b|\bembedded\b"
    r"|\bfirmware\b|\bdevops\b|\bcloud\b|\bdata\b|\bki\b|\bai\b|\bml\b"
    r"|\brequirements?\b|\banforderung\w*|\btechni\w*|\btech\b"
    r"|\bphysik\w*|\bmaschinenbau\b|\binformatik\w*|\bmikrocontroller\w*"
    r"|\bpruef\w*|\bpruf\w*|\bmesstechnik\w*|\bregelungstechnik\w*"
    # Automotive-/Test-Fachbegriffe. Ohne sie fiel „SDV Expert ADAS/AD
    # Homologation" durch, obwohl es eine Kernrolle ist.
    r"|\badas\b|\bad\b\b|\bautonom\w*|\bautomatisiertes\s+fahren\b|\bhomologation\w*"
    r"|\bhil\b|\bxil\b|\bsil\b|\becu\w*|\bsteuergeraet\w*|\bsteuergerat\w*"
    r"|\bautosar\b|\bflexray\b|\buds\b|\bdspace\b|\bcan-?fd\b|\blin-?bus\b"
    r"|\bfahrzeugtechnik\w*|\bkraftfahrzeug\w*|\bautomotive\b|\bsdv\b"
    r"|\bota\b|\bdiagnose\w*|\bflashtool\w*|\btrace\w*|\bmessdaten\w*",
    re.IGNORECASE,
)

# Führung in technischem Kontext zählt ebenfalls zur Domäne.
_LEAD_SIGNAL = re.compile(
    r"\bmanager\w*|\blead\b|\bteamlead\w*|\bteamleitung\w*|\bleitung\w*"
    r"|\bhead of\b|\bcoordinator\w*|\bkoordinator\w*|\bconsultant\w*"
    r"|\bspezialist\w*|\bspecialist\w*|\bexpert\w*",
    re.IGNORECASE,
)

# --- Eindeutig andere Domäne: nie eine Ingenieursrolle ----------------------
# Diese Signale lehnen ab, sofern kein technisches Signal dagegensteht.
_NON_TECH_SIGNAL = re.compile(
    # Vertrieb / Verkauf
    r"\bvertrieb\w*|\bsales\b|\bverkauf\w*|\bau[sß]sendienst\w*|\bakquis\w*"
    r"|\baccount\s+manager\w*|\bgebiet\w*"
    # Marketing / Kommunikation / E-Commerce
    r"|\bmarketing\w*|\bonline[- ]?marketing\b|\be-?commerce\b|\bamazon\b"
    r"|\bseo\b|\bcontent\w*|\bsocial\s+media\b|\bkommunikation\w*"
    # Finanzen / Rechnungswesen / Controlling
    r"|\bbuchhalt\w*|\bcontrolling\b|\bcontroller\w*|\bfinanz\w*|\bfinance\b"
    r"|\bsteuer\w*|\baccounting\b|\bpreispruefer\w*|\bpayment\w*|\btreasury\b"
    # Personal / Recht / Verwaltung
    r"|\bpersonalreferent\w*|\brecruit\w*|\bhuman\s+resources\b|\bhr\b"
    r"|\bjurist\w*|\blegal\b|\bsteuerberat\w*|\bsachbearbeit\w*|\bverwaltung\w*"
    r"|\bsekret\w*|\bassistenz\w*|\bempfang\w*|\bkaufm\w*"
    # Compliance / Exportkontrolle (Recht, nicht Technik)
    r"|\bexport\s*control\b|\bcompliance\s+manager\b"
    # Einkauf / Beschaffung
    r"|\beinkauf\w*|\bpurchas\w*|\bbeschaffung\w*|\bprocurement\b"
    # Pharmazie / GMP-Qualifizierung (andere Domäne als Softwaretest)
    r"|\bgmp\b|\bpharma\w*|\bpharmazeutisch\w*|\bformulierungsentwicklung\w*"
    # IT-Betrieb / Anwendungsbetreuung (kein Engineering)
    r"|\bit[- ]service\b|\bit[- ]support\b|\banwendungsbetreu\w*"
    # Prüfungswesen im Bildungsbereich („Prüfung“ = Examen, nicht Test)
    r"|\bprüfungskoordinator\w*|\bpruefungskoordinator\w*|\btelc\b"
    # Gastronomie / Hotellerie
    r"|\bkoch\w*|\bcommis\b|\bchef\s+de\b|\bpartie\b|\bservicekraft\w*"
    r"|\brestaurant\w*|\bhotel\w*|\bbarista\w*|\bcuisine\b"
    # Fahren / Transport / Zustellung
    # ``testfahrer`` ist ein Fahrerjob, nicht eine Testrolle — während
    # „Fahrerassistenzsysteme" (ohne Wortgrenze davor) echte Technik ist.
    r"|\btaxi\w*|\bchauffeur\w*|\bkurier\w*|\btestfahrer\w*|\bfahrer\b|\blieferant\w*"
    r"|\bzustell\w*|\bbusfahrer\w*|\bberufskraftfahrer\w*"
    # Pflege / Soziales / Erziehung
    # ``\w*pfleg`` statt ``\bpfleg``: deutsche Komposita kleben den Stamm an ein
    # Bestimmungsvort („Altenpfleger", „Krankenpfleger") — eine Wortgrenze davor
    # würde sie übersehen. Dieselbe Falle wie bei ``has_role_signal``.
    r"|\w*pfleg\w*|\berzieher\w*|\bsozial\w*|\btherap\w*"
    # Handel / Filiale / Lager / Reinigung
    r"|\bfilial\w*|\bkassier\w*|\blager\w*|\blogistik\w*"
    r"|\breinigung\w*|\bhausmeister\w*|\bsecurity\s+guard\b"
    # Handwerk / Fertigung (angelernt)
    # ``\w*`` vor dem Stamm wegen Komposita: „Industriemechaniker",
    # „Kfz-Monteur", „Anlagenmechaniker".
    r"|\w*mechaniker\w*|\w*monteur\w*|\w*schlosser\w*|\bschweisser\w*"
    r"|\bkarosserie\w*|\bproduktionsmitarbeiter\w*|\bfertigungshelfer\w*"
    r"|\bbauarbeiter\w*"
    # Immobilien / Versicherung / Bank
    r"|\bimmobilien\w*|\bversicherung\w*|\bfilialleiter\w*|\bbank\w*",
    re.IGNORECASE,
)


# --- Rollen-Nomen, die eine *nicht-technische Tätigkeit* benennen -----------
# Diese Begriffe enthalten oft ein technisch klingendes Wort („Test**fahrer**",
# „**Test**fahrer"), bezeichnen aber den Job selbst — nicht das Produkt. Sie
# werden deshalb unabhängig vom übrigen Tech-Signal abgelehnt.
#
# Bewusst klein gehalten: nur Komposita, die eindeutig eine andere Tätigkeit
# benennen. „Fahrerassistenz" steht hier absichtlich NICHT — das ist Technik.
_HARD_REJECT_ROLE = re.compile(
    r"\btestfahrer\w*|\bprobefahrer\w*|\büberführungsfahrer\w*"
    r"|\bberufskraftfahrer\w*|\bbusfahrer\w*|\bkraftfahrer\w*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Verdict:
    """Ergebnis der Triage: Klasse + nachvollziehbarer Grund."""

    label: str
    reason: str

    @property
    def is_reject(self) -> bool:
        return self.label == REJECT


def _hit(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(0) if m else ""


def _match_override(text: str, patterns: list[str] | None) -> str:
    """Erster passender Nutzer-Eintrag aus einer Liste (Substring, ohne Groß/Klein).

    Die Einträge sind bewusst *keine* Regex: der Nutzer trägt Titel-Fragmente ein
    („Projektleitung Versicherungs-Software"), keine Muster. Das ist robuster
    gegen Tippfehler und bleibt lesbar.

    Ein Eintrag darf den Firmennamen mit ``|`` abgrenzen
    (``"Teamleitung | VITES"``). Nötig, weil ein generischer Titel wie
    „Teamleitung" sonst zu breit wirkt: ohne Firmenbezug würde er auch
    „Teamleitung Vertrieb" behalten und damit die Vertriebs-Regel aushebeln.
    """
    if not patterns:
        return ""
    low = text.lower()
    for p in patterns:
        raw = str(p).strip()
        if not raw:
            continue
        # ``A | B`` = alle Teile müssen vorkommen (Titel UND Firma).
        parts = [part.strip().lower() for part in raw.split("|") if part.strip()]
        if parts and all(part in low for part in parts):
            return raw
    return ""


def triage_classify(title: str | None, firma: str | None = None,
             beschreibung: str | None = None,
             *, reject_patterns: list[str] | None = None,
             keep_patterns: list[str] | None = None) -> Verdict:
    """Ordnet eine Stelle ein: ``relevant``, ``unsure`` oder ``reject``.

    Regelwerk (in dieser Reihenfolge):

    0. Nutzerentscheidung (``reject_patterns``/``keep_patterns``) — gewinnt immer.
    1. Studenten-/Praktikumsrolle → ``reject`` (nie eine Vollzeitstelle).
    2. Fahrertätigkeit mit technisch klingendem Namen („Testfahrer") → ``reject``.
    3. Eindeutig andere Domäne **ohne** technisches Signal → ``reject``.
    4. Technisches Signal **und** andere Domäne → ``unsure`` (z. B. „Sales
       Engineer"): technisch möglich, aber die Rolle muss der Mensch beurteilen.
    5. Technisches Signal → ``relevant``.
    6. Sonst → ``unsure``.

    ``beschreibung`` wird nur für die letzte Stufe herangezogen: nennt ein
    unklarer Titel im Text doch Technik, wird daraus ``relevant``. So fällt die
    teure Entscheidung erst, wenn der Titel allein nicht reicht.

    ``reject_patterns``/``keep_patterns`` kommen aus ``search.triage_reject`` /
    ``triage_keep`` der Konfiguration. Sie existieren, weil ein Regelwerk die
    Grenze nicht prinzipiell ziehen kann: „Sales Manager *Embedded*" nennt
    Technik, meint aber Vertrieb. Statt dafür Wörter anzuhäufen (Overfitting),
    entscheidet der Nutzer den Restfall — dauerhaft und nachvollziehbar.
    """
    t = (title or "").strip()
    if not t:
        return Verdict(UNSURE, "Kein Titel")

    # 0) Nutzerentscheidung. ``keep`` gewinnt gegen ``reject``, damit eine
    #    versehentlich zu breite Reject-Regel eine echte Stelle nie verliert.
    #    Geprüft wird Titel **und** Firma, damit ein Eintrag wie
    #    „Teamleitung | VITES" genau eine Stelle trifft, nicht jede Teamleitung.
    haystack = f"{t} · {firma or ''}"
    keep_hit = _match_override(haystack, keep_patterns)
    if keep_hit:
        return Verdict(RELEVANT, f"Nutzerentscheidung (behalten): {keep_hit}")
    reject_hit = _match_override(haystack, reject_patterns)
    if reject_hit:
        return Verdict(REJECT, f"Nutzerentscheidung (verwerfen): {reject_hit}")

    if is_student_role(t):
        return Verdict(REJECT, "Studenten-/Praktikumsstelle")

    # Rollen-Nomen mit technisch klingendem Bestandteil („Testfahrer") müssen
    # vor der Tech-Prüfung greifen — sonst liest die Regel das „Test" als Signal.
    hard = _hit(_HARD_REJECT_ROLE, t)
    if hard:
        return Verdict(REJECT, f"Fahrertätigkeit: {hard}")

    tech = _hit(_TECH_SIGNAL, t)
    lead = _hit(_LEAD_SIGNAL, t)
    non_tech = _hit(_NON_TECH_SIGNAL, t)

    # Eine andere Domäne wird nur durch *fachliches* Technik-Signal entschärft —
    # nicht durch ein Führungswort. Sonst rutschte „Head of International Sales"
    # als „unsure" durch, obwohl es eindeutig Vertrieb ist.
    if non_tech and not tech:
        return Verdict(REJECT, f"Andere Domäne: {non_tech}")
    if non_tech and tech:
        # „Sales Engineer", „Finance Software Manager": nicht automatisch weg.
        return Verdict(UNSURE, f"Technisch, aber {non_tech}")
    if tech:
        return Verdict(RELEVANT, f"Technisches Signal: {tech}")
    if lead:
        return Verdict(UNSURE, f"Führungsrolle ohne klares Technik-Signal: {lead}")

    # Firma kann das Signal liefern (z. B. „Testmanager" ohne Tech-Wort,
    # aber Anbieter ist ein Testdienstleister).
    if firma and _hit(_TECH_SIGNAL, firma):
        return Verdict(RELEVANT, "Technisches Signal in der Firma")

    if beschreibung and _hit(_TECH_SIGNAL, beschreibung):
        return Verdict(RELEVANT, "Technisches Signal in der Beschreibung")
    return Verdict(UNSURE, "Kein eindeutiges Signal")


def triage_verdict(job: dict, config=None) -> Verdict:
    """Bequemer Aufruf für einen Job-Datensatz.

    ``config`` (optional) liefert ``search.triage_reject`` / ``triage_keep``.
    """
    reject, keep = _overrides_from_config(config)
    return triage_classify(job.get("titel"), job.get("firma"), job.get("beschreibung"),
                    reject_patterns=reject, keep_patterns=keep)


def _overrides_from_config(config) -> tuple[list[str] | None, list[str] | None]:
    """Liest die Nutzerentscheidungen aus ``search.triage_reject``/``triage_keep``."""
    data = getattr(config, "data", None)
    if not isinstance(data, dict):
        return None, None
    search = data.get("search") or {}
    reject = search.get("triage_reject")
    keep = search.get("triage_keep")
    return (reject if isinstance(reject, list) else None,
            keep if isinstance(keep, list) else None)


def triage_split(jobs: list[dict], config=None) -> tuple[list[dict], list[dict]]:
    """Teilt Jobs in (behalten, verworfen) — nur ``reject`` fliegt raus.

    ``unsure`` bleibt bewusst im Bestand: der Fit entscheidet, nicht der Titel.
    """
    kept: list[dict] = []
    rejected: list[dict] = []
    for job in jobs:
        (rejected if triage_verdict(job, config).is_reject else kept).append(job)
    return kept, rejected
