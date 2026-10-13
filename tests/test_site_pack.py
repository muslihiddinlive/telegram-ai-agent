"""Sayt frontend'ini o'qish va ko'chirish: tahlil, bitta HTML (inline/base64), ZIP (assets/), source map, chegaralar."""
import asyncio
import http.server
import io
import ipaddress
import re
import socket
import threading
import zipfile

import pytest

import core.site_fetch as sf
import core.site_pack as pack
from core.site_fetch import SiteError

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
HTML = ('<!DOCTYPE html><html lang="uz"><head><meta charset="windows-1251"><title>Test sayt</title>'
        '<link rel="stylesheet" href="/style.css" integrity="sha384-x" crossorigin="anonymous"><link rel="icon" href="/fav.ico">'
        '<link rel="preload" href="/app.js" as="script"><link rel="preconnect" href="https://fonts.example.com">'
        '<style>.hero{background:url(/bg.png)}</style><script src="/app.js" defer integrity="sha384-y" crossorigin></script></head>'
        '<body><h1>Салом</h1><div class="hero" style="background:url(\'/bg.png\') no-repeat"></div>'
        '<img src="/logo.png" srcset="/logo.png 1x, /logo@2x.png 2x" alt="x"><img src="/missing.png"><img data-src="/lazy.png">'
        '<a href="/about">About</a><a href="mailto:a@b.c">mail</a><a href="#top">top</a>'
        '<form action="/login" method="post"><input name="user"><input name="pw" type="password"></form>'
        '<script>var inline=1;</script></body></html>').encode("cp1251")
CSS = ('@import url("/reset.css") screen;\n@font-face{font-family:F;src:url("/f.woff2") format("woff2")}\n'
       "body{background:url('bg.png')}\n.d{background:url(data:image/png;base64,AAAA)}\n/*# sourceMappingURL=style.css.map */").encode()
JS = b'console.log("</script>");\n//# sourceMappingURL=app.js.map\n'


class H(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        r = H.routes.get(self.path.split("?")[0])
        if r is None:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        ct, body = r
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


def default_routes():
    return {"/": ("text/html", HTML), "/style.css": ("text/css", CSS), "/reset.css": ("text/css", b"*{margin:0}"),
            "/f.woff2": ("font/woff2", b"\x00wOF2fake"), "/bg.png": ("image/png", PNG), "/logo.png": ("image/png", PNG),
            "/logo@2x.png": ("image/png", PNG + b"2"), "/lazy.png": ("image/png", PNG + b"3"), "/fav.ico": ("image/x-icon", b"ICO"),
            "/app.js": ("application/javascript", JS), "/app.js.map": ("application/json", b'{"version":3,"sources":["src/a.js"]}'),
            "/style.css.map": ("application/json", b'{"version":3,"sources":["a.scss"]}')}


@pytest.fixture
def site(monkeypatch):
    H.routes = default_routes()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real_ok = sf._ip_ok
    monkeypatch.setattr(sf, "_ip_ok", lambda ip: ip == ipaddress.ip_address("127.0.0.1") or real_ok(ip))
    monkeypatch.setattr(sf, "ALLOWED_PORTS", {80, 443, 8080, 8443, port})
    real_gai = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, *a, **k: real_gai("127.0.0.1", p, *a, **k) if str(h).endswith(".test") else real_gai(h, p, *a, **k))
    yield type("S", (), {"url": f"http://site.test:{port}/", "base": f"http://site.test:{port}", "routes": H.routes})
    srv.shutdown()


def run(c):
    return asyncio.run(c)


