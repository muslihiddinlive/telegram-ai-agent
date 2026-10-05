import asyncio
import os
import sys

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.instagram_api as ig  # noqa: E402
import core.instagram_common as common  # noqa: E402
import core.instagram_media as media  # noqa: E402
import core.instagram_tools as tools  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("IG_USER_ID", "1784000")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "SECRET-TOKEN")
    monkeypatch.setenv("IG_PUBLIC_BASE_URL", "https://bot.example.com")
    monkeypatch.setattr(common, "allowed", lambda uid: uid == 1)
    udir = tmp_path / "user"
    udir.mkdir()
    monkeypatch.setattr(common, "user_dir", lambda uid: str(udir))
    common._PENDING.clear()
    media._FILES.clear()
    return udir


def _img(path, size=(800, 600), mode="RGB"):
    Image.new(mode, size, (200, 30, 30) if mode == "RGB" else (200, 30, 30, 120)).save(path)


# ── Rasm tayyorlash ────────────────────────────────────────────────────────────
def test_story_is_1080x1920_jpeg(tmp_path):
    src = tmp_path / "a.png"
    _img(src, (500, 300), "RGBA")
    out = media.prepare_image(str(src), str(tmp_path), story=True)
    with Image.open(out) as im:
        assert im.size == (1080, 1920) and im.format == "JPEG" and im.mode == "RGB"


@pytest.mark.parametrize("size", [(400, 1600), (3000, 400), (800, 800), (4000, 3000)])
def test_feed_ratio_in_range(tmp_path, size):
    src = tmp_path / "a.png"
    _img(src, size)
    out = media.prepare_image(str(src), str(tmp_path), story=False)
    with Image.open(out) as im:
        assert media.FEED_MIN_RATIO - 0.01 <= im.width / im.height <= media.FEED_MAX_RATIO + 0.01
        assert im.width <= media.FEED_MAX_WIDTH


def test_bad_image_raises(tmp_path):
    bad = tmp_path / "x.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(media.MediaError):
        media.prepare_image(str(bad), str(tmp_path), story=False)


# ── Vaqtinchalik URL server ────────────────────────────────────────────────────
def test_media_server_serves_then_expires_and_revokes(tmp_path, monkeypatch):
    monkeypatch.setenv("IG_PUBLIC_BASE_URL", "https://bot.example.com")
    f = tmp_path / "p.jpg"
    f.write_bytes(b"JPEGDATA")
    url = media.expose(str(f))
    path = url.replace("https://bot.example.com", "")
    assert path.endswith("/media.jpg")

    async def go():
        app = web.Application()
        media.register(app)
        async with TestClient(TestServer(app)) as c:
            r = await c.get(path)
            assert r.status == 200 and await r.read() == b"JPEGDATA"
            assert (await c.get("/ig-media/wrong/media.jpg")).status == 404
            media.revoke(url)
            assert (await c.get(path)).status == 404
            url2 = media.expose(str(f), ttl=-1)  # allaqachon muddati o'tgan
            assert (await c.get(url2.replace("https://bot.example.com", ""))).status == 404

    run(go())


# ── Graph API ketma-ketligi ────────────────────────────────────────────────────
def _fake_request(calls):
    counter = {"n": 0}

    async def fake(method, path, *, params=None, json_body=None):
        calls.append((method, path, json_body))
        if method == "POST":
            counter["n"] += 1
            return {"id": f"id{counter['n']}"}
        if params and params.get("fields") == "permalink":
            return {"permalink": "https://instagram.com/p/XYZ"}
        return {"status_code": "FINISHED"}

    return fake


def test_carousel_sequence(env, monkeypatch):
    calls = []
    monkeypatch.setattr(ig, "_request", _fake_request(calls))
    res = run(ig.publish("CAROUSEL", [("https://u/1.jpg", False), ("https://u/2.mp4", True)], "cap"))
    posts = [c for c in calls if c[0] == "POST"]
    assert posts[0][2] == {"is_carousel_item": True, "image_url": "https://u/1.jpg"}
    assert posts[1][2] == {"is_carousel_item": True, "media_type": "VIDEO", "video_url": "https://u/2.mp4"}
    assert posts[2][2] == {"media_type": "CAROUSEL", "children": "id1,id2", "caption": "cap"}
    assert posts[3][1].endswith("/media_publish") and posts[3][2] == {"creation_id": "id3"}
    assert res == {"media_id": "id4", "permalink": "https://instagram.com/p/XYZ"}


def test_story_has_no_caption_and_reel_flags(env, monkeypatch):
    calls = []
    monkeypatch.setattr(ig, "_request", _fake_request(calls))
    run(ig.publish("STORY", [("https://u/v.mp4", True)], "ignored"))
    assert calls[0][2] == {"media_type": "STORIES", "video_url": "https://u/v.mp4"}
    calls.clear()
    run(ig.publish("REEL", [("https://u/v.mp4", True)], "hi"))
    assert calls[0][2]["media_type"] == "REELS" and calls[0][2]["share_to_feed"] is True


