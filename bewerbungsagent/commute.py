"""Pendelweg-Berechnung von der Wohnadresse zu jedem Arbeitsort.

Geocoding über Nominatim (OpenStreetMap), Fahrweg über OSRM (Auto).
Alle Ergebnisse werden in Caches abgelegt (``data/geocode_cache.json`` und
``data/commute_cache.json``), damit wiederholte Läufe keine erneuten
API-Aufrufe benötigen. Nominatim wird mit dem geforderten Politeness-Abstand
(≥ 1 s) abgefragt.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .profile import normalize

HOME_ADDRESS = "Musterstraße 1, 12345 Musterstadt"

# Stellen mit längerem Pendelweg werden gar nicht erst angelegt: es werden
# weder Bewerbungsunterlagen erzeugt noch erscheinen sie im Dashboard.
# Maßgeblich ist der berechnete Auto-Pendelweg; unbekannte Werte (``None``,
# z. B. Remote oder fehlgeschlagenes Routing) gelten nicht als zu weit.
MAX_COMMUTE_MINUTES = 90


def exceeds_commute_limit(app: dict, limit: int | None = None) -> bool:
    """True, wenn der bekannte Pendelweg die Obergrenze überschreitet.

    Unbekannte Pendelzeiten (``None``/leer) liefern ``False``: eine fehlende
    Angabe ist kein Ausschlussgrund.
    """
    commute = app.get("pendelzeit_min")
    if commute is None or commute == "":
        return False
    try:
        value = float(commute)
    except (TypeError, ValueError):
        return False
    return value > (MAX_COMMUTE_MINUTES if limit is None else limit)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
_USER_AGENT = "Bewerbungsagent/1.0 (persönliches Bewerbungs-Tool; vorname.nachname@example.com)"

# Ortsnamen, die zur Münchener Metropolregion zählen (dort wird ein realer
# Arbeitsweg angenommen). Reihenfolge irrelevant, nur Zugehörigkeit zählt.
# Wird beim Import normalisiert, damit Umlaute/„ue/oe"-Schreibungen robust matchen.
_METRO_RAW = {
    "muenchen", "munchen", "munich", "garching", "ismaning", "ottobrunn",
    "unterschleissheim", "neubiberg", "unterfoehring", "unterfohring",
    "taufkirchen", "putzbrunn", "kirchheim", "feldkirchen", "haar",
    "oberhaching", "dornach", "aschheim", "grasbrunn", "hohenbrunn", "poing",
    "vaterstetten", "planegg", "gruenwald", "grunwald", "germering",
    "fuerstenfeldbruck", "furstenfeldbruck", "dachau", "starnberg", "gilching",
    "freising", "weilheim", "olching", "puchheim", "groebenzell", "grobenszell",
    "oberpfaffenhofen",
}
_METRO = {normalize(x) for x in _METRO_RAW}
_NON_OFFICE_PARTS = {
    "germany", "deutschland", "bavaria", "bayern", "baden-wuerttemberg",
    "baden-wurttemberg", "berlin", "brandenburg", "bremen", "hamburg",
    "hesse", "hessen", "lower saxony", "niedersachsen", "mecklenburg-vorpommern",
    "north rhine-westphalia", "nordrhein-westfalen", "rhineland-palatinate",
    "rheinland-pfalz", "saarland", "saxony", "sachsen", "saxony-anhalt",
    "sachsen-anhalt", "schleswig-holstein", "thuringia", "thueringen",
}

# Mehrdeutige Ortsnamen in der Region: hier den eindeutigen Suchbegriff wählen,
# damit Nominatim nicht den falschen (weit entfernten) Ort trifft.
_DISAMBIGUATE = {
    "seefeld": "Seefeld, Landkreis Starnberg",
}

_REMOTE_MARKERS = ("remote", "homeoffice", "home office", "deutschlandweit",
                   "bundesweit", "100% remote", "remote-first", "vollzeit remote")

# Parenthesen-Inhalte, die keine Standort-Info tragen (nur Anmerkungen) und
# beim Geocoding stören.
_NOISE_PAREN = ("ermittelbar", "einsatzort", "nicht munchen", "nicht münchen",
                "werk", "kein festes", "kein buro", "kein büro", "bei munchen")


def is_remote(ort: str) -> bool:
    return any(m in normalize(ort or "") for m in _REMOTE_MARKERS)


def _is_metro(token: str) -> bool:
    return any(c in token for c in _METRO)


def _strip_noise(part: str) -> str:
    """Entfernt störende Klammer-Anmerkungen (z. B. „(nicht München!)")."""
    def repl(m: re.Match[str]) -> str:
        inner = normalize(m.group(1))
        return "" if any(p in inner for p in _NOISE_PAREN) else m.group(0)
    cleaned = re.sub(r"\(([^)]*)\)", repl, part)
    cleaned = re.sub(r"\s+bei\s+(?:m[uü]nchen|munich)$", "", cleaned,
                     flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" ,-")


def resolve_office(ort: str) -> str:
    """Wählt aus einer (ggf. mehrteiligen) Ortsangabe den wahrscheinlichen
    München-nahen Standort aus; ansonsten den letzten (Stadt-)Bestandteil."""
    raw = (ort or "").strip()
    if not raw:
        return ""
    parts = [_strip_noise(p) for p in raw.replace(";", "/").replace(",", "/")
             .replace(" oder ", "/").replace(" bzw. ", "/").replace(" bzw ", "/")
             .split("/")]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    for p in parts:
        if _is_metro(normalize(p)):
            return p
    for p in parts:
        if re.search(r"\b\d{5}\b", p):
            return p
    cities = [p for p in parts if normalize(p) not in _NON_OFFICE_PARTS]
    if not cities:
        return ""
    first = cities[0]
    return _DISAMBIGUATE.get(normalize(first), first)


def _simplify(office: str) -> str:
    """Fallback-Abfrage: Klammern und Slash-Teile entfernen (nur Stadt/Ort)."""
    s = re.sub(r"\([^)]*\)", " ", office)
    s = s.split("/")[0].split(",")[0]
    return re.sub(r"\s+", " ", s).strip()


class _Geocoder:
    """Nominatim-Geocoder mit Disk-Cache."""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.cache: dict[str, dict] = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.cache = {}
        self._last = 0.0

    def _throttle(self) -> None:
        wait = 1.1 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

    def geocode(self, query: str) -> dict | None:
        key = normalize(query or "")
        if not key:
            return None
        if key in self.cache:
            return self.cache[key]
        self._throttle()
        try:
            r = requests.get(
                _NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
        except requests.RequestException:
            self._last = time.monotonic()
            return None
        self._last = time.monotonic()
        if r.status_code != 200:
            return None
        data = r.json()
        if not data:
            self.cache[key] = None
            return None
        item = data[0]
        result = {
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "display_name": item.get("display_name", query),
        }
        self.cache[key] = result
        return result

    def save(self) -> None:
        try:
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError:
            pass


def _route_driving(home: dict, dest: dict) -> tuple[float, int] | None:
    """Rückgabe (Distanz_km, Dauer_min) oder None bei Fehler."""
    url = f"{_OSRM_URL}/{home['lon']},{home['lat']};{dest['lon']},{dest['lat']}"
    try:
        r = requests.get(url, params={"overview": "false"}, timeout=20,
                         headers={"User-Agent": _USER_AGENT})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    route = data["routes"][0]
    return round(route["distance"] / 1000.0, 1), round(route["duration"] / 60.0)


def enrich_commute(apps: list[dict], data_dir: Path) -> dict:
    """Berechnet Pendelzeit/-distanz für alle Stellen und schreibt sie zurück.

    Felder pro Stelle: ``pendel_modus`` (Auto|Remote), ``pendelzeit_min``,
    ``pendeldistanz_km``.
    """
    geocoder = _Geocoder(data_dir / "geocode_cache.json")
    route_cache_path = data_dir / "commute_cache.json"
    route_cache: dict[str, dict] = {}
    if route_cache_path.exists():
        try:
            route_cache = json.loads(route_cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            route_cache = {}

    home = geocoder.geocode(HOME_ADDRESS)
    if not home:
        raise RuntimeError(f"Wohnadresse nicht geokodierbar: {HOME_ADDRESS}")

    stats = {"total": len(apps), "remote": 0, "routed": 0, "cached": 0, "failed": 0}

    for a in apps:
        ort = a.get("ort") or ""
        if is_remote(ort):
            a["pendel_modus"] = "Remote"
            a["pendelzeit_min"] = None
            a["pendeldistanz_km"] = None
            stats["remote"] += 1
            continue

        office = resolve_office(ort)
        if not office:
            a["pendel_modus"] = "Nicht ermittelt"
            a["pendelzeit_min"] = None
            a["pendeldistanz_km"] = None
            stats["failed"] += 1
            continue

        dest = geocoder.geocode(office)
        if not dest:
            simplified = _simplify(office)
            if simplified and simplified != office:
                dest = geocoder.geocode(simplified)
        if not dest:
            a["pendel_modus"] = "Nicht ermittelt"
            a["pendelzeit_min"] = None
            a["pendeldistanz_km"] = None
            stats["failed"] += 1
            continue

        cache_key = f"{dest['lat']:.6f},{dest['lon']:.6f}"
        if cache_key in route_cache:
            route = route_cache[cache_key]
            stats["cached"] += 1
        else:
            route = _route_driving(home, dest)
            if route is None:
                a["pendel_modus"] = "Nicht ermittelt"
                a["pendelzeit_min"] = None
                a["pendeldistanz_km"] = None
                stats["failed"] += 1
                continue
            route_cache[cache_key] = {"km": route[0], "min": route[1]}
            stats["routed"] += 1

        a["pendel_modus"] = "Auto"
        a["pendeldistanz_km"] = route_cache[cache_key]["km"]
        a["pendelzeit_min"] = route_cache[cache_key]["min"]

    geocoder.save()

    try:
        tmp = route_cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(route_cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(route_cache_path)
    except OSError:
        pass

    return stats
