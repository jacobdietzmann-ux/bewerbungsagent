"""Kanonische Status-Werte (5-Stufen-Funnel), angelehnt an das alte Dashboard.

Der Funnel: research -> docs -> sent -> interview, Endstatus rejected.
Alle früheren/abweichenden Statuswerte werden über ``normalize_status`` darauf abgebildet.
"""

from __future__ import annotations

STATUS = {
    "research":  {"label": "Research",           "cls": "s-research",  "color": "#64748b"},
    "docs":      {"label": "Dokumente erstellt", "cls": "s-docs",      "color": "#3b82f6"},
    "sent":      {"label": "Versendet",          "cls": "s-sent",      "color": "#a78bfa"},
    "interview": {"label": "Interview",          "cls": "s-interview", "color": "#22c55e"},
    "rejected":  {"label": "Abgelehnt/Abgelaufen", "cls": "s-rejected", "color": "#ef4444"},
}

ORDER = ["research", "docs", "sent", "interview", "rejected"]

# Abbildung alter/abweichender Statuswerte auf den kanonischen Funnel.
LEGACY_STATUS_MAP = {
    # research
    "neu": "research", "passend": "research", "research": "research",
    # docs
    "dokumente_erstellt": "docs", "docs": "docs",
    # sent
    "beworben": "sent", "sent": "sent", "applied": "sent",
    # Die frühere Stufe „Follow-up“ ist entfallen; Nachfassen steht in ``nachgefasstAm``.
    "antwort": "sent", "followup": "sent",
    # interview (positive Endzustände wie Zusage/Angebot zählen als Interview-Erfolg)
    "interview": "interview", "zusage": "interview", "offer": "interview",
    # rejected
    "absage": "rejected", "rejected": "rejected", "archiviert": "rejected",
}


def normalize_status(status: str | None) -> str:
    if not status:
        return "research"
    return LEGACY_STATUS_MAP.get(status, status if status in STATUS else "research")
