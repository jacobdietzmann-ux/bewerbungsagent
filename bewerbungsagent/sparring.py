"""Wöchentliche Sparring-Liste (ADR-062): Qualität statt Masse.

Unterlagen entstehen nicht mehr automatisch. Kandidaten sind offene Stellen ab
``SPARRING_MIN_FIT`` mit passendem Rollentitel. Je Stelle zeigt die Liste, was die
Anzeige verlangt und im Profil nicht belegt ist. Im Sparring wird geklärt, ob ein
Skill tatsächlich vorhanden ist (dann ins Profil) und ob beworben wird
(dann ``agent.py generate --ids N`` mit getailertem Lebenslauf).

Deterministisch und ohne Netzwerk: nur Bestand und Profil.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from .matching import fit_value, has_role_signal
from .profile import Profile, normalize

SPARRING_MIN_FIT = 71
_ABGESCHLOSSEN = ("sent", "followup", "interview", "rejected")

# Fachbegriffe in Anzeigen: Akronyme (CAN, UDS, ASPICE), Wörter mit Ziffern
# (ISO 26262, DO-178C) oder Binnen-Großbuchstaben (dSPACE, CANoe).
_BEGRIFF_RE = re.compile(
    r"\b(?:[A-Z]{2,}[A-Za-z0-9+/-]*|[A-Za-z]+[0-9][A-Za-z0-9-]*|[a-z]+[A-Z][A-Za-z]+)\b")
# Häufige Großschreibungen ohne fachlichen Gehalt.
_KEIN_BEGRIFF = frozenset({
    "GMBH", "AG", "SE", "KG", "CO", "UG", "MBH", "DE", "EN", "IT", "HR", "CV", "PDF", "FAQ",
    "UND", "ODER", "WIR", "SIE", "DU", "IHR", "THE", "AND", "OR", "WE", "YOU", "M", "W", "D",
    "MWD", "WMD", "MFD", "FMD", "ALL", "USA", "EU", "DACH", "CEO", "CTO", "KPI", "B2B", "B2C",
    "XL", "EUR", "TV", "CHF", "BMW", "AUDI", "IAV", "NTNU", "TU",
    # Hervorhebungen in englischen Anzeigen („YOUR PROFILE", „THIS IS US")
    "YOUR", "PROFILE", "THIS", "BONUS", "LOOK", "FORWARD", "WHAT", "WHO", "JOIN", "APPLY",
    "NOW", "TEAM", "JOB", "OFFER", "ABOUT", "BENEFITS", "TASKS", "US",
})


def ist_kandidat(app: dict, min_fit: int = SPARRING_MIN_FIT) -> bool:
    """Offene, sichtbare Stelle ab ``min_fit`` mit passendem Rollentitel."""
    return (not app.get("deleted")
            and app.get("status") not in _ABGESCHLOSSEN
            and app.get("verfuegbar") is not False
            and fit_value(app) >= min_fit
            and has_role_signal(app.get("titel")))


def fehlende_begriffe(app: dict, profile: Profile, limit: int = 12) -> list[str]:
    """Fachbegriffe der Anzeige, die im Profil nicht belegt sind (häufigste zuerst)."""
    beleg = profile.evidence_text
    text = f"{app.get('titel') or ''}\n{app.get('beschreibung') or ''}"
    # Wörter, die im Text auch klein oder normal geschrieben vorkommen, sind
    # Hervorhebungen („YOUR PROFILE"), keine Fachbegriffe; ebenso der Firmenname.
    normale_woerter = {w.lower() for w in re.findall(r"\b[A-Za-zÄÖÜäöüß]+\b", text)
                       if not w.isupper()}
    firma = {w.lower() for w in re.findall(r"\w+", app.get("firma") or "")}
    zaehler: dict[str, int] = {}
    for treffer in _BEGRIFF_RE.findall(text):
        begriff = treffer.strip("-/")
        if len(begriff) < 2 or begriff.upper() in _KEIN_BEGRIFF:
            continue
        if begriff.lower() in firma:
            continue
        if (begriff.isupper() and begriff.isalpha() and len(begriff) >= 4
                and begriff.lower() in normale_woerter):
            continue
        norm = normalize(begriff)
        if not norm or norm in beleg:
            continue
        zaehler[begriff] = zaehler.get(begriff, 0) + 1
    # Stack-Lücken und harte Lücken aus der Bewertung zuerst.
    vorn = [str(s) for s in (app.get("stack_missing") or [])]
    if app.get("hard_gap"):
        vorn.append(str(app["hard_gap"]))
    rest = sorted(zaehler, key=lambda b: (-zaehler[b], b.lower()))
    out: list[str] = []
    for b in [*vorn, *rest]:
        if b not in out:
            out.append(b)
    return out[:limit]


def kandidaten(apps: Iterable[dict], min_fit: int = SPARRING_MIN_FIT) -> list[dict]:
    """Sparring-Kandidaten, bester Fit zuerst."""
    return sorted((a for a in apps if ist_kandidat(a, min_fit)), key=fit_value, reverse=True)


def als_markdown(liste: list[dict], profile: Profile, heute: date | None = None) -> str:
    """Liste für das wöchentliche Sparring im Chat (``data/sparring.md``)."""
    heute = heute or date.today()
    zeilen = [f"# Sparring-Liste {heute:%d.%m.%Y}", "",
              f"{len(liste)} offene Stelle(n) ab {SPARRING_MIN_FIT} % mit passendem Rollentitel.",
              "Je Stelle: Fehlt ein Skill wirklich, oder steht er nur nicht im Profil?",
              "Freigabe: `agent.py generate --ids <ID>` (mit `Lebenslauf-Tailoring.json`).", ""]
    for a in liste:
        stand = "Unterlagen vorhanden" if a.get("dokumente") else "offen"
        pendel = f", {a['pendelzeit_min']} min" if a.get("pendelzeit_min") else ""
        zeilen.append(f"## {fit_value(a)} % · {a.get('firma') or '?'} — {a.get('titel') or '?'}")
        zeilen.append(f"ID {a.get('id')} · {stand}{pendel} · {a.get('url') or 'ohne Link'}")
        treffer = ", ".join((a.get("matched_skills") or [])[:10]) or "–"
        zeilen.append(f"- Profil-Treffer: {treffer}")
        fehlend = ", ".join(fehlende_begriffe(a, profile)) or "–"
        zeilen.append(f"- Nicht im Profil: {fehlend}")
        zeilen.append("")
    return "\n".join(zeilen)
