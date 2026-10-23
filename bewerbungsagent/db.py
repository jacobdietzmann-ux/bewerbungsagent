"""SQLite-Persistenz mit Provider-/Nutzer-Feldtrennung (ADR-018).

Ersetzt die monolithische ``data/state.json`` durch eine SQLite-Datenbank
(``data/jobs.db``) mit zwei JSON-Spalten pro Bewerbung:

- ``provider`` — alle Felder aus Suche/Fetch/Matching/Anreicherung/Dokumenten.
  Diese dürfen von einem erneuten Scrape aktualisiert werden.
- ``user``    — alle Felder, die der Nutzer über das Dashboard ändert (Status,
  Kontakt, Notizen, gelöscht, Interview-Datum, …). Diese werden von einem
  erneuten Scrape **niemals** überschrieben (Prinzip aus ``ai-job-scraper``).

Die Identität einer Bewerbung ist ``key`` (die normalisierte URL bzw. der
Firma|Titel-Fallback); sie ist die Primärschlüssel-Spalte der Tabelle.

Das ``Store``-Objekt kapselt Lese-/Schreibzugriff und liefert bewusst dieselbe
Dict-Struktur wie zuvor (``{"applications": [...], "updated": ...}``), damit
Pipeline, Server und Dashboard unverändert mit Dicts arbeiten können.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, Integer, String, Text, create_engine, event, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

from .storage import now_iso

Base = declarative_base()

# Felder, die der Nutzer über das Dashboard (POST /state) ändert und die ein
# erneuter Scrape niemals überschreiben darf.
USER_FIELDS = (
    "status", "contact", "notes", "deleted", "interviewDate",
    "statusChangedAt", "sentAt", "deleted_reason", "deletedAt",
    # Freigabe eines Research-Funds für die Dashboard-Tabelle. Eine bewusste
    # Entscheidung des Nutzers, kein ableitbarer Zustand — deshalb hier und
    # nicht im Provider-Anteil, den ein Suchlauf neu schreiben darf.
    "research_sichtbar",
)

# Status, den ein CLI-Lauf nicht zurückstufen darf: was der Nutzer als
# "erledigt" markiert hat, bleibt erledigt.
_HANDLED_STATUS = ("sent", "followup", "interview", "rejected")

# Marker für eine Löschung durch den Nutzer im Dashboard. Solche Einträge darf
# kein Pipeline-Lauf wieder einblenden; Löschungen des Agenten selbst (Fit-,
# Pendel-, Rollen-Filter) tragen andere Begründungen und bleiben neu bewertbar.
USER_DELETE_REASON = "nutzerkriterium: im dashboard entfernt"

# Nutzerfelder, die ein CLI-Lauf nicht besitzt. Ein Wochenlauf hält den Zustand
# minutenlang im Speicher; Änderungen aus dem Dashboard währenddessen dürfen
# nicht durch den abschließenden Voll-Schreibvorgang verloren gehen. Die DB ist
# die frischere Quelle, deshalb gewinnt sie hier.
_RUN_FOREIGN_FIELDS = ("sentAt", "notes", "contact", "interviewDate", "statusChangedAt",
                       "deletedAt")


def _protected_user(db_user: dict | None, incoming: dict) -> dict:
    """Bewahrt Nutzerfelder, die der laufende Prozess nicht gesetzt hat."""
    merged = dict(incoming or {})
    db = dict(db_user or {})
    for k in _RUN_FOREIGN_FIELDS:
        if db.get(k) not in (None, ""):
            merged[k] = db[k]
    # Im Dashboard gelöschte Stellen bleiben gelöscht: der Lauf kennt das Flag
    # nicht und hätte es sonst stillschweigend zurückgesetzt — die Zahlen in der
    # Statistik sprangen dadurch nach dem nächsten Lauf zurück. Die Löschung ist
    # an ``deleted_reason`` erkennbar; Filter-Löschungen der Pipeline (ohne
    # diesen Marker) bleiben weiterhin neu bewertbar.
    reason = str(db.get("deleted_reason") or "").lower()
    if db.get("deleted") is True and reason.startswith(USER_DELETE_REASON):
        merged["deleted"] = True
        merged["deleted_reason"] = db["deleted_reason"]
    if db.get("status") in _HANDLED_STATUS and merged.get("status") not in _HANDLED_STATUS:
        merged["status"] = db["status"]
    return merged


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False, index=True)
    provider = Column(JSON, nullable=False, default=dict)
    user = Column(JSON, nullable=False, default=dict)
    created_at = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=True)


class Meta(Base):
    __tablename__ = "meta"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


def _split(app: dict) -> tuple[dict, dict]:
    """Zerlegt einen Anwendungs-Dict in Provider- und Nutzer-Anteil."""
    provider: dict[str, Any] = {}
    user: dict[str, Any] = {}
    for k, v in (app or {}).items():
        if k == "key":
            continue  # Identität liegt in der PK-Spalte
        if k in USER_FIELDS:
            user[k] = v
        else:
            provider[k] = v
    return provider, user


def _merge(key: str, provider: dict, user: dict) -> dict:
    """Setzt Provider- und Nutzer-Anteil wieder zu einem Dict zusammen."""
    out = dict(provider or {})
    out["key"] = key
    out.update(user or {})
    return out


class Store:
    """SQLite-Backend mit Dict-kompatibler Schnittstelle."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._guard_production_db()
        url = f"sqlite:///{self.path}"
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            future=True,
        )
        self._configure_sqlite()
        self._ensure_schema(url)
        self._Session = sessionmaker(bind=self.engine, future=True)

    def _guard_production_db(self) -> None:
        """Verhindert, dass ein Testlauf die produktive Datenbank beschreibt.

        ``save_state`` ersetzt den gesamten Bestand. Griff ein Test versehentlich
        auf die echte DB zu, wurde sie auf die Testdaten reduziert (342
        Bewerbungen → 1 Testeintrag). Die Pfad-Auflösung in ``Config`` schließt
        das schon aus; diese Sperre ist die zweite Verteidigungslinie.
        """
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            return
        prod = os.environ.get("BEWERBUNGSAGENT_DB", "").strip()
        if not prod:
            return
        try:
            if self.path.expanduser().resolve() == Path(prod).expanduser().resolve():
                raise RuntimeError(
                    "Testlauf darf nicht die produktive Datenbank verwenden: " + str(self.path)
                )
        except OSError:  # pragma: no cover - Pfad nicht auflösbar
            return

    def _configure_sqlite(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _set_pragmas(dbapi_conn, _record):  # pragma: no cover - sqlite intern
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    def _ensure_schema(self, url: str) -> None:
        """Legt das Schema per Alembic an, falls noch nicht vorhanden."""
        if inspect(self.engine).has_table("applications"):
            return
        from alembic import command
        from alembic.config import Config as AlembicConfig

        root = Path(__file__).resolve().parent.parent
        cfg = AlembicConfig(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "migrations"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")

    # ---- Lesen -----------------------------------------------------------

    def load_state(self) -> dict:
        """Lädt alle Bewerbungen als ``{"applications": [...], "updated": ...}``."""
        with self._Session() as session:
            rows = session.query(Application).all()
            apps = [_merge(r.key, r.provider, r.user) for r in rows]
            updated = session.get(Meta, "updated")
        return {"applications": apps, "updated": updated.value if updated else ""}

    def get_overlay(self) -> dict:
        """Liefert nur die Nutzer-Felder als ``{key: {…}}`` (für GET /state)."""
        with self._Session() as session:
            rows = session.query(Application).all()
            return {r.key: dict(r.user or {}) for r in rows if r.user}

    # ---- Meta ------------------------------------------------------------

    def get_meta(self, key: str, default=None):
        """Liest einen Wert aus der ``meta``-Tabelle."""
        with self._Session() as session:
            row = session.get(Meta, key)
        if row is None or row.value is None:
            return default
        try:
            return json.loads(row.value)
        except (ValueError, TypeError):
            return row.value

    def set_meta(self, key: str, value) -> None:
        """Schreibt einen JSON-Wert in die ``meta``-Tabelle."""
        with self._Session() as session:
            session.merge(Meta(key=key, value=json.dumps(value, ensure_ascii=False)))
            session.commit()

    # ---- Schreiben -------------------------------------------------------

    def save_state(self, state: dict) -> None:
        """Ersetzt den gesamten Bestand atomar.

        Alle im Dict enthaltenen Bewerbungen werden eingefügt/aktualisiert;
        alle **nicht** mehr enthaltenen Keys werden gelöscht (Voll-Replace).
        ``updated`` wird in der ``meta``-Tabelle geführt."""
        apps = state.get("applications", []) if isinstance(state, dict) else []
        now = state.get("updated") if isinstance(state, dict) else now_iso()
        with self._Session() as session:
            existing = {r.key: r for r in session.query(Application).all()}
            keep_keys: set[str] = set()
            for app in apps:
                key = app.get("key") or _fallback_key(app)
                if not key:
                    continue
                keep_keys.add(key)
                provider, user = _split(app)
                row = existing.get(key)
                if row is None:
                    session.add(Application(
                        key=key, provider=provider, user=user,
                        created_at=provider.get("created") or now,
                        updated_at=now,
                    ))
                else:
                    provider, user = _split(app)
                    row.provider = provider
                    row.user = _protected_user(row.user, user)
                    row.updated_at = now
            # Nicht mehr enthaltene Einträge entfernen (Voll-Replace).
            for key, row in existing.items():
                if key not in keep_keys:
                    session.delete(row)
            session.merge(Meta(key="updated", value=now))
            session.commit()

    def apply_overlay(self, overlay: dict) -> None:
        """Übernimmt Nutzer-Feldänderungen aus dem Dashboard (POST /state).

        Schreibt ausschließlich in die ``user``-Spalte; Provider-Felder bleiben
        garantiert unangetastet.
        """
        if not isinstance(overlay, dict):
            return
        now = now_iso()
        with self._Session() as session:
            rows = {r.key: r for r in session.query(Application).all()}
            changed = False
            for key, entry in overlay.items():
                if not isinstance(entry, dict):
                    continue
                row = rows.get(key)
                if row is None:
                    continue
                user = dict(row.user or {})
                for k, v in entry.items():
                    if k in USER_FIELDS and v is not None:
                        user[k] = v
                row.user = user
                row.updated_at = now
                changed = True
            if changed:
                session.merge(Meta(key="updated", value=now))
            session.commit()

    # ---- Export ----------------------------------------------------------

    def export_json(self, path: str | Path) -> None:
        """Schreibt einen bisync-sicheren JSON-Snapshot (abgeleitet, für Backup)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.load_state(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(target)


def _fallback_key(app: dict) -> str:
    """Firma|Titel-Fallback, falls kein expliziter ``key`` gesetzt ist."""
    from .profile import normalize
    url = normalize(app.get("url", ""))
    if url:
        return url
    return normalize(f"{app.get('firma', '')}|{app.get('titel', '')}")
