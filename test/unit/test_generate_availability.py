import base64
import io
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "py"))

from generate_availability import build_onto_repo_auth, download_and_unzip


def test_build_onto_repo_auth_returns_none_when_both_unset():
    assert build_onto_repo_auth(None, None) is None


def test_build_onto_repo_auth_returns_basic_auth_when_both_set():
    auth = build_onto_repo_auth("svc-user", "secret-token")

    assert auth.username == "svc-user"
    assert auth.password == "secret-token"


@pytest.mark.parametrize("username,password", [("svc-user", None), (None, "secret-token")])
def test_build_onto_repo_auth_raises_when_only_one_is_set(username, password):
    with pytest.raises(ValueError):
        build_onto_repo_auth(username, password)


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.headers = {"Content-Type": "application/zip"}
        self.text = ""

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, content: bytes):
        self._content = content
        self.calls = []

    def get(self, url, timeout=None, auth=None):
        self.calls.append({"url": url, "auth": auth})
        return FakeResponse(self._content)


def make_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("elastic/onto_es__ontology_1.json", "{}")
    return buf.getvalue()


def test_download_and_unzip_sends_the_given_auth_to_the_request(tmp_path):
    session = FakeSession(make_zip_bytes())
    auth = build_onto_repo_auth("svc-user", "secret-token")

    download_and_unzip(session, "https://artifactory.example/elastic.zip", tmp_path, auth=auth)

    assert len(session.calls) == 1
    assert session.calls[0]["auth"] is auth


def test_download_and_unzip_without_auth_passes_none_through(tmp_path):
    session = FakeSession(make_zip_bytes())

    download_and_unzip(session, "https://example/elastic.zip", tmp_path)

    assert session.calls[0]["auth"] is None


def test_download_and_unzip_clears_stale_files_from_a_previous_run(tmp_path):
    stale_file = tmp_path / "elastic" / "onto_es__ontology_old.json"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("stale from a previous release")

    session = FakeSession(make_zip_bytes())
    download_and_unzip(session, "https://example/elastic.zip", tmp_path)

    assert not stale_file.exists()
    assert (tmp_path / "elastic" / "onto_es__ontology_1.json").exists()


def _make_basic_auth_server(expected_username: str, expected_password: str, zip_bytes: bytes) -> HTTPServer:
    """A real loopback HTTP server that challenges Basic Auth the way an
    artifactory proxy would, so tests exercise an actual request/response
    cycle instead of a stubbed session."""

    expected_header = "Basic " + base64.b64encode(
        f"{expected_username}:{expected_password}".encode()
    ).decode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get("Authorization") != expected_header:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="artifactory"')
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def basic_auth_server():
    server = _make_basic_auth_server("svc-user", "secret-token", make_zip_bytes())
    yield server
    server.shutdown()


def test_download_and_unzip_is_rejected_without_credentials(basic_auth_server, tmp_path):
    url = f"http://127.0.0.1:{basic_auth_server.server_port}/elastic.zip"

    with requests.Session() as session:
        with pytest.raises(requests.HTTPError) as exc_info:
            download_and_unzip(session, url, tmp_path)

    assert exc_info.value.response.status_code == 401


def test_download_and_unzip_is_rejected_with_wrong_credentials(basic_auth_server, tmp_path):
    url = f"http://127.0.0.1:{basic_auth_server.server_port}/elastic.zip"
    auth = build_onto_repo_auth("svc-user", "wrong-password")

    with requests.Session() as session:
        with pytest.raises(requests.HTTPError) as exc_info:
            download_and_unzip(session, url, tmp_path, auth=auth)

    assert exc_info.value.response.status_code == 401


def test_download_and_unzip_succeeds_over_real_http_with_correct_credentials(basic_auth_server, tmp_path):
    url = f"http://127.0.0.1:{basic_auth_server.server_port}/elastic.zip"
    auth = build_onto_repo_auth("svc-user", "secret-token")

    with requests.Session() as session:
        download_and_unzip(session, url, tmp_path, auth=auth)

    assert (tmp_path / "elastic" / "onto_es__ontology_1.json").exists()


