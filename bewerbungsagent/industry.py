"""Branchenzuordnung für Suchtreffer ohne explizite Branchenangabe."""

from __future__ import annotations

from .profile import normalize

_COMPANY_INDUSTRIES = (
    # Hinweis: Quantum-Systems bleibt bewusst unter „Luft- und Raumfahrt“ (UAS),
    # damit die bestehende Einordnung stabil bleibt.
    ("Defense / Wehrtechnik", ("diehl defence", "diehl defense", "knds", "rheinmetall",
                               "stark defence", "stark defense", "helsing")),
    ("Luft- und Raumfahrt", ("diehl aviation", "dornier", "airbus", "quantum-systems")),
    ("Energie / Leistungselektronik", ("reinhausen",)),
    ("Medizintechnik / Biotechnologie", ("astrazeneca", "neovii", "synformulas")),
    ("Halbleiter / Elektronik", ("panasonic", "theva", "infineon", "actron",
                                 "canon production printing")),
    ("IT / Software / Cybersecurity", ("sopra steria", "adesso", "msg nexinsure",
                                       "leibniz-rechenzentrum")),
    ("Finanzdienstleistung / Versicherung", ("verivox",)),
    ("Gesundheitswesen / Versicherung", ("ikk",)),
    ("Medien / Rundfunk", ("bayerischer rundfunk",)),
    ("Öffentlicher Dienst / Verwaltung", ("staatliche lotterie",
                                          "kommunale datenverarbeitung", "akdb")),
    ("Bildung", ("deutschakademie",)),
)

_ENGINEERING_PROVIDERS = (
    "bertrandt", "alten", "ferchau", "agap2", "sii consulting",
    "proevolution", "iabg",
)

_ENGINEERING_DOMAINS = (
    ("Defense", ("defense", "defence", "wehrtechnik", "military", "flugkorper")),
    ("Automotive", ("automotive", "automobil", "fahrzeug", "vehicle", "hochvolt",
                    "batteriesystem", "e-mobility")),
    ("Luft- und Raumfahrt", ("aerospace", "aviation", "luftfahrt", "raumfahrt",
                             "aircraft", "flugzeug", "uav", "drone", "drohne")),
    ("Energie", ("leistungselektronik", "power electronics", "energietechnik",
                 "transformator", "transformer")),
)

_TITLE_INDUSTRIES = (
    ("Defense / Wehrtechnik", (
        "defense", "defence", "wehrtechnik", "military", "militaer",
        "bundeswehr", "munition", "waffensystem", "landsystem", "flugkoerper",
    )),
    ("Luft- und Raumfahrt", (
        "aerospace", "aviation", "luftfahrt", "raumfahrt", "aircraft",
        "flugzeug", "satellite", "satellit", "uav", "drone", "drohne",
        "flight test", "dornier", "seawings",
    )),
    ("Bahn / Schienenverkehr", (
        "railway", "rail system", "schienenfahrzeug", "lokomotive", "locomotive",
    )),
    ("Medizintechnik / Biotechnologie", (
        "medical", "medizintechnik", "biotech", "biotechnologie",
        "pharma", "healthcare", "diagnostic",
    )),
    ("Robotik / Automation", (
        "robot", "robotik", "automation", "automatisierung", "ugv",
    )),
    ("Automotive / Mobilität", (
        "automotive", "automobil", "fahrzeug", "vehicle", "e-mobility",
        "emobility", "hochvolt", "batteriesystem", "mobility",
    )),
    ("Energie / Leistungselektronik", (
        "leistungselektronik", "power electronics", "energietechnik",
        "transformator", "transformer", "stromnetz", "switchgear",
    )),
    ("Halbleiter / Elektronik", (
        "semiconductor", "halbleiter", "chip", "electronics", "elektronik",
        "thin-film", "duennschicht", "dunschicht", "circuit board",
        "flachbaugruppe", "display",
    )),
    ("Finanzdienstleistung / Versicherung", (
        "insurance", "versicherung", "finanz", "fintech", "e-commerce",
    )),
    ("Medien / Rundfunk", ("broadcast", "media", "rundfunk", "kontributionssystem")),
    ("Öffentlicher Dienst / Verwaltung", (
        "public sector", "oeffentlicher dienst", "verwaltung", "lotterie",
    )),
    ("Bildung / Forschung", (
        "education", "e-learning", "akademie", "rechenzentrum", "wissenschaft",
    )),
    ("IT / Software / Cybersecurity", (
        "cybersecurity", "cyber security", "information security",
        "it-sicherheit", "software", "cloud", "saas", "virtualization",
        "virtualisierung", "embedded",
    )),
)


def classify_industry(job: dict) -> str:
    """Nutzt vorhandene Branchenmetadaten, sonst eine nachvollziehbare Textheuristik."""
    branch = job.get("branche")
    if job.get("branche_quelle") == "Quelle" and isinstance(branch, str) and branch.strip():
        return branch.strip()
    for key in ("industry", "company_industry"):
        value = job.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    company_value = job.get("firma") or job.get("company")
    title_value = job.get("titel") or job.get("title")
    company = normalize(company_value if isinstance(company_value, str) else "")
    title = normalize(title_value if isinstance(title_value, str) else "")
    for industry, keywords in _COMPANY_INDUSTRIES:
        if any(keyword in company for keyword in keywords):
            return industry

    if any(provider in company for provider in _ENGINEERING_PROVIDERS):
        for domain, keywords in _ENGINEERING_DOMAINS:
            if any(keyword in title for keyword in keywords):
                return f"Engineering-Dienstleister / {domain}"
        return "Engineering-Dienstleister"

    for industry, keywords in _TITLE_INDUSTRIES:
        if any(keyword in title for keyword in keywords):
            return industry
    return "Nicht ermittelt"
