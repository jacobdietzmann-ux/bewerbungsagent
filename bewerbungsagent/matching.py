"""Fit-Scoring: vergleicht eine Stellenanzeige mit dem Skill-Profil.

Der Score ist bewusst transparent und deterministisch, damit der Bewerber die
Einschätzung nachvollziehen und ggf. manuell nachjustieren kann.
"""

from __future__ import annotations

from .profile import Profile, normalize


def _job_text(job: dict) -> tuple[str, str]:
    title = job.get("titel") or job.get("title") or ""
    desc = (
        job.get("beschreibung")
        or job.get("description")
        or job.get("snippet")
        or ""
    )
    return title, desc


def score_job(profile: Profile, job: dict, location: str | None = None) -> dict:
    """Berechnet Score (0–100), Kategorie und Begründung für einen Job."""
    title, desc = _job_text(job)

    title_hits = profile.keywords_in(title)
    body_hits = profile.keywords_in(desc)
    word_hits = profile.words_in(f"{title} {desc}")

    # Phrasen-Treffer im Titel zählen stärker als im Beschreibungstext.
    raw = 7 * len(title_hits) + 3 * len(body_hits) + 1 * len(word_hits)
    score = min(100, raw)

    # Standort-Bonus (max +10), wenn der Ort zum Suchort passt.
    location_bonus = 0
    ort = normalize(job.get("ort") or job.get("location") or "")
    loc = normalize(location or "")
    # "munich"/"munchen" gleich behandeln (englische vs. deutsche Schreibung).
    ort = ort.replace("munich", "munchen")
    loc = loc.replace("munich", "munchen")
    if loc and ort:
        if loc in ort or ort in loc:
            location_bonus = 10
        else:
            location_bonus = 0
    score = min(100, score + location_bonus)

    if score >= 65:
        category = "hoch"
    elif score >= 40:
        category = "mittel"
    else:
        category = "niedrig"

    matched = sorted(set(title_hits + body_hits))
    begruendung = _reasoning(category, len(title_hits), len(body_hits), len(word_hits), location_bonus)

    return {
        "score": score,
        "fit_geschaetzt": category,
        "begruendung": begruendung,
        "matched_skills": matched,
        "title_hits": title_hits,
        "body_hits": body_hits,
        "location_bonus": location_bonus,
    }


def _reasoning(category: str, title_hits: int, body_hits: int, word_hits: int, loc_bonus: int) -> str:
    parts = []
    if title_hits:
        parts.append(f"{title_hits} Profil-Begriff(e) direkt im Stellentitel")
    if body_hits:
        parts.append(f"{body_hits} Übereinstimmung(en) im Anzeigentext")
    if word_hits:
        parts.append(f"{word_hits} weitere Inhaltswort-Überschneidungen")
    if loc_bonus:
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
