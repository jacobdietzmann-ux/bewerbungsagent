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


def score_job(profile: Profile, job: dict, location: str | None = None) -> dict:
    """Berechnet Score (0–100), Kategorie und Begründung für einen Job."""
    title, desc = _job_text(job)

    title_hits = profile.keywords_in(title)
    body_hits = profile.keywords_in(desc)
    # ``words_in()`` liefert eine Menge — als sortierte Liste, damit das Feld
    # JSON-serialisierbar ist (``word_hits`` wird seit der Score-Offenlegung
    # gespeichert).
    word_hits = sorted(profile.words_in(f"{title} {desc}"))


    # Gewichtung: Titel-Treffer zählen am stärksten, gefolgt vom Anzeigentext;
    # die Inhaltswort-Überschneidungen geben den „weichen" Ausschlag. 6/4/2
    # statt 7/3/1 mildert die Titel-Dominanz und hebt Jobs im mittleren Bereich,
    # die über Text- und Wort-Überschneidungen relevant sind, aber keinen
    # wortwörtlichen Titel-Treffer haben.
    raw = 6 * len(title_hits) + 4 * len(body_hits) + 2 * len(word_hits)
    score = min(100, raw)

    location_bonus = location_bonus_for(job, location)
    score = min(100, score + location_bonus)

    if score >= 65:
        category = "hoch"
    elif score >= 40:
        category = "mittel"
    else:
        category = "niedrig"

    matched = sorted(set(title_hits + body_hits))
    begruendung = _reasoning(category, len(title_hits), len(body_hits), len(word_hits),
                             location_bonus, _as_minutes(job.get("pendelzeit_min")))

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


def match_jobs(profile: Profile, jobs: list[dict], location: str | None = None) -> list[dict]:
    """Reichert eine Jobliste um Fit-Scoring an (neue Liste, Jobs unverändert)."""
    matched = []
    for job in jobs:
        result = score_job(profile, job, location=location)
        row = dict(job)
        row.update(result)
        matched.append(row)
    matched.sort(key=lambda j: j["score"], reverse=True)
    return matched