# ── bitta HTML ─────────────────────────────────────────────────────────────────
def test_single_file_inlines_everything(site):
    res = run(pack.archive(site.url, "single"))
    out = res.data.decode("utf-8")
    assert res.mode == "single" and res.filename.startswith("site.test_") and res.filename.endswith(".html")
    assert out.startswith("<!-- Saqlangan:") and 'charset="utf-8"' in out and "Салом" in out and "windows-1251" not in out    # kodirovka tiklandi
    # tarmoq havolalari qolmadi
    for gone in ('href="/style.css"', 'src="/app.js"', 'src="/logo.png"', "url(/bg.png)", "preload", "preconnect", "integrity", "crossorigin"):
        assert gone not in out
    assert out.count("data:image/png;base64") >= 4 and "data:font/woff2;base64" in out and "data:image/x-icon;base64" in out
    assert "@media screen" in out and "margin:0" in out                                                       # @import ichiga joylandi
    assert "sourceMappingURL" not in out
    # JS: </script> ichida buzilmaydi, defer'li skript body oxiriga ko'chdi
    assert 'console.log("<\\/script>")' in out
    assert out.index("var inline=1") < out.index("console.log(") and out.index("Салом") < out.index("console.log(")
    # lazy/srcset
    assert "data-src=\"data:image/png;base64" in out and re.search(r'srcset="data:image/png;base64,[^ ]+ 1x, data:image/png;base64,[^ ]+ 2x"', out)
    # havolalar absolyutlashtirildi; mailto/# tegilmadi; forma o'zgarmadi (faqat to'liq yozildi)
    assert f'href="{site.base}/about"' in out and 'href="mailto:a@b.c"' in out and 'href="#top"' in out and f'action="{site.base}/login"' in out
    # yuklanmagan rasm: asl (absolyut) havola saqlandi
    assert f'src="{site.base}/missing.png"' in out and any("missing.png" in u and "404" in why for u, why in res.failed)
    assert res.notes and "1 ta resurs" in " ".join(res.notes) or any("yuklanmadi" in n for n in res.notes)


def test_single_file_survives_a_base_tag_and_utf8_pages(site):
    site.routes["/"] = ("text/html", '<html><head><base href="/sub/"><meta charset="utf-8"><link rel="stylesheet" href="s.css"></head><body><img src="p.png"></body></html>'.encode())
    site.routes["/sub/s.css"] = ("text/css", b"body{color:red}")
    site.routes["/sub/p.png"] = ("image/png", PNG)
    out = run(pack.archive(site.url, "single")).data.decode()
    assert "color:red" in out and "data:image/png;base64" in out and "<base" not in out


# ── ZIP ────────────────────────────────────────────────────────────────────────
def test_zip_has_structure_relative_paths_source_maps_and_manifest(site):
    res = run(pack.archive(site.url, "zip"))
    z = zipfile.ZipFile(io.BytesIO(res.data))
    names = set(z.namelist())
    assert res.filename.endswith(".zip") and {"index.html", "MANIFEST.txt"} <= names
    css = next(n for n in names if n.startswith("assets/css/style-") and n.endswith(".css")); reset = next(n for n in names if n.startswith("assets/css/reset-") and n.endswith(".css"))
    js = next(n for n in names if n.startswith("assets/js/app-") and n.endswith(".js"))
    assert js + ".map" in names and css + ".map" in names and any(n.startswith("assets/fonts/f-") for n in names) and any(n.startswith("assets/img/bg-") for n in names)
    for n in names:                                                         # zip-slip bo'lmasin
        assert not n.startswith(("/", "..")) and ".." not in n.split("/") and "\\" not in n
    idx = z.read("index.html").decode()
    assert f'href="{css}"' in idx and f'src="{js}"' in idx and "integrity" not in idx and "preload" not in idx
    assert re.search(r'url\("assets/img/bg-[0-9a-f]{6}\.png"\)', idx)                                  # <style> va style="" — index ildizidan nisbiy
    css_text = z.read(css).decode()
    assert f'@import url("{reset.split("/")[-1]}") screen;' in css_text                                # bir papkada: oddiy nom
    assert re.search(r'url\("\.\./fonts/f-[0-9a-f]{6}\.woff2"\)', css_text) and re.search(r'url\("\.\./img/bg-[0-9a-f]{6}\.png"\)', css_text)
    assert "data:image/png;base64,AAAA" in css_text                                                   # allaqachon data: — tegilmagan
    assert css_text.rstrip().endswith("sourceMappingURL=" + css.split("/")[-1] + ".map */")
    assert z.read(js).decode().rstrip().endswith("sourceMappingURL=" + js.split("/")[-1] + ".map")
    man = z.read("MANIFEST.txt").decode()
    assert site.url in man and "/style.css ->" in man and "missing.png: HTTP 404" in man
    assert res.files == len(names) and any("missing.png" in u for u, _ in res.failed)


