"""Relevanz-Triage: filtert Rollen-Lärm, bevor er in den Bestand kommt.

Die Suche liefert auch Stellen, die für einen Vollzeit-Testingenieur nie in
Frage kommen — Taxifahrer, Vertrieb, Marketing, Buchhaltung, Gastronomie,
Pflege, handwerkliche Fertigung. Bisher landeten sie im Bestand, wurden
gescort und mussten nachträglich gelöscht werden.

Dieses Modul entscheidet anhand von **Titel und Firma** (billig, ohne die
Anzeige zu laden) in drei Klassen:

* ``relevant`` — klares Ingenieurs-/Test-/Software-/Technik-Signal.
* ``reject``   — eindeutig andere Domäne (Vertrieb, Marketing, Finanzen, …).
* ``unsure``   — alles dazwischen. Hier lohnt das Nachladen der Beschreibung;
  der Fit entscheidet.

Bewusst regelbasiert und deterministisch: derselbe Titel ergibt dieselbe
Klasse, nachvollziehbar und testbar. Ein Sprachmodell kann später
hinzukommen — die Klasse bleibt das Interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .matching import is_student_role

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
    # Einkauf / Beschaffung
    r"|\beinkauf\w*|\bpurchas\w*|\bbeschaffung\w*|\bprocurement\b"
    # Gastronomie / Hotellerie
    r"|\bkoch\w*|\bcommis\b|\bchef\s+de\b|\bpartie\b|\bservicekraft\w*"
    r"|\brestaurant\w*|\bhotel\w*|\bbarista\w*|\bcuisine\b"
    # Fahren / Transport / Zustellung
    r"|\btaxi\w*|\bchauffeur\w*|\bkurier\w*|\bfahrer\b|\blieferant\w*"
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


def classify(title: str | None, firma: str | None = None,
             beschreibung: str | None = None) -> Verdict:
    """Ordnet eine Stelle ein: ``relevant``, ``unsure`` oder ``reject``.

    Regelwerk (in dieser Reihenfolge):

    1. Studenten-/Praktikumsrolle → ``reject`` (nie eine Vollzeitstelle).
    2. Eindeutig andere Domäne **ohne** technisches Signal → ``reject``.
    3. Technisches Signal **und** andere Domäne → ``unsure`` (z. B. „Sales
       Engineer"): technisch möglich, aber die Rolle muss der Mensch beurteilen.
    4. Technisches Signal → ``relevant``.
    5. Sonst → ``unsure``.

    ``beschreibung`` wird nur für die letzte Stufe herangezogen: nennt ein
    unklarer Titel im Text doch Technik, wird daraus ``relevant``. So fällt die
    teure Entscheidung erst, wenn der Titel allein nicht reicht.
    """
    t = (title or "").strip()
    if not t:
        return Verdict(UNSURE, "Kein Titel")

    if is_student_role(t):
        return Verdict(REJECT, "Studenten-/Praktikumsstelle")

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


def verdict_for(job: dict) -> Verdict:
    """Bequemer Aufruf für einen Job-Datensatz."""
    return classify(job.get("titel"), job.get("firma"), job.get("beschreibung"))


def split(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Teilt Jobs in (behalten, verworfen) — nur ``reject`` fliegt raus.

    ``unsure`` bleibt bewusst im Bestand: der Fit entscheidet, nicht der Titel.
    """
    kept: list[dict] = []
    rejected: list[dict] = []
    for job in jobs:
        (rejected if verdict_for(job).is_reject else kept).append(job)
    return kept, rejected
