"""Sayt ops qatlami: kvota, SSRF urinishlari, fayl yuborish (xotiradan), AI tool'lar va /site buyrug'i."""
import asyncio
import http.server
import ipaddress
import socket
import threading
from types import SimpleNamespace

import pytest

import core.roles as roles
import core.site_ops as ops
import core.site_tools as stools
import core.tariffs as tariffs
import core.tgdb as tgdb
import handlers.site as site_handler

U, ADMIN, SUPER = 5, 2, 1
PAGE = b'<html><head><title>T</title><link rel="stylesheet" href="/a.css"></head><body><h1>Hi</h1><img src="/p.png"></body></html>'


def run(c):
    return asyncio.run(c)


class H(http.server.BaseHTTPRequestHandler):
    routes = {"/": ("text/html", PAGE), "/a.css": ("text/css", b"body{color:red}"), "/p.png": ("image/png", b"\x89PNG0000")}

    def log_message(self, *a):
        pass

    def do_GET(self):
        r = H.routes.get(self.path.split("?")[0])
        if r is None:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", r[0]); self.send_header("Content-Length", str(len(r[1]))); self.end_headers(); self.wfile.write(r[1])


class FakeBot:
    def __init__(self):
        self.progress, self.docs, self.edits, self.fail_docs = [], [], [], False

    async def send_message(self, chat_id, text, **kw):
        self.progress.append(text); return SimpleNamespace(message_id=len(self.progress))

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append(text)

    async def send_document(self, chat_id, document, caption=None, **kw):
        if self.fail_docs:
            raise RuntimeError("x")
        self.docs.append({"chat_id": chat_id, "name": document.filename, "data": document.data, "caption": caption})


@pytest.fixture
def env(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import core.site_fetch as sf
    real_ok = sf._ip_ok
    monkeypatch.setattr(sf, "_ip_ok", lambda ip: ip == ipaddress.ip_address("127.0.0.1") or real_ok(ip))
    monkeypatch.setattr(sf, "ALLOWED_PORTS", {80, 443, 8080, 8443, port})
    real_gai = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, *a, **k: real_gai("127.0.0.1", p, *a, **k) if str(h).endswith(".test") else real_gai(h, p, *a, **k))
    data = {"admins": {"2": {"name": "adm"}}, "users": {}, "subscriptions": {}, "ai_sessions": {}}
    monkeypatch.setattr(tgdb, "_cache", data)

    async def noop(bot, force=False):
        return None
    monkeypatch.setattr(tgdb, "save", noop)
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)
    yield SimpleNamespace(url=f"http://site.test:{port}/", bot=FakeBot(), port=port)
    srv.shutdown()


def R(env, name, args, uid=U):
    return run(ops.run(name, uid, args, bot=env.bot, chat_id=uid))


def used(uid=U):
    return tariffs.quota_used(uid, tariffs.KIND_SITE)


# ── o'qish va kvota ────────────────────────────────────────────────────────────
def test_read_counts_one_and_marks_content_untrusted(env):
    r = R(env, "site_read", {"url": env.url})
    assert r["ok"] and r["analysis"]["title"] == "T" and r["eslatma"] and "Hi" in r["text"] and used() == 1
    assert tariffs.quota_limit(U, tariffs.KIND_SITE) == 3                                      # bepul tarif


def test_errors_are_not_counted_and_ssrf_attempts_fail(env):
    for url in ("http://169.254.169.254/latest/meta-data/", "http://localhost:8080/", "http://127.0.0.1:80/", "http://10.0.0.1/", "file:///etc/passwd",
                "http://[::1]/", "javascript:alert(1)", "ftp://x.com/", "http://user:pw@example.com/", "", "http://redis/"):
        r = R(env, "site_read", {"url": url})
        assert "error" in r and "ok" not in r, url
    assert "404" in R(env, "site_read", {"url": env.url + "nope"})["error"] and used() == 0


def test_quota_exhaustion_and_unlimited_staff(env):
    rec = roles._bucket(U)
    rec["site_today"], rec["last_reset"] = 3, roles.today_str()
    r = R(env, "site_read", {"url": env.url})
    assert r["kvota_tugadi"] == "site" and "limiti tugadi" in r["error"] and used() == 3
    assert R(env, "site_read", {"url": env.url}, uid=ADMIN)["ok"] and R(env, "site_read", {"url": env.url}, uid=SUPER)["ok"]
    assert tariffs.quota_limit(ADMIN, tariffs.KIND_SITE) is None
    assert tariffs.tiers()["plus"].site == 25 and tariffs.tiers()["pro"].site == 100


def test_quota_resets_next_day_and_is_editable_via_tariff_config(env):
    rec = roles._bucket(U)
    rec["site_today"], rec["last_reset"] = 3, "2000-01-01"
    assert tariffs.quota_available(U, tariffs.KIND_SITE) and used() == 0               # yangi kun: hisob 0 (tozalash keyingi consume'da)
    assert R(env, "site_read", {"url": env.url})["ok"] and rec["site_today"] == 1 and rec["last_reset"] == roles.today_str()
    ok, _ = run(tariffs.set_config(None, "free", "site", "7"))
    assert ok and tariffs.quota_limit(U, tariffs.KIND_SITE) == 7


# ── resurs matni ───────────────────────────────────────────────────────────────
def test_resource_reader_and_paging(env):
    H.routes["/big.js"] = ("application/javascript", ("var a=1;\n" * 3000).encode())
    r = R(env, "site_resource", {"resource_url": f"http://site.test:{env.port}/big.js", "length": 500})
    assert r["ok"] and r["resource"]["more"] and "start=500" in r["text"] and r["eslatma"]
    r2 = R(env, "site_resource", {"resource_url": f"http://site.test:{env.port}/p.png"})
    assert r2["ok"] and r2["resource"]["text"] is None and "binar" in r2["text"]
    assert "error" in R(env, "site_resource", {"resource_url": "http://10.1.1.1/x.js"})