def _make_origin_server(zip_bytes: bytes) -> HTTPServer:
    """The real artifact origin (e.g. GitHub releases) sitting behind the
    proxy. Takes no auth of its own."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _make_two_hop_proxy_server(expected_header: str, origin_port: int) -> HTTPServer:
    """Simulates an artifactory-style proxy: authenticates the CLIENT on one
    connection, then makes its OWN separate outbound request to a distinct
    origin server and relays the response — a genuine second hop, unlike a
    single server that just checks the header and answers directly."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get("Authorization") != expected_header:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="artifactory"')
                self.end_headers()
                return

            upstream = requests.get(f"http://127.0.0.1:{origin_port}{self.path}", timeout=10)
            self.send_response(upstream.status_code)
            self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/octet-stream"))
            self.send_header("Content-Length", str(len(upstream.content)))
            self.end_headers()
            self.wfile.write(upstream.content)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def two_hop_proxy():
    zip_bytes = make_zip_bytes()
    origin = _make_origin_server(zip_bytes)
    expected_header = "Basic " + base64.b64encode(b"svc-user:secret-token").decode()
    proxy = _make_two_hop_proxy_server(expected_header, origin.server_port)
    yield proxy
    proxy.shutdown()
    origin.shutdown()


def test_download_and_unzip_works_through_a_two_hop_proxy(two_hop_proxy, tmp_path):
    """Client -> proxy (auth check) -> origin (actual file), two separate
    connections, mirroring how an artifactory proxy really sits in front of
    the upstream release host."""
    url = f"http://127.0.0.1:{two_hop_proxy.server_port}/elastic.zip"
    auth = build_onto_repo_auth("svc-user", "secret-token")

    with requests.Session() as session:
        download_and_unzip(session, url, tmp_path, auth=auth)

    assert (tmp_path / "elastic" / "onto_es__ontology_1.json").exists()


def test_download_and_unzip_rejected_by_proxy_without_credentials(two_hop_proxy, tmp_path):
    url = f"http://127.0.0.1:{two_hop_proxy.server_port}/elastic.zip"

    with requests.Session() as session:
        with pytest.raises(requests.HTTPError) as exc_info:
            download_and_unzip(session, url, tmp_path)

    assert exc_info.value.response.status_code == 401


def test_download_and_unzip_survives_redirect_to_presigned_storage(tmp_path):
    """Some artifactory deployments hand off large-binary downloads with a
    302 to a presigned cloud-storage URL on a DIFFERENT host. `requests`
    strips the Authorization header on such cross-host redirects by design —
    this pins that the download still succeeds, because a presigned URL
    carries its own auth in the query string and doesn't need the header."""
    zip_bytes = make_zip_bytes()
    expected_header = "Basic " + base64.b64encode(b"svc-user:secret-token").decode()

    received_auth_headers = []

    class RecordingHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            received_auth_headers.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)

    storage = HTTPServer(("127.0.0.1", 0), RecordingHandler)
    threading.Thread(target=storage.serve_forever, daemon=True).start()

    class RedirectingProxyHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get("Authorization") != expected_header:
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(302)
            # A different hostname string than "127.0.0.1" so requests treats
            # this as a cross-host redirect and strips the auth header.
            self.send_header("Location", f"http://localhost:{storage.server_port}/elastic.zip?X-Presigned=abc123")
            self.end_headers()

    proxy = HTTPServer(("127.0.0.1", 0), RedirectingProxyHandler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    try:
        url = f"http://127.0.0.1:{proxy.server_port}/elastic.zip"
        auth = build_onto_repo_auth("svc-user", "secret-token")

        with requests.Session() as session:
            download_and_unzip(session, url, tmp_path, auth=auth)

        assert (tmp_path / "elastic" / "onto_es__ontology_1.json").exists()
        assert received_auth_headers == [None]
    finally:
        proxy.shutdown()
        storage.shutdown()
