"""Aufräumen von Bewerbungsordnern (01_Bewerbungen/<Firma> - <Titel>/).

Zwei Regeln bestimmen, was gelöscht wird:

1. Stellen, die im Dashboard als ``deleted`` markiert sind (FIT < 50 %).
2. Stellen mit Status ``rejected``, deren Anzeigen-/Bewerbungsdatum älter als
   ``max_age_days`` (Standard 60) ist.

Aktive Stellen (interview, followup, sent, docs, research) bleiben unangetastet,
auch wenn sie schon älter sind. Gelöschte Ordner werden statt hart zu löschen in
ein Trash-Verzeichnis verschoben (``data/trash/<zeitstempel>/``), damit der
Vorgang reversibel bleibt.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import time
from pathlib import Path

from .storage import load_json, now_iso, save_json

_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d")


def _parse_date(value) -> _dt.date | None:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(v[:10] if fmt == "%Y-%m-%d" else v, fmt).date()
        except ValueError:
            continue
    return None


def app_date(app: dict) -> _dt.date | None:
    """Bestes verfügbares „Alter" einer Bewerbung: gefunden > gesendet > erstellt."""
    for field in ("datum", "sentAt", "created"):
        d = _parse_date(app.get(field))
        if d:
            return d
    return None


def folder_for(app: dict, bewerbungen_dir: Path) -> Path:
    """Ordnerpfad einer Stelle, abgeleitet aus den Dokument-Links oder dem Namen."""
    docs = app.get("dokumente") or {}
    for rel in docs.values():
        if rel:
            # rel zeigt z. B. auf ../01_Bewerbungen/<Ordner>/<Datei>.pdf
            parent = os.path.dirname(str(rel))
            folder_name = os.path.basename(parent)
            return (bewerbungen_dir / folder_name).resolve()
    name = _safe_name(f"{app.get('firma', '')} - {app.get('titel', '')}")
    return (bewerbungen_dir / name).resolve()


def _safe_name(value: str) -> str:
    import re
    s = re.sub(r'[\\/:*?"<>|]', "-", value or "stelle")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80].strip()


def collect_cleanup(state: dict, bewerbungen_dir: Path, max_age_days: int = 60) -> list[dict]:
    """Liefert die Liste der zu löschenden Ordner (ohne sie zu löschen)."""
    today = _dt.date.today()
    cutoff = today - _dt.timedelta(days=max_age_days)
    apps = state.get("applications", []) if isinstance(state, dict) else []

    result: list[dict] = []
    seen: set[str] = set()
    for app in apps:
        key = app.get("key") or f"{app.get('firma', '')}|{app.get('titel', '')}"
        if key in seen:
            continue

        folder = folder_for(app, bewerbungen_dir)
        if not folder.is_dir():
            continue

        reason = ""
        if app.get("deleted"):
            reason = "FIT < 50 % (gelöscht)"
        elif app.get("status") == "rejected":
            d = app_date(app)
            if d and d < cutoff:
                reason = f"abgelehnt, älter als {max_age_days} Tage (gefunden {d.isoformat()})"

        if reason:
            seen.add(key)
            result.append({
                "key": key,
                "firma": app.get("firma"),
                "titel": app.get("titel"),
                "status": app.get("status"),
                "reason": reason,
                "folder": str(folder),
            })

    result.sort(key=lambda r: (r["firma"] or "", r["titel"] or ""))
    return result


def run_cleanup(config, dry_run: bool = True, max_age_days: int = 60) -> dict:
    """Sammelt und (optional) löscht/verschiebt die Bewerbungsordner.

    Rückgabe: ``{"dry_run", "to_delete", "folders": [...]}``.
    """
    state = load_json(config.state_path(), {"applications": []})
    folders = collect_cleanup(state, config.bewerbungen_dir, max_age_days=max_age_days)

    if dry_run:
        return {"dry_run": True, "to_delete": len(folders), "folders": folders}

    trash_root = config.data_dir / "trash" / time.strftime("%Y%m%d-%H%M%S")
    trash_root.mkdir(parents=True, exist_ok=True)

    moved = []
    for f in folders:
        src = Path(f["folder"])
        if not src.is_dir():
            continue
        dst = trash_root / src.name
        if dst.exists():
            dst = trash_root / f"{src.name}__{len(moved)}"
        shutil.move(str(src), str(dst))
        f["moved_to"] = str(dst)
        moved.append(f)

    # Dokument-Referenzen im State entfernen, damit das Dashboard keine
    # ins Leere zeigenden Links mehr anzeigt.
    state = load_json(config.state_path(), {"applications": []})
    moved_keys = {f["key"] for f in moved}
    for a in state.get("applications", []):
        key = a.get("key") or f"{a.get('firma', '')}|{a.get('titel', '')}"
        if key in moved_keys and a.get("dokumente"):
            a["dokumente"] = {}
            a["cleanup_at"] = now_iso()
    save_json(config.state_path(), state)

    return {"dry_run": False, "to_delete": len(folders), "moved": len(moved),
            "trash": str(trash_root), "folders": folders}
