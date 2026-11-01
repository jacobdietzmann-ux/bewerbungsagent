"""Tests für mehrdeutige Ortsnamen und Regionsangaben im Pendelweg.

Hintergrund: „Vierkirchen" gibt es in Oberbayern (85256) und in Sachsen;
Nominatim liefert den ersten Treffer — die MicroNova-Stelle bekam 529 km und
306 Minuten statt ~30 km. „München Area" fiel auf eine Straße in Sibiu (980 km).
"""

from __future__ import annotations

from bewerbungsagent.commute import (_nearest, _haversine_km, _strip_noise,
                                    resolve_office)

HOME = {"lat": 48.1953, "lon": 11.6528}          # Garching bei München
VIERKIRCHEN_BAYERN = {"lat": 48.3517, "lon": 11.4653}
VIERKIRCHEN_SACHSEN = {"lat": 51.2167, "lon": 14.7833}
MUNICH = {"lat": 48.1374, "lon": 11.5755}


class TestRegionsangaben:
    def test_muenchen_area_wird_zu_muenchen(self):
        assert _strip_noise("München Area") == "München"
        assert resolve_office("München Area") == "München"

    def test_region_praefix(self):
        assert _strip_noise("Region München") == "München"

    def test_umgebung(self):
        assert _strip_noise("München Umgebung") == "München"

    def test_echter_ortsname_bleibt(self):
        assert _strip_noise("Vierkirchen") == "Vierkirchen"


class TestDistance:
    def test_vierkirchen_bayern_ist_nah(self):
        assert _haversine_km(HOME, VIERKIRCHEN_BAYERN) < 40

    def test_vierkirchen_sachsen_ist_weit(self):
        assert _haversine_km(HOME, VIERKIRCHEN_SACHSEN) > 300

    def test_nearest_waehlt_den_namen_nahen_ort(self):
        kandidaten = [VIERKIRCHEN_SACHSEN, VIERKIRCHEN_BAYERN]
        assert _nearest(kandidaten, HOME) is VIERKIRCHEN_BAYERN

    def test_naehe_gewinnt_gegen_zentrum(self):
        # München liegt 13 km entfernt, Vierkirchen 20 km — die Funktion nimmt
        # den nächstgelegenen Punkt, nicht den „wichtigsten".
        assert _nearest([VIERKIRCHEN_BAYERN, MUNICH], HOME) is MUNICH

    def test_nearest_ohne_treffer(self):
        assert _nearest([], HOME) is None