def test_api_error_never_leaks_token(env, monkeypatch):
    import httpx

    resp = httpx.Response(400, json={"error": {"message": "Invalid", "code": 100, "error_subcode": 2207}})
    msg = ig._describe_error("POST", "/1784000/media", resp)
    assert "Invalid" in msg and "2207" in msg and "SECRET-TOKEN" not in msg


# ── Tool: ruxsat, validatsiya, tasdiq qulfi ────────────────────────────────────
def _setup_publish(env, monkeypatch):
    _img(env / "a.jpg")
    published = []

    async def fake_publish(kind, items, caption=""):
        published.append((kind, [u for u, _ in items], caption))
        return {"media_id": "M1", "permalink": "https://instagram.com/p/A"}

    async def fake_quota():
        return {"used": 3, "total": 100}

    monkeypatch.setattr(ig, "publish", fake_publish)
    monkeypatch.setattr(ig, "get_quota", fake_quota)
    return published


def test_confirmation_flow(env, monkeypatch):
    published = _setup_publish(env, monkeypatch)
    args = {"kind": "POST", "file_names": ["a.jpg"], "caption": "salom"}

    r1 = run(tools._instagram_publish(1, dict(args), {"message_id": 10}))
    assert r1["status"] == "tasdiq_kerak" and not published

    # AI o'sha xabar ichida o'zi tasdiqlamoqchi → rad etiladi
    r2 = run(tools._instagram_publish(1, {**args, "confirmed": True}, {"message_id": 10}))
    assert "error" in r2 and not published

    # foydalanuvchi keyingi xabarida rozi → joylanadi, URL'lar o'chiriladi
    r3 = run(tools._instagram_publish(1, {**args, "confirmed": True}, {"message_id": 11}))
    assert r3["status"] == "joylandi" and r3["havola"] == "https://instagram.com/p/A"
    assert published[0][0] == "POST" and published[0][1][0].startswith("https://bot.example.com/ig-media/")
    assert not media._FILES

    # tasdiq bir martalik
    r4 = run(tools._instagram_publish(1, {**args, "confirmed": True}, {"message_id": 12}))
    assert "error" in r4 and len(published) == 1


def test_changed_args_after_preview_rejected(env, monkeypatch):
    published = _setup_publish(env, monkeypatch)
    run(tools._instagram_publish(1, {"kind": "POST", "file_names": ["a.jpg"], "caption": "A"}, {"message_id": 1}))
    r = run(tools._instagram_publish(
        1, {"kind": "POST", "file_names": ["a.jpg"], "caption": "BOSHQA", "confirmed": True}, {"message_id": 2}))
    assert "error" in r and not published


def test_denied_cases(env, monkeypatch):
    _setup_publish(env, monkeypatch)
    a = {"kind": "POST", "file_names": ["a.jpg"]}
    assert "huquqi" in run(tools._instagram_publish(2, a, {}))["error"]
    assert "shaxsiy" in run(tools._instagram_publish(1, a, {"is_group": True}))["error"]
    monkeypatch.delenv("IG_ACCESS_TOKEN")
    assert "ulanmagan" in run(tools._instagram_publish(1, a, {}))["error"]


@pytest.mark.parametrize("args,needle", [
    ({"kind": "CAROUSEL", "file_names": ["a.jpg"]}, "2-10"),
    ({"kind": "REEL", "file_names": ["a.jpg"]}, "video"),
    ({"kind": "POST", "file_names": ["../../etc/passwd"]}, "topilmadi"),
    ({"kind": "POST", "file_names": ["a.jpg"], "caption": "x" * 2201}, "uzun"),
    ({"kind": "POST", "file_names": ["a.jpg"], "caption": " ".join(f"#t{i}" for i in range(31))}, "Hashtag"),
    ({"kind": "NOPE", "file_names": ["a.jpg"]}, "Noma'lum"),
])
def test_validation_errors(env, monkeypatch, args, needle):
    _setup_publish(env, monkeypatch)
    assert needle in run(tools._instagram_publish(1, args, {}))["error"]


def test_api_failure_is_reported_and_cleaned(env, monkeypatch):
    _setup_publish(env, monkeypatch)

    async def boom(kind, items, caption=""):
        raise ig.InstagramAPIError("Meta rad etdi")

    monkeypatch.setattr(ig, "publish", boom)
    a = {"kind": "STORY", "file_names": ["a.jpg"]}
    run(tools._instagram_publish(1, a, {"message_id": 1}))
    r = run(tools._instagram_publish(1, {**a, "confirmed": True}, {"message_id": 2}))
    assert r == {"error": "Meta rad etdi"} and not media._FILES
