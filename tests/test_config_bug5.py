"""Funktionstests für Bug 5 Fix: config.py Methoden für persönliche Daten."""

import json
import tempfile
from pathlib import Path

from bewerbungsagent.config import Config, DEFAULT_HEADLINE_DE, DEFAULT_DOC_NAMES


def test_personal_name():
    cfg_data = {
        'documents': {
            'personal': {'name': 'Jacob Dietzmann'},
            'doc_names': {},
        }
    }
    tmp = tempfile.mktemp(suffix='.json')
    Path(tmp).write_text(json.dumps(cfg_data), encoding='utf-8')
    try:
        config = Config(Path(tmp))
        assert config.personal_name() == 'Jacob Dietzmann'
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_personal_first_last():
    cfg_data = {
        'documents': {
            'personal': {'name': 'Jacob Dietzmann'},
            'doc_names': {},
        }
    }
    tmp = tempfile.mktemp(suffix='.json')
    Path(tmp).write_text(json.dumps(cfg_data), encoding='utf-8')
    try:
        config = Config(Path(tmp))
        first, last = config._personal_first_last()
        assert first == 'Jacob'
        assert last == 'Dietzmann'
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_headline_de():
    cfg_data = {
        'documents': {
            'personal': {
                'headline_de': 'Testingenieur · Testkoordinator',
                'headline_en': 'Test Engineer',
            },
            'doc_names': {},
        }
    }
    tmp = tempfile.mktemp(suffix='.json')
    Path(tmp).write_text(json.dumps(cfg_data), encoding='utf-8')
    try:
        config = Config(Path(tmp))
        assert config.headline('de') == 'Testingenieur · Testkoordinator'
        assert config.headline('en') == 'Test Engineer'
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_headline_chip():
    cfg_data = {
        'documents': {
            'personal': {
                'headline_chip_de': 'Hardware- & Embedded-Ingenieur',
                'headline_chip_en': 'Hardware & Embedded Engineer',
            },
            'doc_names': {},
        }
    }
    tmp = tempfile.mktemp(suffix='.json')
    Path(tmp).write_text(json.dumps(cfg_data), encoding='utf-8')
    try:
        config = Config(Path(tmp))
        assert config.headline('de', chip=True) == 'Hardware- & Embedded-Ingenieur'
        assert config.headline('en', chip=True) == 'Hardware & Embedded Engineer'
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_doc_names_de():
    cfg_data = {
        'documents': {
            'personal': {'name': 'Jacob Dietzmann'},
            'doc_names': {
                'de': {
                    'anschreiben': 'Anschreiben_{firstname}_{lastname}.pdf',
                    'lebenslauf': 'Lebenslauf_{firstname}_{lastname}.pdf',
                },
            },
        }
    }
    tmp = tempfile.mktemp(suffix='.json')
    Path(tmp).write_text(json.dumps(cfg_data), encoding='utf-8')
    try:
        config = Config(Path(tmp))
        names = config.doc_names('de')
        assert names['anschreiben'] == 'Anschreiben_Jacob_Dietzmann.pdf'
        assert names['lebenslauf'] == 'Lebenslauf_Jacob_Dietzmann.pdf'
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_doc_names_en():
    cfg_data = {
        'documents': {
            'personal': {'name': 'Jacob Dietzmann'},
            'doc_names': {
                'en': {
                    'anschreiben': 'Cover_Letter_{firstname}_{lastname}_EN.pdf',
                    'lebenslauf': 'CV_{firstname}_{lastname}_EN.pdf',
                },
            },
        }
    }
    tmp = tempfile.mktemp(suffix='.json')
    Path(tmp).write_text(json.dumps(cfg_data), encoding='utf-8')
    try:
        config = Config(Path(tmp))
        names = config.doc_names('en')
        assert names['anschreiben'] == 'Cover_Letter_Jacob_Dietzmann_EN.pdf'
        assert names['lebenslauf'] == 'CV_Jacob_Dietzmann_EN.pdf'
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_empty_config_fallback():
    """Leere Config sollte keine Abstürze verursachen."""
    cfg_data = {'documents': {'personal': {}, 'doc_names': {}}}
    tmp = tempfile.mktemp(suffix='.json')
    Path(tmp).write_text(json.dumps(cfg_data), encoding='utf-8')
    try:
        config = Config(Path(tmp))
        assert config.personal_name() == ''
        assert config.headline('de') == DEFAULT_HEADLINE_DE  # Fallback auf Default
        assert config.doc_names('de') == DEFAULT_DOC_NAMES['de']  # Fallback auf Default
    finally:
        Path(tmp).unlink(missing_ok=True)