def test_same_url_is_stored_once_and_missing_assets_do_not_break_the_page(site):
    z = zipfile.ZipFile(io.BytesIO(run(pack.archive(site.url, "zip")).data))
    pngs = [n for n in z.namelist() if n.startswith("assets/img/logo")]
    assert len(pngs) == 2 and any("logo_2x-" in n for n in pngs)          # logo.png (img + srcset 1x) bir marta, logo@2x alohida (nomi tozalangan)
    assert z.read("index.html")


# ── chegaralar va xatolar ──────────────────────────────────────────────────────
def test_limits_degrade_gracefully(site, monkeypatch):
    monkeypatch.setattr(pack, "MAX_ASSETS", 3)
    res = run(pack.archive(site.url, "single"))
    assert res.data and any("chegarasi" in why for _, why in res.failed)
    monkeypatch.setattr(pack, "MAX_ASSETS", 150); monkeypatch.setattr(pack, "MAX_TOTAL", 60)
    assert any("hajm" in why for _, why in run(pack.archive(site.url, "single")).failed)
    monkeypatch.setattr(pack, "MAX_TOTAL", 40 * 1024 * 1024); monkeypatch.setattr(pack, "MAX_OUT", 200)
    with pytest.raises(SiteError, match="juda katta"):
        run(pack.archive(site.url, "single"))
    monkeypatch.setattr(pack, "MAX_OUT", 44 * 1024 * 1024); monkeypatch.setattr(pack, "MAX_INLINE_ASSET", 10)
    res = run(pack.archive(site.url, "single"))
    assert any("katta" in why for _, why in res.failed)                    # bitta fayl chegarasidan katta rasm inline qilinmadi


def test_non_html_error_pages_and_bad_mode(site):
    site.routes["/img"] = ("image/png", PNG)
    with pytest.raises(SiteError, match="HTML sahifa emas"):
        run(pack.archive(site.base + "/img", "single"))
    with pytest.raises(SiteError, match="404"):
        run(pack.archive(site.base + "/nope", "single"))
    with pytest.raises(SiteError, match="Format"):
        run(pack.archive(site.url, "exe"))
    with pytest.raises(SiteError):
        run(pack.archive("http://169.254.169.254/latest/meta-data/", "zip"))


def test_deadline_is_enforced(site, monkeypatch):
    monkeypatch.setattr(pack, "DEADLINE_SECONDS", -1)
    with pytest.raises(SiteError, match="Vaqt"):
        run(pack.archive(site.url, "single"))


# ── tahlil (o'qish) ────────────────────────────────────────────────────────────
def test_analyze_extracts_structure_and_ignores_scripts_and_secrets():
    html = ('<html lang="en"><head><title>Shop</title><meta name="description" content="Best shop"><meta name="generator" content="WordPress 6">'
            '<link rel="stylesheet" href="/wp-content/themes/a/style.css"><script src="/_next/static/chunks/main.js"></script>'
            '<script>window.SECRET_TOKEN="abc123"</script></head><body><h1>Welcome</h1><h2>Deals</h2><p>Hello   world</p><p>' + 'Realistic server-rendered content. ' * 12 + '</p>'
            '<a href="/p/1">p1</a><a href="https://other.com/x">ext</a><form method="POST" action="/login"><input name="email" value="me@x.com">'
            '<input type="password" name="pw" value="hunter2"></form><img src="/a.png"></body></html>').encode()
    a = pack.analyze(html, "https://shop.example.com/")
    assert a["title"] == "Shop" and a["lang"] == "en" and a["description"] == "Best shop" and a["generator"] == "WordPress 6"
    assert {"WordPress", "Next.js"} <= set(a["tech"]) and not a["spa_suspected"]
    assert [h["text"] for h in a["headings"]] == ["Welcome", "Deals"] and "Hello world" in a["text_excerpt"] and "abc123" not in a["text_excerpt"]
    assert a["links"]["internal_sample"] == ["https://shop.example.com/p/1"] and a["links"]["external"] == 1
    f = a["forms"][0]
    assert f["method"] == "post" and f["action"] == "https://shop.example.com/login" and [x["name"] for x in f["fields"]] == ["email", "pw"]
    assert "hunter2" not in str(a) and "me@x.com" not in str(a)                                          # qiymatlar yig'ilmaydi — faqat maydon nomlari
    assert a["resources"]["css"] == ["https://shop.example.com/wp-content/themes/a/style.css"] and a["resources"]["inline_scripts"] == 1
    text = pack.render_analysis(a)
    assert "WordPress" in text and "Formalar:" in text


