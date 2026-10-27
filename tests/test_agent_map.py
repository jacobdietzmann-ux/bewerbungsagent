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

    def test_jede_quelle_und_jeder_dienst_hat_einen_knoten(self, mod):
        """Die Listen sind die Wahrheit — ein neuer Provider darf nicht fehlen.

        Vorher standen die Kästen als feste Liste in der Funktion, während
        ``_SRC_SVG``/``_SVC_SVG`` daneben lagen; eine Ergänzung an einer Stelle
        hätte die Karte stillschweigend veraltet gelassen.
        """
        svg = mod._build_system_svg()
        for i in range(len(mod._SRC_SVG)):
            assert f'data-node="src-{i}"' in svg
        for i in range(len(mod._SVC_SVG)):
            assert f'data-node="svc-{i}"' in svg
        assert f'data-node="src-{len(mod._SRC_SVG)}"' not in svg

    def test_hoehe_waechst_mit_der_quellenzahl(self, mod):
        """Neun Quellen brauchen mehr Platz als fünf — sonst fehlt der unterste Kasten."""
        svg = mod._build_system_svg()
        height = int(re.search(r'viewBox="0 0 \d+ (\d+)"', svg).group(1))
        boxes = _rects(svg)
        assert max(y + h for _, y, _, h in boxes) <= height
        assert height > 440


class TestToolchainMap:
    """Arbeitsplatz → GitHub/Drive → Raspberry Pi → Telegram → Handy."""

    def test_renders_svg_with_all_tool_nodes(self, mod):
        svg = mod._build_toolchain_svg()
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        for key, _name, _sub, _status in [t for _title, entries in mod._TOOLCHAIN for t in entries]:
            assert f'data-node="{key}"' in svg, key

    def test_boxes_do_not_overlap(self, mod):
        assert _overlaps(_rects(mod._build_toolchain_svg())) == []

    def test_stays_within_viewbox(self, mod):
        svg = mod._build_toolchain_svg()
        width, height = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups()
        width, height = int(width), int(height)
        for x, y, w, h in _rects(svg):
            assert x + w <= width and y + h <= height, (x, y, w, h)

    def test_jeder_status_hat_eine_legende(self, mod):
        """Ein Kasten mit unbekanntem Status würde die Farbe nicht finden."""
        used = {status for _title, entries in mod._TOOLCHAIN for *_rest, status in entries}
        used |= {status for *_rest, status, _beleg in mod._TOOLS_EXTRA}
        assert used <= set(mod._TOOL_STATUS)

    def test_knoten_haben_detailtexte(self, mod):
        """Jeder Kasten der Grafik braucht einen Eintrag, sonst bleibt der Klick leer."""
        keys = [t[0] for _title, entries in mod._TOOLCHAIN for t in entries]
        for key in keys:
            assert key in mod._TOOL_NODES, key
            assert mod._TOOL_NODES[key].get("title")

    def test_keine_erfundene_verbindung(self, mod):
        """Kanten dürfen nur zwischen existierenden Spalten/Zeilen verlaufen."""
        layout = [
            [(i, j) for j in range(len(entries))]
            for i, (_title, entries) in enumerate(mod._TOOLCHAIN)
        ]
        valid = {node for column in layout for node in column}
        for src, dst in mod._TOOL_EDGES:
            assert src in valid and dst in valid, (src, dst)

    def test_pi_ist_als_gateway_nicht_als_job_runner_gekennzeichnet(self, mod):
        """Der Pi hostet das Telegram-Gateway — der Lauf selbst läuft auf dem PC.

        Diese Unterscheidung ist der eigentliche Punkt der Spalte: der Pi ist
        kein Job-Runner, systemd-Timer für ``tageslauf.sh`` gibt es dort nicht.
        Eine frühere Fassung der Karte behauptete das Gegenteil.
        """
        titles = " ".join(title for title, _entries in mod._TOOLCHAIN)
        assert "PI" in titles
        body = mod._TOOL_NODES["tool-6"]["body"]
        assert "Hermes" in body
        assert "nicht als Job-Runner" in body
        assert "gibt es auf dem Pi nicht" in body
        # Der Ablauf selbst ist dem PC zugeordnet.
        assert "PC" in mod._TOOL_NODES["tool-7"]["title"]


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
        # Fünf Stufen in Richtung Grenze (Standardgrenze 30 min).
        assert mod._commute_color(5) == "#22c55e"     # 17 %
        assert mod._commute_color(15) == "#22c55e"    # genau 50 %
        assert mod._commute_color(22) == "#84cc16"    # 73 %
        assert mod._commute_color(25) == "#f59e0b"    # 83 % (München-Sammelgruppe)
        assert mod._commute_color(28) == "#f97316"    # 93 % (knapp an der Grenze)
        assert mod._commute_color(30) == "#f97316"    # genau an der Grenze
        assert mod._commute_color(31) == "#ef4444"    # darüber
        assert mod._commute_color(None) == "#64748b"

    def test_farbskala_folgt_der_konfigurierten_grenze(self, mod):
        """Bei anderer Grenze wandert die Skala mit — vorher war sie an 30/60 fixiert."""
        assert mod._commute_color(25, 60) == "#22c55e"   # 42 %
        assert mod._commute_color(40, 60) == "#84cc16"   # 67 %
        assert mod._commute_color(50, 60) == "#f59e0b"   # 83 %
        assert mod._commute_color(57, 60) == "#f97316"   # 95 %
        assert mod._commute_color(61, 60) == "#ef4444"

    def test_without_geodata_returns_hint(self, mod):
        svg, meta = mod._build_geo_svg([], {}, 30)
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
        svg, meta = mod._build_geo_svg(apps, cache, 30, home_address=HOME_ADDR)
        assert meta["total"] == 2
        assert "Wohnort" in svg
        assert svg.count("<circle") >= 3  # zwei Stellen + Wohnort


