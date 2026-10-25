"""Mehrdimensionale Bewertung einer Stellenanzeige (P0a aus dem Review-Plan).

Warum ein eigenes Modul: Der Keyword-Fit (``matching.fit_value``) beantwortet
nur „wie viel Profil-Vokabular steht in der Anzeige“. Ein Fit von 80 % kann
trotzdem eine unpassende Stelle sein — falsches Verantwortungsniveau, zu
niedriges Gehalt, weiter Pendelweg. Dieses Modul zerlegt die Bewertung in
sieben unabhängige Dimensionen mit **Belegen** pro Dimension.

Wichtig — in dieser Ausbaustufe ist die Bewertung **berichtend**:

* ``score``/``fit_value`` bleiben unverändert (Baseline AUC 0,715 auf den
  harten Labels). Die Dimensionen laufen im Dashboard/DB mit, entscheiden aber
  nicht über den Fit (AGENTS.md: „Neue Methode → erst gegen Baseline messen“).
* Hart ist nur die **K.O.-Liste**: Sie ist nicht durch hohe Teilwerte
  kompensierbar. Sie blockiert in dieser Stufe ausschließlich die
  *automatische* Unterlagenerzeugung, nicht die Anzeige im Dashboard — eine
  falsch gesetzte K.O.-Schwelle soll keine Stellen verschwinden lassen.

Die Gewichte sind Startwerte aus dem Review (Hypothese, keine Messung).
"""

from __future__ import annotations

import re

from .industry import classify_industry
from .profile import Profile, normalize

# Startgewichte aus dem Review (30/20/15/10/10/10/5). Sie werden erst zur
# Bewertung, wenn die Dimensionen die Keyword-Baseline auf den harten Labels
# schlagen (siehe eval/run_dimensions_eval.py).
DEFAULT_WEIGHTS: dict[str, float] = {
    "kompetenz": 0.30,
    "aufgaben": 0.20,
    "senioritaet": 0.15,
    "technologie": 0.10,
    "gehalt": 0.10,
    "arbeitsmodell": 0.10,
    "entwicklung": 0.05,
}

# Branchen, in denen das Profil Erfahrung hat. Teilstring-Vergleich gegen die
# von ``industry.classify_industry`` vergebene Bezeichnung.
DEFAULT_ZIEL_BRANCHEN = (
    "Automotive",
    "Luft- und Raumfahrt",
    "Defense",
    "Halbleiter",
    "Robotik",
    "Energie",
    "Engineering-Dienstleister",
)

DEFAULT_OPTIONS: dict = {
    "gewichte": DEFAULT_WEIGHTS,
    "gehalt_ziel_tsd": 65,
    "ko_gehalt_min_tsd": 55,
    # Leer = keine Senioritäts-K.O. Die Schwelle ist eine persönliche
    # Entscheidung („ist eine Teamleiter-Stelle noch gewollt?“), deshalb ist
    # nur das Gehalt standardmäßig hart. Beispiel: ["head of", "abteilungsleiter"].
    "ko_senioritaet": (),
    "ziel_branchen": DEFAULT_ZIEL_BRANCHEN,
    "ko_blockiert_generierung": True,
}

# --- Seniorität -----------------------------------------------------------
# Auf normalisiertem Text (Umlaute abgebaut) — „Geschäftsführer“ → „geschaftsfuhrer“.
_JUNIOR = re.compile(r"\bjunior\w*|\beinsteiger\w*|\babsolvent\w*|\bgraduat\w*")
_SENIOR = re.compile(r"\bsenior\w*|\berfahren\w*|\bexpert\w*")
# Koordination ist Verantwortung ohne disziplinarische Leitung — die Stufe des
# eigenen Profils („Testkoordinator“) und einer „Testkoordinator“-Stelle.
_COORD = re.compile(r"\w*koordinator\w*|\w*coordinator\w*")
_LEAD = re.compile(
    r"\blead\b|\bprincipal\b|\bteamleiter\w*|\bgruppenleiter\w*|"
    r"\bprojektleiter\w*|\bteilprojektleiter\w*|\bteam\s*lead\w*|"
    r"\barchitekt\w*|\barchitect\w*"
)
_HEAD = re.compile(
    r"\bhead\s+of\b|\babteilungsleiter\w*|\bdirector\b|"
    r"\bgeschaftsfuhrer\w*|\bgeschaeftsfuehrer\w*|\bvp\b"
)

_LEVEL_NAMES = {
    1: "Junior",
    2: "Mitarbeiter",
    3: "Senior",
    4: "Lead/Projektleitung",
    5: "Head/Abteilungsleitung",
}

