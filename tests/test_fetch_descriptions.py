from pathlib import Path

from bewerbungsagent.search import browser


def test_windows_uses_playwright_managed_chromium(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "win32")

    assert browser._chromium_executable_path() is None


def test_linux_keeps_system_chromium_when_installed(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: self.as_posix() == "/usr/bin/chromium",
    )

    assert browser._chromium_executable_path() == Path("/usr/bin/chromium")
