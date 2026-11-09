"""Manueller Import-Provider: liest ``data/import_jobs.json``.

Erwartetes Format (Array):

    [
      {
        "firma": "Beispiel GmbH",
        "titel": "Testingenieur HiL (m/w/d)",
        "ort": "München",
        "url": "https://...",
        "beschreibung": "Optionaler Anzeigentext ..."
      }
    ]
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from ..profile import normalize

# Leads aus Job-Mails (JobLeads, Xing, Instaffo …): nur Firma + Titel, ohne Anzeigentext.
# Sie landen im selben Import, werden aber erst nach den Web-Providern aufgenommen
# (siehe ``run_search``) — eine vollständige Anzeige darf nicht vom Platzhalter verdrängt werden.
MAIL_LEAD = "Mail-Lead"
MAIL_LEAD_TAGE = 30

# Ab dieser Wortüberlappung gelten zwei Titel derselben Firma als dieselbe Stelle.
# Bewusst streng: Eine falsche Zuordnung bringt fremden Text in die Bewertung, das
# wiegt schwerer als ein Lead, der offen bleibt. 0,75 traf „Mechatronics and
# Hardware Test Engineer" und „Mechatronics Test Engineer" (ADR-055).
TITEL_AEHNLICHKEIT = 0.8
# Ein Lead wird höchstens einmal in dieser Frist gesucht: Seine Anzeige erscheint
# nicht täglich neu, und jede Suche kostet das Portal einen Seitenaufruf.
LEAD_SUCHE_TAGE = 7
LEADS_JE_LAUF = 30
_MIN_FIRMENKERN = 4

_RECHTSFORM_RE = re.compile(
    r"\b(gmbh|mbh|ag|se|kg|kgaa|ohg|ug|co|ltd|limited|inc|llc|plc|sa|bv|nv"
    r"|group|gruppe|holding|deutschland|germany|europe|international|und|and)\b"
)
_TITEL_FUELLWOERTER = frozenset({
    "all", "gender", "genders", "am", "an", "and", "als", "at", "bei", "de", "der", "das",
    "den", "die", "for", "fuer", "fur", "im", "in", "mit", "munchen", "muenchen", "munich",
    "of", "oder", "or", "teilzeit", "the", "und", "vollzeit",
})


def _identity(firma: str | None, titel: str | None) -> tuple[str, str]:
    def norm(text: str | None) -> str:
        return " ".join(re.sub(r"[^a-z0-9äöüß]+", " ", (text or "").lower()).split())
    return norm(firma), norm(titel)


def lead_key(lead: dict) -> str:
    """Bestandsschlüssel eines Leads ohne URL (wie ``pipeline._job_key``)."""
    return normalize(f"{lead.get('firma', '')}|{lead.get('titel', '')}")


def _firmenkern(firma: str | None) -> str:
    """Firmenname ohne Rechtsform und Trennzeichen: „Agile Robots SE" → ``agilerobots``."""
    text = _RECHTSFORM_RE.sub(" ", normalize(firma or "").replace("&", " "))
    return re.sub(r"[^a-z0-9]+", "", text)


def firma_passt(a: str | None, b: str | None) -> bool:
    """Gleiche Firma? Portale kürzen und verkleben Namen („Agilerobotsse")."""
    kern_a, kern_b = _firmenkern(a), _firmenkern(b)
    if not kern_a or not kern_b:
        return False
    if kern_a == kern_b:
        return True
    kurz, lang = sorted((kern_a, kern_b), key=len)
    return len(kurz) >= _MIN_FIRMENKERN and lang.startswith(kurz)


def _titel_woerter(titel: str | None) -> set[str]:
    """Sinntragende Wörter eines Titels, ohne Genderkürzel und abgeschnittenes Wortende."""
    roh = (titel or "").strip()
    gekuerzt = roh.endswith(("...", "…"))
    woerter = re.split(r"[^a-z0-9]+", normalize(roh.rstrip(".… ")))
    if gekuerzt and woerter:
        woerter = woerter[:-1]
    return {w for w in woerter if len(w) > 1 and w not in _TITEL_FUELLWOERTER}


def titel_passt(lead_titel: str | None, titel: str | None) -> bool:
    """Gleicher Titel? Mails kürzen lange Titel mit „…", dann zählt der Anfang."""
    a, b = _titel_woerter(lead_titel), _titel_woerter(titel)
    if not a or not b:
        return False
    if (lead_titel or "").strip().endswith(("...", "…")):
        return len(a) >= 2 and a <= b
    return len(a & b) / len(a | b) >= TITEL_AEHNLICHKEIT


def lead_passt(lead: dict, anzeige: dict) -> bool:
    """True, wenn ``anzeige`` dieselbe Stelle wie ``lead`` beschreibt."""
    return (firma_passt(lead.get("firma"), anzeige.get("firma"))
            and titel_passt(lead.get("titel"), anzeige.get("titel")))


def suchbegriff(lead: dict) -> str:
    """Suchtext für ein Portal: Firma + Titel ohne Klammern und Mail-Kürzung."""
    titel = re.sub(r"\(.*?\)", " ", lead.get("titel") or "").rstrip(".… ")
    return " ".join(f"{lead.get('firma') or ''} {titel}".split())


