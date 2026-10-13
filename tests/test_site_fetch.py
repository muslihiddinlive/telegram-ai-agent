"""SSRF-xavfsiz sayt yuklagich: URL/IP/redirect/DNS-rebinding himoyasi, hajm/vaqt chegaralari va HTTPS'da IP'ga bog'lash (haqiqiy lokal serverlar bilan)."""
import asyncio
import datetime
import gzip
import http.server
import ipaddress
import socket
import ssl
import threading

import pytest

import core.site_fetch as sf
from core.site_fetch import SiteError


def run(coro):
    return asyncio.run(coro)


# ── sof validatsiya ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "javascript:alert(1)", "data:text/html,hi", "dict://example.com:11211/",
    "http://user:pass@example.com/", "http://example.com@evil.com/", "http://example.com:22/", "http://example.com:6379/", "http://example.com:3000/",
    "http://localhost/", "http://LOCALHOST./", "http://foo.localhost/", "http://redis/", "http://db.internal/", "http://printer.local/",
    "http://router.lan/", "http://x.home.arpa/", "http:///nohost", "", " ", "http://exa mple.com/", "http://example.com/\nX: y", "https://example.com\\@evil.com",
    "http://[::1]:80/", "http://example.com:99999/", "x" * 2100,
])
def test_validate_url_rejects(url):
    with pytest.raises(SiteError):
        sf.validate_url(url)


def test_validate_url_ok_and_normalizes():
    assert sf.validate_url("https://Example.COM/a?b=1") == ("https", "example.com", 443, "/a?b=1")
    assert sf.validate_url("http://example.com:8080") == ("http", "example.com", 8080, "/")
    assert sf.validate_url("https://xn--80ak6aa92e.com/")[1] == "xn--80ak6aa92e.com"
    assert sf.validate_url("https://пример.рф/")[1].startswith("xn--")


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.1.2.3", "10.0.0.1", "172.16.5.5", "192.168.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255",
    "192.0.0.1", "198.18.0.1", "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "::ffff:127.0.0.1", "::ffff:10.1.1.1", "::ffff:169.254.169.254",
    "64:ff9b::7f00:1", "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "ff02::1",
])
def test_internal_ips_are_blocked(ip):
    assert sf._ip_ok(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_ips_are_allowed(ip):
    assert sf._ip_ok(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "0.0.0.0", "100.64.0.1", "::ffff:7f00:1",
                                  "127.1", "0x7f.1", "0177.0.0.1", "localtest.me"])
def test_resolve_blocks_internal_including_alt_notations(host):
    # ip-literal'lar va getaddrinfo shu yozuvlarni 127.0.0.1 ga aylantiradigan variantlar (127.1, 0x7f.1, 0177.0.0.1) ham rad etiladi
    async def go():
        try:
            return await sf.resolve(host.strip("[]"), 80)
        except SiteError as e:
            return e
    out = run(go())
    assert isinstance(out, SiteError)


def test_resolve_rejects_mixed_answers_and_accepts_all_public(monkeypatch):
    def fake_gai(host, port, *a, **k):
        return [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("10.0.0.7", port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
    with pytest.raises(SiteError):
        run(sf.resolve("rebind.example.com", 80))
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, *a, **k: [(2, 1, 6, "", ("93.184.216.34", p)), (10, 1, 6, "", ("2606:4700::1", p, 0, 0))])
    assert run(sf.resolve("ok.example.com", 80)) == ["93.184.216.34", "2606:4700::1"]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("nx")))
    with pytest.raises(SiteError):
        run(sf.resolve("nonexistent.example.com", 80))


# ── lokal serverlar ────────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.seen.append({"path": self.path, "host": self.headers.get("Host"), "auth": self.headers.get("Authorization"),
                             "cookie": self.headers.get("Cookie"), "ua": self.headers.get("User-Agent")})
        r = Handler.routes.get(self.path.split("?")[0])
        if r is None:
            self.send_response(404); self.end_headers(); return
        code, headers, body = r() if callable(r) else r
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        if "Content-Length" not in headers and not isinstance(body, type(None)):
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass


@pytest.fixture
def server(monkeypatch):
    Handler.routes, Handler.seen = {}, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real_ok = sf._ip_ok
    monkeypatch.setattr(sf, "_ip_ok", lambda ip: ip == ipaddress.ip_address("127.0.0.1") or real_ok(ip))      # faqat lokal server uchun teshik
    monkeypatch.setattr(sf, "ALLOWED_PORTS", {80, 443, 8080, 8443, port})
    real_gai = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, *a, **k: real_gai("127.0.0.1", p, *a, **k) if str(h).endswith(".test") else real_gai(h, p, *a, **k))
    yield type("S", (), {"port": port, "base": f"http://site.test:{port}", "h": Handler})
    srv.shutdown()


def test_fetch_basic_pins_ip_sets_host_header_and_sends_no_credentials(server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9"); monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9"); monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    Handler.routes["/p"] = (200, {"Content-Type": "text/html; charset=utf-8"}, b"<h1>hi</h1>")
    r = run(sf.fetch(f"{server.base}/p?x=1"))
    assert r.status == 200 and r.body == b"<h1>hi</h1>" and r.content_type == "text/html"            # muhit proksilari e'tiborsiz
    seen = Handler.seen[-1]
    assert seen["host"] == f"site.test:{server.port}" and seen["path"] == "/p?x=1"                   # Host — asl nom, ulanish — tekshirilgan IP'ga
    assert seen["auth"] is None and seen["cookie"] is None and "SiteCopierBot" in seen["ua"]