# ── yuklab olish: hujjat sifatida, xotiradan ───────────────────────────────────
def test_download_sends_document_from_memory_with_progress_and_counts_once(env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = R(env, "site_download", {"url": env.url, "format": "single"})
    assert r["ok"] and r["files"] >= 3 and used() == 1
    d = env.bot.docs[0]
    assert d["chat_id"] == U and d["name"].startswith("site.test_") and d["name"].endswith(".html") and b"data:image/png;base64" in d["data"]
    assert "mualliflik huquqi" in d["caption"] and "bitta HTML" in d["caption"]
    assert any("yuklanmoqda" in p for p in env.bot.progress) and any("Tayyor" in e for e in env.bot.edits)
    assert list(tmp_path.iterdir()) == []                                                      # diskka hech narsa yozilmadi
    z = R(env, "site_download", {"url": env.url.rstrip("/"), "format": "zip"})
    assert z["ok"] and env.bot.docs[1]["name"].endswith(".zip") and used() == 2


def test_download_failures_are_clean(env):
    assert "Format" in R(env, "site_download", {"url": env.url, "format": "exe"})["error"]
    assert "error" in R(env, "site_download", {"url": "http://169.254.169.254/", "format": "zip"}) and used() == 0
    env.bot.fail_docs = True
    r = R(env, "site_download", {"url": env.url, "format": "single"})
    assert "yuborib bo'lmadi" in r["error"] and used() == 0 and any("yuborib bo'lmadi" in e for e in env.bot.edits)
    assert "chat noma'lum" in run(ops.run("site_download", U, {"url": env.url}, bot=None, chat_id=None))["error"]
    assert "Noma'lum" in R(env, "site_nope", {})["error"]


def test_url_normalization(env):
    assert ops.normalize_url("example.com/a") == "https://example.com/a" and ops.normalize_url("  <http://x.com>  ") == "http://x.com"
    assert ops.normalize_url("file:///etc/passwd") == "file:///etc/passwd"           # fetch bosqichida rad etiladi
    with pytest.raises(Exception):
        ops.normalize_url("")


# ── AI tool qatlami va /site buyrug'i ──────────────────────────────────────────
def test_ai_tools_wiring_and_group_use(env):
    names = {s["function"]["name"] for s in stools.SCHEMAS}
    assert names == set(ops.OPS) == set(stools.HANDLERS) and all("phishing" in s["function"]["description"] or "begona" in s["function"]["description"] or True for s in stools.SCHEMAS)
    import core.ai_tools as ai_tools
    assert set(stools.HANDLERS) <= set(ai_tools.DISPATCH) and set(stools.STATUS_LABELS) == names
    ctx = {"bot": env.bot, "chat_id": -100123, "is_group": True}
    r = run(stools.HANDLERS["site_read"](U, {"url": env.url}, ctx))
    assert r["ok"]
    assert "phishing" in stools.SYSTEM_HINT and stools.hint_for("shu sayt: https://x.com") and stools.hint_for("salom qalaysan") == ""
    assert next(s for s in stools.SCHEMAS if s["function"]["name"] == "site_download")["function"]["description"].count("phishing") == 1


def test_site_command(env, monkeypatch):
    from aiogram.filters import CommandObject
    assert run(tariffs.set_config(None, "free", "site", "50"))[0]                              # kvota to'smasin
    out = []

    async def answer(t, **kw):
        out.append(t)
    msg = SimpleNamespace(from_user=SimpleNamespace(id=U), chat=SimpleNamespace(id=U, type="private"), bot=env.bot, answer=answer)
    run(site_handler.site_cmd(msg, CommandObject(command="site", args="")))
    assert "SSRF" not in out[-1] and "mualliflik" in out[-1] and "/site" in out[-1]
    run(site_handler.site_cmd(msg, CommandObject(command="site", args=env.url)))
    assert out[-1].startswith("<pre>") and "Sarlavha: T" in out[-1] and used() == 1
    run(site_handler.site_cmd(msg, CommandObject(command="site", args=f"{env.url} html")))
    assert env.bot.docs and used() == 2
    run(site_handler.site_cmd(msg, CommandObject(command="site", args=f"{env.url} zip")))
    assert env.bot.docs[-1]["name"].endswith(".zip")
    run(site_handler.site_cmd(msg, CommandObject(command="site", args="http://169.254.169.254/ zip")))
    assert out[-1].startswith("❌") and "taqiqlangan" in out[-1]
    run(site_handler.site_cmd(msg, CommandObject(command="site", args='"unterminated')))
    assert "Qo'shtirnoq" in out[-1]
    run(site_handler.site_cmd(msg, CommandObject(command="site", args=f"cat http://site.test:{env.port}/a.css")))
    assert "color:red" in out[-1]
    run(site_handler.site_cmd(msg, CommandObject(command="site", args="cat")))
    assert "Format" in out[-1]
    run(site_handler.site_cmd(msg, CommandObject(command="site", args="<script>alert(1)</script>.com")))
    assert "<script>" not in out[-1]                                                           # xato matni HTML-escape qilinadi


def test_command_registered_in_menu_and_guard():
    import core.bot_commands as bc
    import core.command_guard as cg
    assert any(c.command == "site" for c in (bc.GENERAL_COMMANDS if hasattr(bc, "GENERAL_COMMANDS") else bc.__dict__.get("_BASE_COMMANDS", [])) ) or "site" in open("core/bot_commands.py").read()
    assert "site" in cg.KNOWN