def test_analyze_detects_spa_shell():
    a = pack.analyze(b'<html><head><title>App</title></head><body><div id="root"></div><script src="/assets/index-AbC123.js"></script></body></html>', "https://x.com/")
    assert a["spa_suspected"] and "Vite" in a["tech"] and "SPA" in pack.render_analysis(a)


def test_analysis_via_network_and_resource_reader(site):
    page = run(pack.fetch_page(site.url))
    a = pack.analyze(page.body, page.url)
    assert a["title"] == "Test sayt" and a["resources"]["css"] == [site.base + "/style.css"] and "Салом" in a["text_excerpt"]
    site.routes["/big.js"] = ("application/javascript", ("var a=1;" * 5000).encode())
    r = run(pack.read_resource(site.base + "/big.js", 0, 1000))
    assert len(r["text"]) == 1000 and r["more"] and r["chars"] == 40000 and r["minified"]
    r2 = run(pack.read_resource(site.base + "/big.js", 39500, 5000))
    assert not r2["more"] and len(r2["text"]) == 500
    bin_ = run(pack.read_resource(site.base + "/logo.png"))
    assert bin_["text"] is None and "binar" in bin_["note"]
    with pytest.raises(SiteError, match="404"):
        run(pack.read_resource(site.base + "/nope.js"))
    with pytest.raises(SiteError):
        run(pack.read_resource("http://10.0.0.1/secret.js"))


# ── regressiya: parser yopilmagan <meta/> ichiga keyingi teglarni joylab yuboradi (haqiqiy github.com'da topilgan) ──────────────────
def test_flatten_void_moves_swallowed_siblings_out():
    from bs4 import BeautifulSoup
    s = BeautifulSoup('<head><meta name="a"><link rel="preload" href="/a.js"><link rel="stylesheet" href="/s.css"></head>', "html.parser")
    meta = s.find("meta")
    for sib in list(meta.next_siblings):
        meta.append(sib.extract())
    assert [l.parent.name for l in s.find_all("link")] == ["meta", "meta"]
    pack._flatten_void(s)
    assert [l.parent.name for l in s.find_all("link")] == ["head", "head"] and not meta.contents
    assert [t.name for t in s.head.find_all(True, recursive=False)] == ["meta", "link", "link"]          # tartib saqlandi


def test_archive_and_analysis_survive_the_parser_nesting_quirk(site, monkeypatch):
    real = pack.BeautifulSoup

    def quirky(text, parser):
        s = real(text, parser)
        meta = s.find("meta")
        if meta is not None:
            for sib in list(meta.next_siblings):             # <meta/> yopilmagan holat: keyingi hamma narsa uning ichida
                meta.append(sib.extract())
        return s
    monkeypatch.setattr(pack, "BeautifulSoup", quirky)
    site.routes["/"] = ("text/html", b'<html><head><meta name="x" content="0"><link rel="modulepreload" href="/app.js"><link rel="stylesheet" href="/a.css">'
                                      b'<link rel="icon" href="/fav.ico"></head><body><h1>Hi</h1><img src="/p.png"></body></html>')
    site.routes["/a.css"] = ("text/css", b"body{color:red}")
    site.routes["/p.png"] = ("image/png", PNG)
    out = run(pack.archive(site.url, "single")).data.decode()
    assert "color:red" in out and "modulepreload" not in out and "data:image/png;base64" in out and "data:image/x-icon;base64" in out      # xato bermadi, hamma ishlandi
    z = zipfile.ZipFile(io.BytesIO(run(pack.archive(site.url, "zip")).data))
    assert any(n.startswith("assets/css/a-") for n in z.namelist())
    a = pack.analyze(site.routes["/"][1], site.url)
    assert a["resources"]["css"] == [site.base + "/a.css"]
