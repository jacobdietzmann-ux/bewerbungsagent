"""Pendelweg-Berechnung von der Wohnadresse zu jedem Arbeitsort.

Geocoding über Nominatim (OpenStreetMap), Fahrweg über OSRM (Auto).
Alle Ergebnisse werden in Caches abgelegt (``data/geocode_cache.json`` und
``data/commute_cache.json``), damit wiederholte Läufe keine erneuten
API-Aufrufe benötigen. Nominatim wird mit dem geforderten Politeness-Abstand
(≥ 1 s) abgefragt.

Die Wohnadresse steht **nicht** im Quelltext, sondern unter
``commute.home_address`` in der ``config.json`` — sie ist eine persönliche
Angabe und gehört nicht in ein geteiltes Repository.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .profile import normalize

# Standard-Kennung für die APIs. Nominatim verlangt eine identifizierbare
# Angabe, die Projekt-URL genügt. Eine Kontaktadresse kann über
# ``commute.contact_email`` ergänzt werden — sie steht dann nur in der privaten
# Konfiguration, nicht im Repository.
_USER_AGENT_BASE = ("Bewerbungsagent/1.0 "
                    "(+https://github.com/jacobdietzmann-ux/bewerbungsagent)")


def user_agent(contact_email: str | None = None) -> str:
    """User-Agent für Nominatim/OSRM, optional mit Kontaktadresse."""
    mail = (contact_email or "").strip()
    return f"Bewerbungsagent/1.0 ({mail})" if mail else _USER_AGENT_BASE

# Stellen mit längerem Pendelweg werden gar nicht erst angelegt: es werden
# weder Bewerbungsunterlagen erzeugt noch erscheinen sie im Dashboard.
# Maßgeblich ist der berechnete Auto-Pendelweg; unbekannte Werte (``None``,
# z. B. Remote oder fehlgeschlagenes Routing) gelten nicht als zu weit.
MAX_COMMUTE_MINUTES = 30


def commute_limit_minutes(config_data: dict | None = None) -> int:
    """Die konfigurierte Pendelweg-Grenze in Minuten.

    ``max_pendelzeit_min`` aus der Konfiguration, sonst der Standard. Diese
    Funktion ist die *einzige* Stelle, an der die Grenze ermittelt wird —
    zuvor las sie jedes Modul selbst, und nach einer Änderung standen vier
    verschiedene Werte (30/35/90) gleichzeitig im Code.
    """
    raw = (config_data or {}).get("max_pendelzeit_min")
    try:
        return int(raw) if raw is not None else MAX_COMMUTE_MINUTES
    except (TypeError, ValueError):
        return MAX_COMMUTE_MINUTES


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

# Mittelpunkt Münchens (Marienplatz). Nur für Umkreissuchen bei Jobbörsen, die
# Koordinaten statt Ortsnamen erwarten — nicht die Wohnadresse.
MUNICH_LAT = 48.1371079
MUNICH_LON = 11.5753822

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

# Mehr-Standort-Angaben belegen **keine** Nähe: der tatsächliche Einsatzort steht
# nicht fest. „bundesweit, Düsseldorf, Frankfurt, Hamburg, München" ist eine
# Beratungstätigkeit beim Kunden, kein Arbeitsplatz in München. Vorher zählte der
# Teilstring „münchen" als Ortstreffer und gab +10 Punkte — eine 84-%-Stelle war
# in Wahrheit nicht in München.
_MULTI_LOCATION_MARKERS = (
    "bundesweit", "deutschlandweit", "mehrere standorte", "verschiedene standorte",
    "verschiedene orte", "weitere standorte", "+ weitere", "wechselnde",
    "wechselnder einsatzort", "verschiedene kunden", "wechselnde projekte",
)


# Teile einer Ortsangabe, die keinen zweiten Arbeitsort bezeichnen: Land,
# Bundesland, Region. „München, Bayern, Deutschland" ist **ein** Standort,
# „Munich, Germany, San Diego, California" sind zwei.
_NON_PLACE = {
    "deutschland", "germany", "de", "brd", "d",
    "osterreich", "austria", "at", "schweiz", "switzerland", "ch",
    "usa", "united states", "us", "vereinigte staaten",
    "bayern", "bavaria", "by", "baden-wurttemberg", "baden-wuerttemberg",
    "nordrhein-westfalen", "nrw", "hessen", "sachsen", "niedersachsen",
    "rheinland-pfalz", "berlin-brandenburg", "schleswig-holstein",
    "thuringen", "sachsen-anhalt", "saarland",
    "oberosterreich", "niederosterreich", "steiermark",
    "california", "ca", "texas", "tx", "washington", "wa", "new york", "ny",
    "region", "raum", "umgebung", "homeoffice", "remote", "hybrid",
}


def _place_parts(ort: str) -> list[str]:
    """Zerlegt eine Ortsangabe in Standort-Kandidaten.

    Verworfen werden Teile, die keinen Ort benennen: Land/Bundesland/Region
    (``_NON_PLACE``) und Adressbestandteile mit Hausnummer oder Postleitzahl
    („Landaubogen 1", „81373 München (Sendling)") — eine Straßenadresse ist
    **ein** Standort, keine Aufzählung.
    """
    parts = []
    for raw in normalize(ort or "").split(","):
        part = raw.strip(" .;/-")
        if not part or part in _NON_PLACE or re.search(r"\d", part):
            continue
        parts.append(part)
    return parts


def is_multi_location(ort: str) -> bool:
    """True, wenn der Ort mehrere Standorte zur Wahl stellt.

    Solche Angaben sind für den Ortsbonus unbrauchbar: ein einzelner Stadtname
    in der Aufzählung belegt keine Nähe. Land/Bundesland und Adressbestandteile
    zählen **nicht** als zweiter Standort — „Garching b. Muenchen, Bayern,
    Germany" und „Landaubogen 1, 81373 München" bleiben je ein Ort.
    """
    text = normalize(ort or "")
    if not text:
        return False
    if any(marker in text for marker in _MULTI_LOCATION_MARKERS):
        return True
    return len(_place_parts(text)) >= 2


def all_locations_near_munich(ort: str) -> bool:
    """True, wenn **jeder** genannte Standort in der Metropolregion liegt.

    „München, Starnberg" ist eine echte Wahl zwischen zwei nahen Büros —
    „München, Berlin" ist keine Nähe. Nur im zweiten Fall darf der Ortsbonus
    entfallen.
    """
    parts = _place_parts(ort)
    return bool(parts) and all(_is_metro(part) for part in parts)


def is_remote(ort: str) -> bool:
    return any(m in normalize(ort or "") for m in _REMOTE_MARKERS)


# Parenthesen-Inhalte, die keine Standort-Info tragen (nur Anmerkungen) und
# beim Geocoding stören.
_NOISE_PAREN = ("ermittelbar", "einsatzort", "nicht munchen", "nicht münchen",
                "werk", "kein festes", "kein buro", "kein büro", "bei munchen")

# Zusatz hinter dem Ortsnamen, der nur die Region nennt („Poing bei München",
# „Kaufering nahe München"). Wird entfernt, damit geokodiert werden kann.
# Vorher war nur „bei" abgedeckt — „Kaufering nahe München" blieb stehen und
# war bei Nominatim nicht auflösbar, die Stelle hatte dann gar keinen Pendelweg
# und umging damit die harte Grenze.
_NOISE_SUFFIX = re.compile(
    r"\s+(?:nahe(?:\s+bei)?|nähe|bei|raum|umgebung|großraum|grossraum)\s+"
    r"(?:m[uü]nchen|munich)\s*$",
    re.IGNORECASE,
)


def is_near_munich(ort: str) -> bool:
    """True, wenn der Ort in der Münchener Metropolregion liegt oder remote ist.

    Für Provider, die **alle** Stellen einer Firma auf einmal liefern (ATS,
    Arbeitnow), ist das der günstige Vorfilter: eine Firma mit 141 Stellen
    weltweit würde sonst 141 Geocoding-Aufrufe à 1 s kosten, nur um danach
    festzustellen, dass 130 davon zu weit weg sind.
    """
    if is_remote(ort):
        return True
    return _is_metro(normalize(ort or ""))


def office_override(firma: str, overrides: dict | None) -> str:
    """Konfigurierter Firmensitz, der die Ortsangabe der Anzeige ersetzt.

    Viele Anzeigen nennen nur die Zentrale („München"), während das Büro
    tatsächlich woanders liegt (z. B. STARK Defence in Maisach). Der Pendelweg
    muss zum echten Arbeitsort berechnet werden — sonst liegt er zu niedrig und
    eine zu weit entfernte Stelle rutscht durch die ``max_pendelzeit_min``-Grenze.
    """
    if not overrides or not firma:
        return ""
    key = normalize(firma)
    for name, office in overrides.items():
        if normalize(name) == key:
            return str(office or "").strip()
    return ""


def _is_metro(token: str) -> bool:
    return any(c in token for c in _METRO)


def _strip_noise(part: str) -> str:
    """Entfernt störende Klammer-Anmerkungen (z. B. „(nicht München!)")."""
    def repl(m: re.Match[str]) -> str:
        inner = normalize(m.group(1))
        return "" if any(p in inner for p in _NOISE_PAREN) else m.group(0)
    cleaned = re.sub(r"\(([^)]*)\)", repl, part)
    cleaned = _NOISE_SUFFIX.sub("", cleaned)
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


def is_city_only(office: str) -> bool:
    """True, wenn die Ortsangabe nur eine Stadt nennt (keine Hausnummer/PLZ).

    Dann ist der geokodierte Punkt der Stadtmittelpunkt, und der Pendelweg kann
    um die halbe Stadt danebenliegen. In diesem Fall lohnt der Versuch, die
    echte Firmenadresse zu ermitteln.
    """
    return bool(office) and not re.search(r"\d", office)


# Nominatim-Typen, die nur Geografie beschreiben. Sie liefern den
# Stadtmittelpunkt (oder eine Straße ohne Hausnummer) und damit keinen
# Genauigkeitsgewinn gegenüber dem Stadt-Geocoding.
_GEO_TYPES = {"city", "town", "village", "hamlet", "suburb", "administrative",
              "district", "state", "country", "postcode", "road", "motorway",
              "residential", "pedestrian", "footway", "cycleway", "locality"}


def _company_address(geocoder: "_Geocoder", firma: str, city: str,
                     cache: dict) -> dict | None:
    """Sucht die Firmenadresse in der Stadt über Nominatim (mit Cache).

    Der Cache speichert auch Fehlschläge (``None``): Firmen ohne OSM-Eintrag
    würden sonst bei jedem Lauf erneut abgefragt — bei ~100 Firmen sind das
    mehrere Minuten reine Wartezeit wegen der 1-s-Politeness-Regel.
    """
    key = f"{normalize(firma)}|{normalize(city)}"
    if key in cache:
        return cache[key]
    result = None
    if not (firma or "").strip():
        return None
    # „LRE Medical GmbH“ findet in OSM nichts, „LRE Medical“ schon — die
    # Rechtsform steht dort meist nicht im Namen.
    kurz = re.sub(r"\s*[-–]?\s*(gmbh|mbh|ag|se|kg|ug|e\.?\s?v\.?)(\s*&\s*co\.?\s*kg)?\.?$",
                  "", firma, flags=re.IGNORECASE).strip(" ,-")
    queries = [f"{firma}, {city}"]
    if kurz and kurz != firma:
        queries.append(f"{kurz}, {city}")
    for query in queries:
        item = geocoder.search_one(
            query, addressdetails=True,
            extra_params={"countrycodes": "de"},
        )
        if not item:
            continue
        address = item.get("address") or {}
        item_type = (item.get("type") or "").lower()
        if item_type in _GEO_TYPES:
            continue
        # Stadt prüfen: exakt oder innerhalb der Münchener Metropolregion.
        places = [normalize(address.get(k) or "") for k in
                  ("city", "town", "village", "municipality", "suburb")]
        places = [p for p in places if p]
        target = normalize(city)
        if not any(p == target or _is_metro(p) for p in places):
            continue
        if not address.get("road"):
            continue  # nur ein Punkt ohne Straße — kein Genauigkeitsgewinn
        road = str(address["road"]).strip()
        # Sehr kurze „Straßennamen" sind in OSM Gebäude- oder Ortsteilnamen
        # („T&S" traf ein Gebäude namens „S") und damit kein realer Arbeitsort.
        if len(road) < 4:
            continue
        result = {
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "display_name": item.get("display_name", query),
            "strasse": " ".join(filter(None, [road, address.get("house_number")])),
            "ort": address.get("city") or address.get("town") or city,
            "plz": address.get("postcode") or "",
        }
        break
    cache[key] = result
    return result


class _Geocoder:
    """Nominatim-Geocoder mit Disk-Cache."""

    def __init__(self, cache_path: Path, agent: str | None = None):
        self.cache_path = cache_path
        self.agent = agent or _USER_AGENT_BASE
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
                headers={"User-Agent": self.agent},
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

    def search_one(self, query: str, *, addressdetails: bool = False,
                   extra_params: dict | None = None) -> dict | None:
        """Erste Nominatim-Trefferzeile (roh, inkl. ``address``) oder ``None``.

        Getrennt von :meth:`geocode`, weil hier die Adressbestandteile gebraucht
        werden und der Aufrufer selbst entscheiden muss, ob der Treffer zur
        gesuchten Firma/Stadt passt.
        """
        if not (query or "").strip():
            return None
        params: dict = {"q": query, "format": "json", "limit": 1}
        if addressdetails:
            params["addressdetails"] = 1
        if extra_params:
            params.update(extra_params)
        self._throttle()
        try:
            r = requests.get(_NOMINATIM_URL, params=params,
                             headers={"User-Agent": self.agent}, timeout=15)
        except requests.RequestException:
            self._last = time.monotonic()
            return None
        self._last = time.monotonic()
        if r.status_code != 200:
            return None
        data = r.json()
        return data[0] if data else None

    def save(self) -> None:
        """Schreibt den Cache — ohne erfolglose Abfragen.

        Ein ``None`` heißt „hat nicht geklappt", nicht „gibt es nicht". Wurde es
        mitgeschrieben, blieb der Ort für immer unauflösbar: ``geocode`` liefert
        den gespeicherten Fehlschlag zurück, ohne erneut zu fragen. So standen
        Gilching, Poing und Erding dauerhaft auf „Nicht ermittelt", obwohl sie
        auflösbar sind. Innerhalb eines Laufs bleibt der Fehlschlag im
        Speicher-Cache (kein zweiter Aufruf für denselben Ort), über Läufe
        hinweg wird er erneut versucht.
        """
        try:
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: v for k, v in self.cache.items() if v},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError:
            # Cache ist best-effort: ein Schreibfehler darf den Lauf nicht stoppen.
            pass


def _route_driving(home: dict, dest: dict,
                   agent: str | None = None) -> tuple[float, int] | None:
    """Rückgabe (Distanz_km, Dauer_min) oder None bei Fehler."""
    url = f"{_OSRM_URL}/{home['lon']},{home['lat']};{dest['lon']},{dest['lat']}"
    try:
        r = requests.get(url, params={"overview": "false"}, timeout=20,
                         headers={"User-Agent": agent or _USER_AGENT_BASE})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    route = data["routes"][0]
    return round(route["distance"] / 1000.0, 1), round(route["duration"] / 60.0)


def enrich_commute(apps: list[dict], data_dir: Path,
                   home_address: str | None = None,
                   contact_email: str | None = None,
                   office_overrides: dict | None = None) -> dict:
    """Berechnet Pendelzeit/-distanz für alle Stellen und schreibt sie zurück.

    ``home_address`` kommt aus ``commute.home_address`` der Konfiguration.
    Fehlt sie, wird ein klarer Hinweis geworfen statt still eine falsche
    Adresse zu verwenden.

    ``office_overrides`` (aus ``commute.office_overrides``) ersetzt die
    Ortsangabe der Anzeige durch den tatsächlichen Firmensitz.

    Felder pro Stelle: ``pendel_modus`` (Auto|Remote), ``pendelzeit_min``,
    ``pendeldistanz_km``.
    """
    if not home_address or not str(home_address).strip():
        raise RuntimeError(
            "Keine Wohnadresse konfiguriert. Bitte `commute.home_address` in der "
            "config.json setzen (z. B. \"Musterstraße 1, 12345 Musterstadt\")."
        )
    home_address = str(home_address).strip()

    agent = user_agent(contact_email)
    geocoder = _Geocoder(data_dir / "geocode_cache.json", agent)
    route_cache_path = data_dir / "commute_cache.json"
    route_cache: dict[str, dict] = {}
    if route_cache_path.exists():
        try:
            route_cache = json.loads(route_cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            route_cache = {}

    home = geocoder.geocode(home_address)
    if not home:
        raise RuntimeError(f"Wohnadresse nicht geokodierbar: {home_address}")

    office_cache_path = data_dir / "office_cache.json"
    office_cache: dict = {}
    if office_cache_path.exists():
        try:
            office_cache = json.loads(office_cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            office_cache = {}

    stats = {"total": len(apps), "remote": 0, "routed": 0, "cached": 0,
             "failed": 0, "address_resolved": 0}

    for a in apps:
        # Firmensitz-Überschreibung: die Anzeige nennt oft nur die Zentrale.
        override = office_override(a.get("firma"), office_overrides)
        if override:
            a["ort"] = override

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

        # Nennt die Anzeige nur eine Stadt, ist der geokodierte Punkt der
        # Stadtmittelpunkt — der Pendelweg kann dann um die halbe Stadt
        # danebenliegen. Deshalb zuerst die echte Firmenadresse versuchen.
        dest = None
        if is_city_only(office) and not a.get("deleted"):
            adresse = _company_address(geocoder, a.get("firma") or "", office,
                                       office_cache)
            if adresse:
                dest = adresse
                a["office_adresse"] = " ".join(
                    filter(None, [adresse.get("strasse"), adresse.get("plz"),
                                  adresse.get("ort")])).strip()
                stats["address_resolved"] += 1
        if dest is None:
            # Kein (mehr) gültiger Firmensitz: alten Wert nicht stehen lassen,
            # sonst zeigt das Dashboard eine Adresse, zu der nicht geroutet wurde.
            a.pop("office_adresse", None)

        if dest is None:
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
            route = _route_driving(home, dest, agent)
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
        tmp = office_cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(office_cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(office_cache_path)
    except OSError:
        pass

    try:
        tmp = route_cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(route_cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(route_cache_path)
    except OSError:
        # Routen-Cache ist best-effort: ein Schreibfehler darf den Lauf nicht stoppen.
        pass

    return stats