# --- Aufgaben -------------------------------------------------------------
# Signifikante Tätigkeitsfamilien. Bewusst Gruppen statt Einzelwörter: „test“
# allein steht in fast jeder Anzeige, die *Kombination* aus Test, Integration,
# Verifikation und Projektsteuerung beschreibt die Rolle.
_TASK_GROUPS: tuple[tuple[str, str], ...] = (
    ("Testdurchführung", r"\btest\w*|\bpruef\w*|\bpruf\w*|\bversuch\w*"),
    ("Testautomatisierung", r"testautomatisierung|test automation|testautomation|\bautomatisier\w*"),
    ("Integration", r"integration\w*|inbetriebnahme|schnittstelle\w*"),
    ("Verifikation/Validierung",
     r"verifikation\w*|validierung\w*|absicherung\w*|verification\w*|validation\w*|\bnachweis\w*"),
    ("Anforderungen", r"anforderung\w*|requirement\w*|\bdoors\b|spezifikation\w*"),
    ("Fehleranalyse", r"fehleranalyse\w*|root\s*cause|fault analysis|\bdebug\w*"),
    ("Projektsteuerung",
     r"projektleit\w*|teilprojekt\w*|koordination\w*|koordinier\w*|planung\w*|steuerung\w*"),
    ("Dokumentation", r"dokumentation\w*|bericht\w*|reporting"),
)

# --- Entwicklung ----------------------------------------------------------
_GROWTH_RE = re.compile(
    r"weiterbild\w*|fortbild\w*|weiterentwickl\w*|karriere\w*|aufstieg\w*|"
    r"entwicklungsmoglich\w*|training\w*|coach\w*|zertifizier\w*|"
    r"gestaltungsspielraum|verantwortung ubernehmen"
)

# --- Gehalt ---------------------------------------------------------------
_RANGE_T = re.compile(
    r"(\d{2,3})\s*[-–—]\s*(\d{2,3})\s*(?:t€|teur|tsd)", re.IGNORECASE)
_RANGE_EUR = re.compile(
    r"(\d{2,3})[.,](\d{3})\s*[-–—]\s*(\d{2,3})[.,](\d{3})\s*(?:€|eur)", re.IGNORECASE)
_SINGLE_EUR = re.compile(r"(\d{2,3})[.,](\d{3})\s*(?:€|eur)", re.IGNORECASE)
_SINGLE_T = re.compile(r"(\d{2,3})\s*(?:t€|teur|tsd)", re.IGNORECASE)


def options(config: dict | None = None) -> dict:
    """Liest ``matching.dimensions`` aus der Config und füllt Defaults auf.

    Teilweise gesetzte Gewichte werden auf 1,0 normalisiert, damit ``gesamt``
    immer auf der Skala 0–100 bleibt.
    """
    raw = ((config or {}).get("matching") or {}).get("dimensions") or {}
    opts = dict(DEFAULT_OPTIONS)
    for key in ("gehalt_ziel_tsd", "ko_gehalt_min_tsd", "ko_senioritaet",
                "ziel_branchen", "ko_blockiert_generierung"):
        if key in raw and raw[key] is not None:
            opts[key] = raw[key]
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in (raw.get("gewichte") or {}).items():
        if key not in DEFAULT_WEIGHTS:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            weights[key] = value
    total = sum(weights.values()) or 1.0
    opts["gewichte"] = {k: v / total for k, v in weights.items()}
    opts["ko_senioritaet"] = [str(x) for x in (opts["ko_senioritaet"] or [])]
    return opts


def _scale(n: float, k: float = 4.0) -> int:
    """Sättigende Skala: 0 → 0, k → 50, 3k → 75, 7k → 87, 12k → 92."""
    if n <= 0:
        return 0
    return min(100, round(100 * n / (n + k)))


