"""Fit-Scoring: vergleicht eine Stellenanzeige mit dem Skill-Profil.

Der Score ist bewusst transparent und deterministisch, damit der Bewerber die
Einschätzung nachvollziehen und ggf. manuell nachjustieren kann.
"""

from __future__ import annotations

import re

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
    r"|\bqualifikation\w*|\bqualifizierung\w*|\bqa\b|\bqualitaetssicherung\w*"
    r"|\bpruef\w*|\bpruf\w*"          # Prüfstands-, Prüffeld-, Prüfingenieur
    r"|\bmechatronik\w*|\belektronik\w*|\belektrotechnik\w*"
    r"|\bintegration\w*"
)


def has_role_signal(title: str | None) -> bool:
    """True, wenn der Titel auf eine Test-/Absicherungsrolle hindeutet."""
    return bool(_ROLE_SIGNAL_RE.search(normalize(title or "")))


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

    Ohne Pendeldaten greift weiterhin der Ortsvergleich, damit eine fehlende
    Route niemanden benachteiligt.
    """
    if (job.get("pendel_modus") or "") == "Remote":
        return 10
    minutes = _as_minutes(job.get("pendelzeit_min"))
    if minutes is not None:
        return next((bonus for limit, bonus in _COMMUTE_BONUS
                     if minutes <= limit), 0)

    ort = normalize(job.get("ort") or job.get("location") or "")
    loc = normalize(location or "")
    # "munich"/"munchen" gleich behandeln (englische vs. deutsche Schreibung).
    ort, loc = ort.replace("munich", "munchen"), loc.replace("munich", "munchen")
    if loc and ort and (loc in ort or ort in loc):
        return 10
    return 0


def score_job(profile: Profile, job: dict, location: str | None = None) -> dict:
    """Berechnet Score (0–100), Kategorie und Begründung für einen Job."""
    title, desc = _job_text(job)

    title_hits = profile.keywords_in(title)
    body_hits = profile.keywords_in(desc)
    word_hits = profile.words_in(f"{title} {desc}")

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
