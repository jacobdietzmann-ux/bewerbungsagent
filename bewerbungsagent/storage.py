"""Persistenz-Helfer: JSON lesen/schreiben und Zeitstempel."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
