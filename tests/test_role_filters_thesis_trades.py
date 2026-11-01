"""Filterlücken aus dem Bestand (01.11.2026).

„Master Thesis – … Agentic AI" stand mit 66 % als Neufund im Dashboard, und für
„Elektroniker" waren bei 72 % schon Unterlagen erzeugt. Abschlussarbeiten und
Ausbildungsberufe sind für einen Diplom-Ingenieur keine Zielrollen.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.matching import is_student_role, is_technician_role


@pytest.mark.parametrize("titel", [
    "Master Thesis - Development of Trustworthy Agentic AI (f/m/div)",
    "Masterthesis in the field Sound Based Predictive Maintenance",
    "Bachelor/ Master Thesis - Implementation of a Latch-Based Register File",
    "Masterarbeit: Strukturmechanik",
    "Abschlussarbeit im Bereich System Integration (m/w/d)",
    "PHD Thesis: Quantum Sensing for Navigation (d/f/m)",
    "Doktorand Batteriesysteme (m/w/d)",
])
def test_abschlussarbeiten_sind_studentenrollen(titel):
    assert is_student_role(titel)


@pytest.mark.parametrize("titel", [
    "Testingenieur HiL (m/w/d)",
    "Systems Engineer Thermal Management",
    "Senior Test Engineer",
])
def test_ingenieursrollen_bleiben_frei(titel):
    assert not is_student_role(titel)
    assert not is_technician_role(titel)


@pytest.mark.parametrize("titel", [
    "Mechatroniker/Elektroniker in der Instandhaltung/Wartung m/f/d",
    "Kfz-Mechatroniker m/w/d in VZ/TZ",
    "Elektroniker",
    "Elektroniker Prüffeld (m/w/d) in Vollzeit (40h/Woche)",
    "Karosserie- und Fahrzeugbaumechaniker (m/w/d)",
    "Mechatroniker / Monteur Neufertigung (all gender)",
])
def test_ausbildungsberufe_sind_technikerrollen(titel):
    assert is_technician_role(titel)


@pytest.mark.parametrize("titel", [
    "Elektronikentwickler (m/w/d)",
    "Entwicklungsingenieur Elektronik (m/w/d)",
    "Ingenieur Mechanik / Strukturberechnung",
    "Mechatronik-Ingenieur Testsysteme",
])
def test_ingenieure_mit_aehnlichen_woertern_bleiben_frei(titel):
    assert not is_technician_role(titel)