def offene_leads(path: Path, heute: date | None = None,
                 max_leads: int = LEADS_JE_LAUF) -> list[dict]:
    """Mail-Leads ohne URL, deren letzte Suche länger als ``LEAD_SUCHE_TAGE`` zurückliegt."""
    heute = heute or date.today()
    grenze = (heute - timedelta(days=LEAD_SUCHE_TAGE)).isoformat()
    offen = [j for j in load_import(path)
             if j.get("quelle") == MAIL_LEAD and not j.get("url")
             and str(j.get("url_gesucht") or "") <= grenze]
    return offen[:max_leads]


def leads_verknuepfen(path: Path, anzeigen: list[dict], heute: date | None = None,
                      max_leads: int = LEADS_JE_LAUF) -> int:
    """Trägt für offene Leads die gefundene Anzeigen-URL in den Import ein.

    Jeder geprüfte Lead bekommt ``url_gesucht``, auch ohne Treffer. Die übrigen
    Einträge des Imports bleiben unverändert. Rückgabe: Zahl der neuen URLs.
    """
    heute = heute or date.today()
    daten = load_import(path)
    offen = {lead_key(j) for j in offene_leads(path, heute, max_leads)}
    gefunden = 0
    for lead in daten:
        if lead.get("quelle") != MAIL_LEAD or lead.get("url") or lead_key(lead) not in offen:
            continue
        lead["url_gesucht"] = heute.isoformat()
        treffer = next((a for a in anzeigen if a.get("url") and lead_passt(lead, a)), None)
        if treffer:
            lead["url"] = treffer["url"]
            lead["url_quelle"] = treffer.get("quelle") or ""
            lead["ort"] = lead.get("ort") or treffer.get("ort") or ""
            gefunden += 1
    if offen:
        path.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    return gefunden


def saubere_lead_url(url: str | None) -> str:
    """Öffentliche Anzeigen-URL eines Mail-Leads, sonst ``""``.

    Links aus Job-Mails tragen Nutzer-Kennungen, und XING meldet Recruitern den
    Klick. Übernommen wird deshalb nur die JobLeads-Detailseite, ohne Query:
    Sie öffnet ohne Anmeldung und enthält den Anzeigentext.
    """
    treffer = re.match(r"https://www\.jobleads\.com/de/job/[^?#\s]+", (url or "").strip())
    return treffer.group(0) if treffer else ""


def merge_mail_leads(path: Path, leads: list[dict], heute: date | None = None,
                     max_age_days: int = MAIL_LEAD_TAGE) -> int:
    """Hängt neue Mail-Leads an den Import an; gibt die Zahl der neu aufgenommenen zurück.

    Von Hand gepflegte Einträge bleiben unangetastet. Nur alte Mail-Leads
    (älter als ``max_age_days``) werden entfernt. Ohne Firma oder Titel wird
    ein Lead nicht aufgenommen — ohne beides lässt er sich weder zuordnen
    noch bewerten.
    """
    heute = heute or date.today()
    grenze = (heute - timedelta(days=max_age_days)).isoformat()
    bestehend = load_import(path)
    behalten = [j for j in bestehend
                if j.get("quelle") != MAIL_LEAD or str(j.get("gefunden") or "9999") >= grenze]
    bekannt = {_identity(j.get("firma"), j.get("titel")): j for j in behalten}
    neu = 0
    url_ergaenzt = False
    for lead in leads:
        firma, titel = (lead.get("firma") or "").strip(), (lead.get("titel") or "").strip()
        ident = _identity(firma, titel)
        url = saubere_lead_url(lead.get("url"))
        vorhanden = bekannt.get(ident)
        if vorhanden is not None:
            if url and vorhanden.get("quelle") == MAIL_LEAD and not vorhanden.get("url"):
                vorhanden["url"] = url
                url_ergaenzt = True
            continue
        if not firma or not titel:
            continue
        eintrag = {"firma": firma, "titel": titel, "ort": lead.get("ort") or "",
                   "url": url, "beschreibung": "", "quelle": MAIL_LEAD,
                   "herkunft": lead.get("quelle") or "", "gefunden": heute.isoformat()}
        bekannt[ident] = eintrag
        behalten.append(eintrag)
        neu += 1
    if neu or url_ergaenzt or len(behalten) != len(bestehend):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(behalten, ensure_ascii=False, indent=2), encoding="utf-8")
    return neu


def load_import(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("jobs", [])
    if not isinstance(data, list):
        return []
    return data


def search(path: Path) -> list[dict]:
    jobs = []
    for j in load_import(path):
        description = (j.get("beschreibung") or j.get("description")
                       or j.get("snippet") or "")
        extra = {}
        if j.get("quelle") == MAIL_LEAD and j.get("url"):
            # Der Lead liegt unter ``Firma|Titel`` im Bestand. Mit dem festen Schlüssel
            # füllt die gefundene URL diesen Eintrag, statt einen zweiten anzulegen.
            extra["bestand_key"] = lead_key(j)
        jobs.append({
            **extra,
            "titel": j.get("titel") or j.get("title") or "",
            "url": j.get("url") or "",
            # Volltext sowohl als ``beschreibung`` (Dashboard-Anzeige, Matching)
            # als auch als ``snippet`` (Kurzfassung) durchreichen.
            "beschreibung": description,
            "snippet": description[:400],
            "firma": j.get("firma") or j.get("company") or "",
            "ort": j.get("ort") or j.get("location") or "",
            "quelle": j.get("quelle") or "Import",
        })
    return jobs