class TestPrintRules:
    """Der PDF-Export braucht Druckregeln im HTML.

    Ohne ``print-color-adjust`` verliert das PDF die farbcodierten Karten, und
    ohne ``break-inside:avoid`` werden Karten mitten durchgeschnitten.
    """

    def test_geodaten_testadresse_ist_neutral(self):
        """Regression: hier standen die echten Wohnkoordinaten als Fixture."""
        assert "Musterstraße" in HOME_ADDR
        assert "48.24" not in HOME_ADDR

    def test_export_pdf_ist_vorhanden_und_konfigurierbar(self, mod):
        import inspect
        sig = inspect.signature(mod.export_pdf)
        assert "landscape" in sig.parameters
        assert sig.parameters["landscape"].default is False

    def test_render_enthaelt_druckregeln(self, mod):
        stats = {
            "kpis": [("Bewerbungen", "1", "in der Datenbank")],
            "stages": [], "commands": [], "filesystem": [], "sources": [],
            "status": {}, "apps": [], "geocache": {}, "limit": 30, "nodes": [],
        }
        html = mod._render(stats, "<svg></svg>", "<svg></svg>",
                           {"total": 0, "home": None, "points": []})
        assert "@media print" in html
        assert "print-color-adjust:exact" in html
        assert "break-inside:avoid" in html


class TestRepoLink:
    """Die geteilte Map/PDF muss auf den nachprüfbaren Quellcode verweisen."""

    def test_fusszeile_enthaelt_repo_link(self, mod):
        stats = {
            "kpis": [], "stages": [], "commands": [], "filesystem": [],
            "sources": [], "status": {}, "apps": [], "geocache": {},
            "limit": 30, "nodes": [],
        }
        html = mod._render(stats, "", "", {"total": 0, "home": None, "points": []})
        assert mod.REPO_URL in html
        assert f'href="{mod.REPO_URL}"' in html

    def test_repo_url_ist_die_oeffentliche_adresse(self, mod):
        assert mod.REPO_URL == "https://github.com/jacobdietzmann-ux/bewerbungsagent"
        assert "{REPO_URL}" not in mod.REPO_URL
