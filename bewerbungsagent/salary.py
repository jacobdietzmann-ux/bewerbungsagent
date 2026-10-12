"""Gehalts-Schätzung für Stellen, bei denen keine Zahlen veröffentlicht sind.

Regelbasierte Schätzung (kein Netzwerkzugriff): aus Stellentitel (Rolle,
Seniorität) + Branche + Standort wird eine typische Bruttojahres-Spanne in
Deutschland (Stand ~2025) abgeleitet. Der Wert ist bewusst als *Schätzung*
gekennzeichnet und dient der Vorauswahl, nicht als verbindliche Angabe.
"""

from __future__ import annotations

from .profile import normalize

# Reihenfolge = Priorität (spezifisch vor allgemein). Werte = (min, max) in T€.
_ROLE_RANGES: list[tuple[list[str], tuple[int, int]]] = [
    (["software architect", "system architect", "solution architect", "architekt"], (80, 95)),
    (["gruppenleiter", "teamleiter", "abteilungsleiter", "team lead", "head of"], (80, 100)),
    (["principal", "lead expert", "lead engineer"], (75, 90)),
    (["test manager", "testmanager", "test lead", "leiter test"], (72, 88)),
    (["test automation engineer", "testautomatisierer", "test automation", "testautomation",
      "test automatisierung"], (62, 78)),
    (["hil test", "hardware-in-the-loop", "hardware in the loop", "hil engineer"], (60, 76)),
    (["testingenieur", "test ingenieur", "test-ingenieur", "test engineer", "testengineer"], (58, 72)),
    (["systemingenieur", "systems engineer", "system engineer", "systemingenieur",
      "system engineer"], (65, 80)),
    (["requirements engineer", "requirement engineer", "requirements engineerin",
      "anforderungsmanager", "anforderungsmanagement"], (60, 75)),
    (["qualitaetsingenieur", "qualitätsingenieur", "quality engineer", "qa engineer"], (55, 70)),
    (["verification engineer", "verifikations", "verification", "validierung",
      "validation engineer"], (60, 75)),
    (["versuchsingenieur", "pruefeldingenieur", "prüfingenieur", "testkoordinator",
      "versuch"], (60, 75)),
    (["simulation"], (65, 80)),
    (["embedded"], (60, 75)),
    (["business analyst", "it business analyst"], (60, 75)),
    (["support engineer", "support"], (50, 65)),
    (["entwicklungsingenieur", "development engineer", "entwickler"], (58, 72)),
    (["projektmanager", "project manager"], (70, 85)),
    (["software"], (60, 76)),
]

# Standorte, die eindeutig *außerhalb* der Münchener Metropolregion liegen und
# deshalb einen kleinen Abschlag erhalten (München zahlt tendenziell mehr).
_AWAY_CITIES = {
    "berlin", "dresden", "hamburg", "frankfurt", "koeln", "koln", "essen",
    "duesseldorf", "dusseldorf", "karlsruhe", "kassel", "mannheim", "leipzig",
    "stuttgart", "hannover", "nuernberg", "nurnberg", "erlangen", "bremen",
    "dortmund", "bochum", "bonn", "bielefeld", "mainz", "wiesbaden", "aachen",
    "braunschweig", "wolfsburg", "ingolstadt", "regensburg", "ulm", "freising",
    "landshut", "augsburg", "gilching", "weilheim", "pforzheim", "heidelberg",
    "koethen", "duisburg",
}

_MUNICH_METRO = {
    "muenchen", "munchen", "munich", "garching", "ismaning", "ottobrunn",
    "unterschleissheim", "neubiberg", "unterfoehring", "taufkirchen",
    "putzbrunn", "kirchheim", "feldkirchen", "haar", "oberhaching", "dornach",
    "aschheim", "grasbrunn", "hohenbrunn", "poing", "vaterstetten", "planegg",
    "gruenwald", "germering", "fuerstenfeldbruck", "dachau", "starnberg",
}

_SENIOR_UP = {"senior", "lead", "principal", "architect", "erfahren", "expert", "gruppenleiter", "teamleiter"}
_SENIOR_DOWN = {"junior", "trainee", "werkstudent", "student", "einsteiger", "berufseinsteiger"}


# Keywords bei Modul-Import normalisieren, damit Umlaute/Schreibvarianten
# („qualitätsingenieur" ↔ „qualitatsingenieur") zuverlässig matchen.
_ROLE_NORM: list[tuple[list[str], tuple[int, int]]] = [
    ([normalize(k) for k in keys], rng) for keys, rng in _ROLE_RANGES
]


def estimate_salary(job: dict) -> str:
    """Liefert eine typische Bruttospanne als String, z. B. ``62–78 T€``."""
    text = normalize(f"{job.get('titel', '')} {job.get('firma', '')}")
    ort = normalize(job.get("ort", "") or "")

    lo, hi = 60, 76  # Default: Ingenieur-Mittelband

    for keywords, rng in _ROLE_NORM:
        if any(k in text for k in keywords):
            lo, hi = rng
            break

    # Seniorität / Titelzusätze.
    if any(w in text for w in _SENIOR_DOWN):
        lo, hi = lo - 10, hi - 10
    elif any(w in text for w in _SENIOR_UP):
        lo, hi = lo + 6, hi + 6

    # Standort: Münchener Raum zahlt mehr, entfernte Großstädte etwas weniger.
    if any(c in ort for c in _MUNICH_METRO):
        lo, hi = lo + 2, hi + 2
    elif any(c in ort for c in _AWAY_CITIES):
        lo, hi = lo - 2, hi - 2

    lo = max(40, lo)
    hi = max(lo + 6, hi)
    return f"{lo}–{hi} T€"


def _has_real_salary(value: str) -> bool:
    """True, wenn der Wert eine echte Gehaltsangabe ist (kein Platzhalter)."""
    s = (value or "").strip().lower()
    if not s:
        return False
    if s in ("k. a.", "k.a.", "-", "–", "keine angabe", "keine angaben"):
        return False
    return not ("nicht angezeigt" in s or "keine angabe" in s)


def enrich_salary(apps: list[dict]) -> dict:
    """Setzt ``gehalt`` + ``gehalt_quelle`` für alle Stellen ohne eigene Angabe."""
    estimated = 0
    kept = 0
    for a in apps:
        if _has_real_salary(a.get("gehalt")):
            a.setdefault("gehalt_quelle", "Anzeige")
            kept += 1
            continue
        a["gehalt"] = estimate_salary(a)
        a["gehalt_quelle"] = "Schätzung"
        estimated += 1
    return {"estimated": estimated, "kept": kept}
