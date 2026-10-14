"""Tests für die Agenten-Map (``scripts/build_agent_map.py``).

Geprüft werden die reinen Aufbaufunktionen: Sie erzeugen valides SVG, halten
das Raster ein (keine überlappenden Kästen) und kommen mit fehlenden
Geodaten zurecht.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_agent_map.py"

# Neutrale Testadresse — die echte Wohnadresse gehört nicht ins Repo.
HOME_ADDR = "Musterstraße 1, 12345 Musterstadt"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("build_agent_map", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_agent_map"] = module
    spec.loader.exec_module(module)
    return module


def _rects(svg: str, min_height: int = 11) -> list[tuple[int, int, int, int]]:
    found = re.findall(
        r'<rect x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"', svg
    )
    # Der 4 px hohe Akzentbalken liegt bewusst auf der Stufen-Box.
    return [(int(a), int(b), int(c), int(d)) for a, b, c, d in found if int(d) >= min_height]


def _overlaps(boxes):
    def hit(a, b):
        return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
                    or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])

    return [(boxes[i], boxes[j]) for i in range(len(boxes))
            for j in range(i + 1, len(boxes)) if hit(boxes[i], boxes[j])]


class TestSystemMap:
    def test_renders_svg_with_all_nodes(self, mod):
        svg = mod._build_system_svg()
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        for key in ("search", "match", "generate", "dashboard"):
            assert f'data-node="{key}"' in svg
        for key in ("src-0", "src-4", "out-0", "out-3", "svc-0", "svc-4"):
            assert f'data-node="{key}"' in svg

    def test_boxes_do_not_overlap(self, mod):
        boxes = _rects(mod._build_system_svg())
        assert len(boxes) >= 14
        assert _overlaps(boxes) == []

    def test_stays_within_viewbox(self, mod):
        svg = mod._build_system_svg()
        width, height = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups()
        width, height = int(width), int(height)
        for x, y, w, h in _rects(svg):
            assert x >= 0 and y >= 0
            assert x + w <= width, f"Box ragt rechts heraus: {x}+{w} > {width}"
            assert y + h <= height, f"Box ragt unten heraus: {y}+{h} > {height}"


class TestGeoMap:
    def test_projection_keeps_points_inside_bbox(self, mod):
        f = mod._project(
            [(48.13, 11.57), (48.25, 11.65), (48.06, 11.66), (48.24, 11.65)],
            width=1000, height=600,
        )
        for lat, lon in [(48.13, 11.57), (48.25, 11.65), (48.06, 11.66)]:
            x, y = f(lat, lon)
            assert 0 <= x <= 1000 and 0 <= y <= 600

    def test_commute_colours(self, mod):
        assert mod._commute_color(10) == "#22c55e"
        assert mod._commute_color(91) == "#ef4444"
        assert mod._commute_color(None) == "#64748b"

    def test_without_geodata_returns_hint(self, mod):
        svg, meta = mod._build_geo_svg([], {}, 90)
        assert "Keine Geodaten" in svg
        assert meta["total"] == 0

    def test_plots_jobs_with_coordinates(self, mod):
        apps = [
            {"ort": "München", "pendel_modus": "Auto", "pendelzeit_min": 25},
            {"ort": "Ismaning", "pendel_modus": "Auto", "pendelzeit_min": 30},
        ]
        cache = {
            HOME_ADDR: {"lat": 48.1000, "lon": 11.5000},
            "munchen": {"lat": 48.1371, "lon": 11.5754},
            "ismaning": {"lat": 48.2492, "lon": 11.6521},
        }
        svg, meta = mod._build_geo_svg(apps, cache, 90, home_address=HOME_ADDR)
        assert meta["total"] == 2
        assert "Wohnort" in svg
        assert svg.count("<circle") >= 3  # zwei Stellen + Wohnort
