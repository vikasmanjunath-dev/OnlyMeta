"""TLS: the demo CA tool, strict verification, hostname checking, and the collector's explicit CA bundle (an impostor server is refused)."""
import asyncio
import http.server
import ssl
import sys
import threading
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.config import load_settings  # noqa: E402
from collector.pipeline import Pipeline  # noqa: E402
from collector.sender import Sender  # noqa: E402
from tools.make_cert import make  # noqa: E402


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@pytest.fixture
def server(tmp_path):
    c = make(tmp_path / "tls")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(c["cert"], c["key"])
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield c, srv.server_address[1], tmp_path
    srv.shutdown()


def test_cert_chain_passes_strict_verification_for_loopback_names(server):
    c, port, _ = server
    for host in ("127.0.0.1", "localhost"):
        with ssl.create_default_context(cafile=c["ca"]).wrap_socket(__import__("socket").create_connection(("127.0.0.1", port)), server_hostname=host) as s:
            assert s.version() in ("TLSv1.2", "TLSv1.3")


def test_wrong_ca_and_wrong_hostname_are_refused(server):
    import socket
    c, port, tmp = server
    other = make(tmp / "other")
    with pytest.raises(ssl.SSLCertVerificationError):
        ssl.create_default_context(cafile=other["ca"]).wrap_socket(socket.create_connection(("127.0.0.1", port)), server_hostname="127.0.0.1")
    with pytest.raises(ssl.SSLCertVerificationError):
        ssl.create_default_context(cafile=c["ca"]).wrap_socket(socket.create_connection(("127.0.0.1", port)), server_hostname="example.com")


def test_private_key_is_not_world_readable(server):
    c, _, _ = server
    assert oct(Path(c["key"]).stat().st_mode & 0o777) == "0o600"


def test_ca_bundle_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CA_BUNDLE", "/x/ca.pem")
    assert load_settings(db_path=str(tmp_path / "c.db")).ca_bundle == "/x/ca.pem"
    monkeypatch.delenv("CA_BUNDLE")
    assert load_settings(db_path=str(tmp_path / "c.db")).ca_bundle == ""


def sender_for(tmp, ca):
    s = load_settings(db_path=str(tmp / "c.db"), ca_bundle=ca)
    return Sender(Pipeline(s).outbox, Pipeline(s).egress, s)


def test_the_collector_sender_trusts_only_the_ca_it_was_given(server):
    c, port, tmp = server
    url = f"https://127.0.0.1:{port}/"
    good, bad = sender_for(tmp, c["ca"]), sender_for(tmp, make(tmp / "impostor")["ca"])
    assert asyncio.run(good.client.get(url)).text == "ok"
    with pytest.raises(httpx.ConnectError) as e:
        asyncio.run(bad.client.get(url))
    assert "CERTIFICATE_VERIFY_FAILED" in str(e.value)
