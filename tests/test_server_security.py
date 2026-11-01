"""Sicherheit des lokalen Dashboard-Servers.

Hintergrund: Der Server schickte ``Access-Control-Allow-Origin: *`` und lieferte
den kompletten Bewerbungsordner statisch aus. Jede im Browser geöffnete
Webseite konnte damit ``/state`` lesen und überschreiben (POST mit
``text/plain`` braucht keinen Preflight) und ``04_Agent/config.json`` abrufen.
"""

from __future__ import annotations

import http.client
import threading

import pytest

import server


class TestHelpers:
    def test_host_nur_lokal(self):
        assert server.host_allowed(f"127.0.0.1:{server.PORT}")
        assert server.host_allowed(f"localhost:{server.PORT}")
        assert not server.host_allowed("evil.example:8766")
        assert not server.host_allowed(None)

    def test_origin(self):
        assert server.origin_allowed(None)  # gleiche Herkunft / curl
        assert server.origin_allowed("null")  # file://
        assert server.origin_allowed(f"http://127.0.0.1:{server.PORT}")
        assert not server.origin_allowed("https://evil.example")

    @pytest.mark.parametrize("pfad", [
        "/04_Agent/config.json",
        "/04_Agent/config.json.pre-xing-20261023-132414",
        "/04_Agent/data/state.json",
        "/04_Agent/data/jobs.db",
        "/04_AGENT/Config.json",
        "/04_Agent/./config.json",
        "/04_Agent/%63onfig.json",
        "/irgendwo/jobs.db-wal",
        "/04_Agent/.git/config",
    ])
    def test_sensible_pfade_gesperrt(self, pfad):
        assert server.path_blocked(pfad)

    @pytest.mark.parametrize("pfad", [
        "/00_Dashboard/dashboard.html",
        "/01_Bewerbungen/Firma - Titel/Anschreiben.pdf",
        "/04_Agent/output/Firma/Lebenslauf.pdf",
    ])
    def test_normale_pfade_erlaubt(self, pfad):
        assert not server.path_blocked(pfad)


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    (tmp_path / "04_Agent").mkdir()
    (tmp_path / "04_Agent" / "config.json").write_text('{"geheim": 1}', encoding="utf-8")
    (tmp_path / "00_Dashboard").mkdir()
    (tmp_path / "00_Dashboard" / "info.txt").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(server, "ROOT", str(tmp_path))
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    monkeypatch.setattr(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}, raising=False)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port
    httpd.shutdown()
    httpd.server_close()


def _get(port, path, headers=None, method="GET", body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    data = r.read()
    hdrs = dict(r.getheaders())
    conn.close()
    return r.status, hdrs, data


class TestLive:
    def test_statische_datei_ohne_wildcard_cors(self, live_server):
        status, hdrs, body = _get(live_server, "/00_Dashboard/info.txt")
        assert status == 200 and body == b"ok"
        assert "Access-Control-Allow-Origin" not in hdrs

    def test_config_wird_nicht_ausgeliefert(self, live_server):
        status, _, body = _get(live_server, "/04_Agent/config.json")
        assert status == 404
        assert b"geheim" not in body

    def test_fremde_origin_wird_abgewiesen(self, live_server):
        status, hdrs, _ = _get(live_server, "/00_Dashboard/info.txt",
                               headers={"Origin": "https://evil.example"})
        assert status == 403
        assert "Access-Control-Allow-Origin" not in hdrs

    def test_post_von_fremder_seite_wird_abgewiesen(self, live_server):
        status, _, _ = _get(live_server, "/state", method="POST", body=b"{}",
                            headers={"Origin": "https://evil.example",
                                     "Content-Type": "text/plain"})
        assert status == 403

    def test_dns_rebinding_wird_abgewiesen(self, live_server):
        status, _, _ = _get(live_server, "/00_Dashboard/info.txt",
                            headers={"Host": "evil.example"})
        assert status == 403

    def test_file_origin_bekommt_cors(self, live_server):
        status, hdrs, _ = _get(live_server, "/00_Dashboard/info.txt",
                               headers={"Origin": "null"})
        assert status == 200
        assert hdrs.get("Access-Control-Allow-Origin") == "null"

    def test_zu_grosser_body(self, live_server):
        status, _, _ = _get(live_server, "/state", method="POST", body=b"{}",
                            headers={"Content-Length": str(server.MAX_BODY_BYTES + 1)})
        assert status == 413