def _as_minutes(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_salary_tsd(text: str | None) -> tuple[int, int] | None:
    """Liest eine Gehaltsspanne aus Anzeigen-Texten (Rückgabe in T€).

    Erkennt ``"62–78 T€"``, ``"60.000 – 75.000 €"``, ``"60.000 €"`` und
    ``"88–93 T€ (Anzeige)"``. Rückgabe ``None``, wenn keine echte Zahl vorliegt.
    """
    s = (text or "").strip()
    if not s:
        return None
    if normalize(s) in {"k. a.", "k.a.", "-", "keine angabe", "keine angaben"}:
        return None
    m = _RANGE_EUR.search(s)
    if m:
        lo = int(m.group(1)) * 1000 + int(m.group(2))
        hi = int(m.group(3)) * 1000 + int(m.group(4))
        return lo // 1000, hi // 1000
    m = _RANGE_T.search(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _SINGLE_EUR.search(s)
    if m:
        value = int(m.group(1)) * 1000 + int(m.group(2))
        return value // 1000, value // 1000
    m = _SINGLE_T.search(s)
    if m:
        return int(m.group(1)), int(m.group(1))
    return None


def _level_from_title(title: str | None) -> int:
    n = normalize(title or "")
    if _HEAD.search(n):
        return 5
    if _LEAD.search(n):
        return 4
    if _SENIOR.search(n) or _COORD.search(n):
        return 3
    if _JUNIOR.search(n):
        return 1
    return 2


def _profile_level(profile: Profile) -> int:
    """Höchste nachweisbare Verantwortungsstufe im Profil.

    Bewusst aus den *Rollenbezeichnungen* abgeleitet (nicht aus Jahren): Ein
    Profil, das „Testkoordination“ führt, ist eine Stufe über „Mitarbeiter“.
    """
    roles = []
    for we in profile.work_experience:
        roles.extend([str(we.get("role_de") or ""), str(we.get("role_en") or "")])
    text = normalize(" ".join(roles))
    if _HEAD.search(text):
        return 5
    if _LEAD.search(text):
        return 4
    if _SENIOR.search(text) or _COORD.search(text):
        return 3
    return 2


def _senioritaet_score(job_level: int, profile_level: int) -> tuple[int, list[str]]:
    diff = job_level - profile_level
    if diff == 0:
        score = 100
    elif diff > 0:
        # Eine Stufe drüber ist der normale nächste Schritt, drei Stufen sind
        # eine andere Rolle. Das ist eine Bewertung, kein Ausschluss — die
        # K.O.-Liste ist separat und standardmäßig leer.
        score = {1: 80, 2: 60}.get(diff, 30)
    else:
        score = {1: 85, 2: 55}.get(-diff, 25)
    detail = (f"Stelle: {_LEVEL_NAMES[job_level]} ({job_level}) · "
              f"Profil: {_LEVEL_NAMES[profile_level]} ({profile_level})")
    return score, [detail]


def _kompetenz(profile: Profile, hits: dict) -> tuple[int, list[str]]:
    title = hits.get("title") or []
    body = hits.get("body") or []
    words = hits.get("words") or []
    # Titel-Treffer wiegen doppelt: wer die Rolle im Titel nennt, meint sie ernst.
    n = 2 * len(title) + len(body) + 0.5 * len(words)
    score = _scale(n, 4)
    shown = [profile.display_of(h) for h in (title + sorted(set(body) - set(title)))[:6]]
    belege = [f"{len(title)} Titel-, {len(body)} Text-, {len(words)} Wort-Treffer"]
    if shown:
        belege.append("Treffer: " + ", ".join(shown))
    return score, belege


def _aufgaben(title: str, desc: str) -> tuple[int, list[str]]:
    text = normalize(f"{title} {desc}")
    found = [(name, re.findall(pattern, text)) for name, pattern in _TASK_GROUPS]
    found = [(name, hits) for name, hits in found if hits]
    score = min(100, 18 * len(found))
    belege = [f"{len(found)} von {len(_TASK_GROUPS)} Tätigkeitsfamilien"]
    if found:
        belege.append("Erkannt: " + ", ".join(name for name, _ in found))
    return score, belege


def _technologie(job: dict, opts: dict) -> tuple[int, list[str]]:
    branch = (job.get("branche") or "").strip() or classify_industry(job)
    n = normalize(branch)
    ziele = [normalize(str(z)) for z in opts["ziel_branchen"] if str(z).strip()]
    for ziel in ziele:
        if ziel and ziel in n:
            return 100, [f"Branche in der Zielliste: {branch}"]
    if not n or n in ("nicht ermittelt", "unbekannt"):
        return 55, ["Branche nicht ermittelt (neutral)"]
    return 25, [f"Branche außerhalb der Zielliste: {branch}"]


def _is_estimated_salary(value: str) -> bool:
    """True, wenn der Wert eine Schätzung ist (Xing-Schätzung o. Ä.).

    ``salary.enrich_salary`` setzt ``gehalt_quelle: "Anzeige"`` für jeden Wert,
    der keine Platzhalter ist — auch für „48.500–67.000 € (Xing-Schätzung)“.
    Eine Schätzung darf aber weder das Gehalt noch eine K.O. auslösen.
    """
    n = normalize(value or "")
    return any(marker in n for marker in ("schatzung", "geschatzt", "xing"))


def _gehalt(job: dict, opts: dict) -> tuple[int, list[str]]:
    value = str(job.get("gehalt") or "")
    source = str(job.get("gehalt_quelle") or "")
    rng = parse_salary_tsd(value)
    ziel = float(opts["gehalt_ziel_tsd"])
    if rng and source == "Anzeige" and not _is_estimated_salary(value):
        lo = rng[0]
        score = 100 if lo >= ziel else max(0, round(100 - (ziel - lo) * 4))
        return int(score), [f"Anzeige: {value} (Ziel {ziel:.0f} T€)"]
    if rng:
        return 55, [f"geschätzt: {value} (keine Angabe in der Anzeige)"]
    return 50, ["keine Gehaltsangabe (neutral)"]


def _arbeitsmodell(job: dict) -> tuple[int, list[str]]:
    mode = str(job.get("pendel_modus") or "")
    home = str(job.get("homeoffice") or "")
    if mode == "Remote" or home == "Voll-Remote":
        return 100, ["Remote"]
    minutes = _as_minutes(job.get("pendelzeit_min"))
    if minutes is None:
        return 55, ["Pendelweg unbekannt (neutral)"]
    for limit, score in ((30, 100), (45, 85), (60, 65), (75, 45), (90, 25)):
        if minutes <= limit:
            belege = [f"Pendelweg {minutes:.0f} min"]
            if home:
                belege.append(f"Homeoffice: {home}")
            return score, belege
    return 0, [f"Pendelweg {minutes:.0f} min (über der Grenze)"]


def _entwicklung(desc: str) -> tuple[int, list[str]]:
    hits = sorted(set(_GROWTH_RE.findall(normalize(desc or ""))))
    if not hits:
        return 45, ["keine Entwicklungs-Signale (neutral)"]
    return min(100, 50 + 12 * len(hits)), ["Signale: " + ", ".join(hits[:6])]


def _ko_liste(job: dict, opts: dict) -> list[dict]:
    out: list[dict] = []
    value = str(job.get("gehalt") or "")
    if str(job.get("gehalt_quelle") or "") == "Anzeige" and not _is_estimated_salary(value):
        rng = parse_salary_tsd(value)
        minimum = float(opts["ko_gehalt_min_tsd"])
        # Nur das **obere** Ende zählt: „52–59 T€“ kann 59 T€ bedeuten und ist
        # damit kein harter Ausschluss. Hart ist erst eine Spanne, deren bestes
        # Ende unter der Schwelle liegt („45–52 T€“).
        if rng and rng[1] < minimum:
            out.append({
                "grund": "Gehalt unter Schwelle",
                "detail": f"{value} (auch oben < {minimum:.0f} T€)",
            })
    title = normalize(job.get("titel") or "")
    for pattern in opts["ko_senioritaet"]:
        p = normalize(pattern)
        if p and p in title:
            out.append({"grund": "Seniorität ausgeschlossen", "detail": pattern})
    return out


def score_dimensions(profile: Profile, job: dict, config: dict | None = None,
                     hits: dict | None = None) -> dict:
    """Bewertet eine Stelle in sieben Dimensionen (0–100) + K.O.-Liste.

    ``hits`` erlaubt es, die Keyword-Treffer aus ``matching.score_job``
    wiederzuverwenden, statt sie ein zweites Mal zu berechnen.
    """
    opts = options(config)
    title = job.get("titel") or job.get("title") or ""
    desc = (job.get("beschreibung") or job.get("description")
            or job.get("snippet") or "")
    if hits is None:
        hits = {
            "title": profile.keywords_in(title),
            "body": profile.keywords_in(desc),
            "words": profile.words_in(f"{title} {desc}"),
        }

    profile_level = _profile_level(profile)
    job_level = _level_from_title(title)

    werte: dict[str, int] = {}
    belege: dict[str, list[str]] = {}
    werte["kompetenz"], belege["kompetenz"] = _kompetenz(profile, hits)
    werte["aufgaben"], belege["aufgaben"] = _aufgaben(title, desc)
    werte["senioritaet"], belege["senioritaet"] = _senioritaet_score(
        job_level, profile_level)
    werte["technologie"], belege["technologie"] = _technologie(job, opts)
    werte["gehalt"], belege["gehalt"] = _gehalt(job, opts)
    werte["arbeitsmodell"], belege["arbeitsmodell"] = _arbeitsmodell(job)
    werte["entwicklung"], belege["entwicklung"] = _entwicklung(desc)

    gewichte = opts["gewichte"]
    gesamt = round(sum(werte[k] * gewichte.get(k, 0.0) for k in werte))
    ko = _ko_liste(job, opts)
    return {
        "werte": werte,
        "gewichte": gewichte,
        "gesamt": int(gesamt),
        "belege": belege,
        "ko": ko,
        "blockiert": bool(ko),
        "version": 1,
    }
