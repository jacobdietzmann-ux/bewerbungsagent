from pathlib import Path

import fetch_descriptions


def test_windows_uses_playwright_managed_chromium(monkeypatch):
    monkeypatch.setattr(fetch_descriptions.sys, "platform", "win32")

    assert fetch_descriptions._chromium_executable_path() is None


def test_linux_keeps_system_chromium_when_installed(monkeypatch):
    monkeypatch.setattr(fetch_descriptions.sys, "platform", "linux")
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: self.as_posix() == "/usr/bin/chromium",
    )

    assert fetch_descriptions._chromium_executable_path() == Path("/usr/bin/chromium")
