"""Selbstheilung beim fehlenden Playwright-Browser (``search/browser.py``)."""

from __future__ import annotations

import subprocess

import pytest

from bewerbungsagent.search import browser

FEHLER = RuntimeError("BrowserType.launch: Executable doesn't exist at X "
                      "Please run the following command: playwright install")


class FakeChromium:
    def __init__(self, fails: int, error: Exception = FEHLER):
        self.fails, self.error, self.calls = fails, error, 0

    def launch(self, **_kw):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.error
        return "browser"


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(browser, "_install_versucht", False)
    monkeypatch.delenv("BEWERBUNGSAGENT_NO_AUTOINSTALL", raising=False)


def _run_ok(monkeypatch, record):
    def fake_run(cmd, **_kw):
        record.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(browser.subprocess, "run", fake_run)


def test_fehlender_browser_wird_installiert_und_erneut_gestartet(monkeypatch):
    calls: list = []
    _run_ok(monkeypatch, calls)
    chromium = FakeChromium(fails=1)
    assert browser._launch(FakePlaywright(chromium), headed=False) == "browser"
    assert chromium.calls == 2
    assert calls and calls[0][-2:] == ["install", "chromium"]


def test_installation_nur_einmal_pro_prozess(monkeypatch):
    calls: list = []
    _run_ok(monkeypatch, calls)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            browser._launch(FakePlaywright(FakeChromium(fails=5)), headed=False)
    assert len(calls) == 1


def test_fremde_fehler_loesen_keine_installation_aus(monkeypatch):
    calls: list = []
    _run_ok(monkeypatch, calls)
    with pytest.raises(RuntimeError, match="boom"):
        browser._launch(FakePlaywright(FakeChromium(5, RuntimeError("boom"))), False)
    assert calls == []


def test_fehlgeschlagene_installation_reicht_urspruenglichen_fehler_weiter(monkeypatch):
    monkeypatch.setattr(browser.subprocess, "run",
                        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 1, "", "kein Netz"))
    with pytest.raises(RuntimeError, match="Executable doesn't exist"):
        browser._launch(FakePlaywright(FakeChromium(fails=5)), headed=False)


def test_abschaltbar_per_umgebungsvariable(monkeypatch):
    calls: list = []
    _run_ok(monkeypatch, calls)
    monkeypatch.setenv("BEWERBUNGSAGENT_NO_AUTOINSTALL", "1")
    with pytest.raises(RuntimeError):
        browser._launch(FakePlaywright(FakeChromium(fails=5)), headed=False)
    assert calls == []
