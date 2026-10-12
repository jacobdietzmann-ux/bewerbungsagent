"""Gemeinsame Test-Fixtures.

Alle Tests laufen gegen ein *anonymisiertes* Demo-Profil
(``tests/fixtures/profil-demo.json``), damit niemals echte Personendaten in
Testartefakte oder Repo-Historien gelangen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungsagent.profile import Profile

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def demo_profile_data() -> dict:
    return json.loads((FIXTURES / "profil-demo.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def demo_profile(demo_profile_data: dict) -> Profile:
    return Profile(demo_profile_data)


@pytest.fixture
def tmp_config(tmp_path: Path, demo_profile_data: dict) -> dict:
    """Minimale, testbare Config-Struktur (wie ``config.json``)."""
    profile_path = tmp_path / "profil-demo.json"
    profile_path.write_text(json.dumps(demo_profile_data, ensure_ascii=False), encoding="utf-8")
    return {
        "profile_json": str(profile_path),
        "data_dir": str(tmp_path / "data"),
        "output_dir": str(tmp_path / "output"),
        "dashboard_file": str(tmp_path / "dashboard.html"),
        "search": {"enabled": False, "providers": [], "location": "München", "query_terms": []},
        "documents": {"languages": ["de", "en"], "accent_color": "#0B3D5C",
                      "min_fit_for_generation": "mittel"},
    }