def test_redirects_are_followed_and_revalidated_per_hop(server):
    Handler.routes["/a"] = (302, {"Location": "/b"}, b"")
    Handler.routes["/b"] = (301, {"Location": f"{server.base}/c"}, b"")
    Handler.routes["/c"] = (200, {"Content-Type": "text/plain"}, b"end")
    r = run(sf.fetch(f"{server.base}/a"))
    assert r.body == b"end" and r.url.endswith("/c")
    for evil in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:1/", "http://10.0.0.5/", "http://localhost/admin", "file:///etc/passwd",
                 "gopher://x/", "http://[::1]/", "http://[::ffff:10.0.0.1]/", "http://internal.internal/", "//10.0.0.9/x", "http://user:p@example.com/"):
        Handler.routes["/evil"] = (302, {"Location": evil}, b"")
        with pytest.raises(SiteError):
            run(sf.fetch(f"{server.base}/evil"))
    Handler.routes["/loop"] = (302, {"Location": "/loop"}, b"")
    with pytest.raises(SiteError, match="redirect"):
        run(sf.fetch(f"{server.base}/loop"))
    Handler.routes["/noloc"] = (302, {}, b"")
    with pytest.raises(SiteError):
        run(sf.fetch(f"{server.base}/noloc"))


def test_size_caps_truncate_or_refuse_and_gzip_bomb_is_bounded(server):
    Handler.routes["/big"] = (200, {"Content-Type": "text/plain"}, b"A" * 50_000)
    with pytest.raises(SiteError, match="katta"):
        run(sf.fetch(f"{server.base}/big", max_bytes=10_000))
    r = run(sf.fetch(f"{server.base}/big", max_bytes=10_000, allow_truncate=True))
    assert r.truncated and len(r.body) == 10_000
    bomb = gzip.compress(b"\0" * 20_000_000)                                                      # ~20 KB siqilgan -> 20 MB ochilgan
    Handler.routes["/bomb"] = (200, {"Content-Type": "text/plain", "Content-Encoding": "gzip"}, bomb)
    with pytest.raises(SiteError, match="katta"):
        run(sf.fetch(f"{server.base}/bomb", max_bytes=1_000_000))
    Handler.routes["/gz"] = (200, {"Content-Type": "text/plain", "Content-Encoding": "gzip"}, gzip.compress(b"hello gzip"))
    assert run(sf.fetch(f"{server.base}/gz")).body == b"hello gzip"


def test_timeouts_and_bad_hosts(server, monkeypatch):
    import time
    def slow():
        time.sleep(1.5); return (200, {"Content-Type": "text/plain"}, b"late")
    Handler.routes["/slow"] = slow
    monkeypatch.setattr(sf, "READ_TIMEOUT", 0.3)
    with pytest.raises(SiteError, match="javob bermadi|Vaqt"):
        run(sf.fetch(f"{server.base}/slow"))
    with pytest.raises(SiteError, match="Vaqt"):
        run(sf.fetch(f"{server.base}/slow", deadline=__import__("time").monotonic() - 1))
    with pytest.raises(SiteError):
        run(sf.fetch("http://nonexistent-host-xyz.invalid/"))


def test_real_internal_targets_cannot_be_fetched_even_with_a_public_looking_name(monkeypatch):
    # hujumchi o'z DNS'ini 127.0.0.1 ga yo'naltirsa ham (a.evil.com -> 127.0.0.1) — rad etiladi
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, *a, **k: [(2, 1, 6, "", ("127.0.0.1", p))])
    with pytest.raises(SiteError, match="taqiqlangan"):
        run(sf.fetch("http://a.evil-dns.com/"))
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, *a, **k: [(2, 1, 6, "", ("169.254.169.254", p))])
    with pytest.raises(SiteError, match="taqiqlangan"):
        run(sf.fetch("https://metadata.evil-dns.com/latest/meta-data/"))


# ── HTTPS: IP'ga bog'lanadi, lekin sertifikat/SNI ASL host bo'yicha tekshiriladi ───────────────────
def make_cert(tmp_path, name):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "c.pem", tmp_path / "k.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def test_https_connects_to_pinned_ip_but_verifies_certificate_for_the_original_host(tmp_path, monkeypatch):
    cert, key = make_cert(tmp_path, "secure.test")
    Handler.routes, Handler.seen = {"/": (200, {"Content-Type": "text/plain"}, b"secure ok")}, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real_ok = sf._ip_ok
    monkeypatch.setattr(sf, "_ip_ok", lambda ip: ip == ipaddress.ip_address("127.0.0.1") or real_ok(ip))
    monkeypatch.setattr(sf, "ALLOWED_PORTS", {80, 443, port})
    real_gai = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, *a, **k: real_gai("127.0.0.1", p, *a, **k) if str(h).endswith(".test") else real_gai(h, p, *a, **k))
    monkeypatch.setattr(sf, "_VERIFY", ssl.create_default_context(cafile=cert))
    try:
        r = run(sf.fetch(f"https://secure.test:{port}/"))
        assert r.body == b"secure ok" and Handler.seen[-1]["host"] == f"secure.test:{port}"
        # boshqa nom -> bir xil IP, lekin sertifikat 'secure.test' uchun: tekshiruv ASL host bo'yicha bo'lgani uchun YIQILADI
        with pytest.raises(SiteError):
            run(sf.fetch(f"https://other.test:{port}/"))
    finally:
        srv.shutdown()
