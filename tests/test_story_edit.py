"""Story media tahriri: spec tekshiruvi (AI javoblariga ishonmaslik), rasm/video renderi (haqiqiy Pillow/ffmpeg), AI talqini."""
import asyncio
import json
import os
import random
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops, ImageStat

import core.roles as roles
import core.story_edit as se
import core.stories as stories

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe yo'q")


def run(coro):
    return asyncio.run(coro)


# ── spec: tekshirish va chegaralash ────────────────────────────────────────────
def test_default_is_noop_and_normalize_idempotent():
    d = se.default_spec()
    assert se.is_noop(d) and se.normalize(d) == d
    messy = {"filter": "SEPIA", "brightness": "0.4", "texts": [{"text": " Salom "}], "frame": {"width": "3"}}
    once = se.normalize(messy)
    assert se.normalize(once) == once                                          # ikki marta normallashtirish o'zgartirmaydi


def test_normalize_clamps_and_rejects_garbage():
    s = se.normalize({"filter": "evil", "brightness": 99, "contrast": -99, "saturation": "x", "warmth": float("nan"),
                      "sharpness": 5, "blur": -1, "vignette": float("inf"), "grain": True, "zoom": 100, "focus_x": -3,
                      "fit": "../etc", "fit_color": "javascript:alert(1)", "flip": "diagonal"})
    assert (s["filter"], s["brightness"], s["contrast"], s["saturation"], s["warmth"]) == ("none", 1.0, -1.0, 0.0, 0.0)
    assert (s["sharpness"], s["blur"], s["vignette"], s["grain"]) == (1.0, 0.0, 0.0, 0.0)
    assert (s["zoom"], s["focus_x"], s["fit"], s["fit_color"], s["flip"]) == (3.0, 0.0, "blur", "#000000", "none")


@pytest.mark.parametrize("raw,expected", [(-90, 270), (100, 90), (180, 180), (360, 0), ("abc", 0), (None, 0), (89, 90)])
def test_rotate_snaps_to_right_angles(raw, expected):
    assert se.normalize({"rotate": raw})["rotate"] == expected


def test_unknown_keys_dropped_and_input_not_mutated():
    src = {"filter": "bw", "exec": "rm -rf /", "texts": [{"text": "a", "x": 0.3, "__class__": "x"}]}
    snapshot = json.dumps(src, sort_keys=True)
    out = se.normalize(src)
    assert set(out) == set(se.default_spec()) and "exec" not in out and "__class__" not in out["texts"][0]
    assert json.dumps(src, sort_keys=True) == snapshot


def test_garbage_types_never_raise():
    rnd = random.Random(7)
    pool = [None, "x", 5, -1.5, [], {}, [1, 2], {"a": 1}, True, "#zzz", float("nan"), "💥", [[]], {"text": 5}]
    keys = list(se.default_spec()) + ["texts", "frame", "video"]
    for _ in range(300):
        junk = {rnd.choice(keys): rnd.choice(pool) for _ in range(rnd.randint(1, 6))}
        out = se.normalize(junk)
        assert se.normalize(out) == out                                         # har qanday kirish — yaroqli spec
    for bad in (None, "text", 5, [], [1]):
        assert se.normalize(bad) == se.default_spec()


def test_colors():
    assert se.normalize({"fit_color": "red"})["fit_color"] == "#FF3B30"
    assert se.normalize({"fit_color": "qora"})["fit_color"] == "#000000"
    assert se.normalize({"fit_color": "#abc"})["fit_color"] == "#AABBCC"
    assert se.normalize({"fit_color": "00ff00"})["fit_color"] == "#00FF00"
    assert se.normalize({"fit_color": "url(x)"})["fit_color"] == "#000000"


def test_texts_are_sanitized_and_limited():
    texts = [{"text": f"matn {i}"} for i in range(9)]
    assert len(se.normalize({"texts": texts})["texts"]) == se.MAX_TEXTS
    t = se.normalize({"texts": [{"text": "Salom 😀🔥 dunyo\x00\x07!", "pos": "top", "size": 99, "style": "x", "font": "comic"}]})["texts"][0]
    assert t["text"] == "Salom dunyo!" and t["y"] == 0.12 and t["size"] == 14.0 and t["style"] == "shadow" and t["font"] == "sans"
    assert se.normalize({"texts": [{"text": "   "}, {"text": "😀"}, {"nope": 1}, 5, None]})["texts"] == []
    assert len(se.normalize({"texts": [{"text": "x" * 500}]})["texts"][0]["text"]) == se.MAX_TEXT_LEN
    assert se.normalize({"texts": [{"text": "a\nb\nc\nd\ne"}]})["texts"][0]["text"].count("\n") == 2     # eng ko'pi 3 qator
    assert se.normalize({"texts": "Faqat matn"})["texts"][0]["text"] == "Faqat matn"
    assert se.normalize({"texts": {"text": "bitta"}})["texts"][0]["text"] == "bitta"
    assert "ʻ" in se.clean_text("oʻzbek gʻoyasi")                                                      # o'zbekcha belgi saqlanadi


def test_video_section_and_trim_sanity():
    v = se.normalize({"video": {"speed": 9, "start": 10, "end": 5, "mute": "ha", "fade_in": 99}})["video"]
    assert v == {"speed": 2.0, "start": 10.0, "end": 0.0, "mute": True, "fade_in": 5.0, "fade_out": 0.0}


def test_noop_ignores_video_fields_for_photos_only():
    assert se.is_noop({"video": {"speed": 2}}, "photo") and not se.is_noop({"video": {"speed": 2}}, "video")


def test_merge_semantics():
    cur = se.normalize({"filter": "bw", "brightness": 0.3, "frame": {"width": 2, "color": "white"},
                        "texts": [{"text": "eski"}]})
    m = se.merge(cur, {"contrast": 0.4})
    assert m["filter"] == "bw" and m["brightness"] == 0.3 and m["contrast"] == 0.4 and m["texts"][0]["text"] == "eski"
    assert se.merge(cur, {"frame": {"color": "red"}})["frame"] == {"width": 2.0, "color": "#FF3B30"}   # maydon-maydon
    assert se.merge(cur, {"texts": [{"text": "yangi"}]})["texts"][0]["text"] == "yangi"               # texts to'liq almashadi
    assert se.merge(cur, {"reset": True}) == se.default_spec()
    assert se.merge(cur, {"reset": True, "filter": "sepia"})["filter"] == "sepia"
    assert se.merge(cur, "junk") == cur and se.merge(cur, None) == cur


def test_presets_and_describe():
    s = se.apply_preset(se.default_spec(), "bw")
    assert s["filter"] == "bw" and "qora-oq" in se.describe(s)
    assert se.apply_preset(s, "no-such-preset") == s
    assert se.apply_preset(s, "warm")["filter"] == "warm"                                              # filtr almashadi
    assert se.apply_preset(se.default_spec(), "fill")["fit"] == "fill"
    assert se.describe(se.default_spec()) == "o'zgarishsiz"
    d = se.describe(se.normalize({"texts": [{"text": "Salom"}], "rotate": 90, "zoom": 1.5, "video": {"speed": 2, "mute": True}}))
    assert "matn «Salom»" in d and "90°" in d and "zoom ×1.5" in d and "tezlik ×2" in d and "ovozsiz" in d


def test_effective_combines_filter_and_user_values():
    e = se.effective(se.normalize({"filter": "vivid", "saturation": 0.8}))
    assert e["saturation"] == 1.0 and e["contrast"] == pytest.approx(0.2)                              # 0.8+0.5 -> 1 ga qisqartirilgan
    assert se.effective(se.normalize({"filter": "bw"}))["gray"] == 1.0


# ── RASM renderi (haqiqiy Pillow) ──────────────────────────────────────────────
@pytest.fixture
def photo(tmp_path):
    im = Image.new("RGB", (800, 500), (40, 120, 200))
    px = im.load()
    for x in range(800):
        for y in range(500):
            px[x, y] = (40 + x // 8, 120, 200 - y // 5)
    p = tmp_path / "src.jpg"
    im.save(p, quality=95)
    return str(p)


def render(photo, tmp_path, **spec) -> Image.Image:
    out = str(tmp_path / "out.jpg")
    run(se.render_photo(photo, spec, out))
    return Image.open(out).convert("RGB")


def mean(im, box=None):
    return ImageStat.Stat(im.crop(box) if box else im).mean


def test_default_render_matches_story_format(photo, tmp_path):
    im = render(photo, tmp_path)
    assert im.size == stories.PHOTO_SIZE == (1080, 1920)
    assert os.path.getsize(tmp_path / "out.jpg") <= stories.MAX_PHOTO_BYTES


@pytest.mark.parametrize("fit,corner_check", [("black", lambda c: sum(c) < 30), ("white", lambda c: sum(c) > 720),
                                              ("color", lambda c: c[0] > 200 and c[1] < 80)])
def test_fit_modes_color_bars(photo, tmp_path, fit, corner_check):
    spec = {"fit": fit, "fit_color": "#FF2020"} if fit == "color" else {"fit": fit}
    im = render(photo, tmp_path, **spec)
    assert corner_check(im.getpixel((5, 5)))                                    # tepa chet — fon (rasm vertikal markazda)


def test_fill_has_no_bars_and_blur_has_dim_background(photo, tmp_path):
    fill = render(photo, tmp_path, fit="fill")
    assert fill.getpixel((5, 5)) != (0, 0, 0) and fill.getpixel((540, 5))[2] > 60       # butun kadr rasm bilan to'lgan
    blur = render(photo, tmp_path, fit="blur")
    assert blur.getpixel((5, 5)) != blur.getpixel((540, 960))                            # fon va markaz farq qiladi


def test_color_effects(photo, tmp_path):
    base = render(photo, tmp_path)
    bw = render(photo, tmp_path, filter="bw")
    r, g, b = bw.getpixel((540, 960))
    assert max(r, g, b) - min(r, g, b) < 6                                               # qora-oq: kanallar teng
    assert sum(mean(render(photo, tmp_path, brightness=0.6))) > sum(mean(base)) + 30
    assert sum(mean(render(photo, tmp_path, brightness=-0.6))) < sum(mean(base)) - 30
    warm, cool = mean(render(photo, tmp_path, warmth=1)), mean(render(photo, tmp_path, warmth=-1))
    assert warm[0] > cool[0] and warm[2] < cool[2]                                       # iliq: ko'proq qizil, kamroq ko'k
    sep = render(photo, tmp_path, filter="sepia").getpixel((540, 960))
    assert sep[0] > sep[2]                                                               # sepia: qizil > ko'k
    assert mean(render(photo, tmp_path, saturation=-1))[0] == pytest.approx(mean(render(photo, tmp_path, saturation=-1))[2], abs=3)


def test_vignette_blur_grain_sharpen(photo, tmp_path):
    base = render(photo, tmp_path, fit="fill")
    vig = render(photo, tmp_path, fit="fill", vignette=1.0)
    corner = lambda im: sum(im.getpixel((20, 20)))          # noqa: E731
    assert corner(vig) < corner(base) * 0.6 and sum(vig.getpixel((540, 960))) >= sum(base.getpixel((540, 960))) * 0.9
    grain = render(photo, tmp_path, fit="fill", grain=1.0)
    assert ImageStat.Stat(ImageChops.difference(grain, base).convert("L")).mean[0] > 3     # donadorlik qo'shdi
    blurred = render(photo, tmp_path, fit="fill", blur=1.0)
    edges = lambda im: ImageStat.Stat(im.convert("L").filter(__import__("PIL.ImageFilter", fromlist=["x"]).FIND_EDGES)).mean[0]  # noqa: E731
    assert edges(blurred) < edges(base)


def test_geometry(photo, tmp_path):
    left = render(photo, tmp_path, fit="fill", flip="h").getpixel((20, 960))
    right = render(photo, tmp_path, fit="fill").getpixel((1060, 960))
    assert abs(left[0] - right[0]) < 12                                                  # ag'darish: chap chetda avval o'ng chet rangi
    z = render(photo, tmp_path, fit="fill", zoom=2.0)
    assert mean(z) != mean(render(photo, tmp_path, fit="fill"))
    rot = render(photo, tmp_path, rotate=90)                                             # 90°: gorizontal rasm vertikal bo'ladi
    assert rot.size == (1080, 1920) and rot != render(photo, tmp_path)


def test_frame_draws_border(photo, tmp_path):
    im = render(photo, tmp_path, frame={"width": 4, "color": "white"})
    assert im.getpixel((2, 960)) == (255, 255, 255) and im.getpixel((1077, 960)) == (255, 255, 255)
    assert im.getpixel((100, 960)) != (255, 255, 255)


def test_text_overlay_position_style_and_wrapping(photo, tmp_path):
    ov = se.render_overlay(se.normalize({"texts": [{"text": "SALOM", "pos": "top", "size": 10, "color": "#FF0000", "style": "plain"}]}), (1080, 1920))
    bbox = ov.getchannel("A").getbbox()
    assert bbox and bbox[1] < 400 and bbox[3] < 500                                      # tepada
    assert ov.getpixel(((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2))[3] in range(0, 256)
    long = se.render_overlay(se.normalize({"texts": [{"text": "juda uzun matn " * 8, "size": 9, "pos": "center"}]}), (1080, 1920))
    lb = long.getchannel("A").getbbox()
    assert lb[0] >= 0.04 * 1080 - 2 and lb[2] <= 1080 * 0.96 + 2 and (lb[3] - lb[1]) > 150   # kenglikka sig'di, qatorlarga bo'lindi
    box = se.render_overlay(se.normalize({"texts": [{"text": "Box", "pos": "bottom", "style": "box", "color": "white"}]}), (1080, 1920))
    assert box.getchannel("A").getbbox()[2] - box.getchannel("A").getbbox()[0] > 200     # orqa fon to'rtburchagi ham bor
    for style in se.STYLES:
        assert se.render_overlay(se.normalize({"texts": [{"text": "Xayr", "style": style}]}), (720, 1280)).getchannel("A").getbbox()
    assert se.render_overlay(se.default_spec(), (720, 1280)).getchannel("A").getbbox() is None   # matn/ramka yo'q — shaffof


def test_text_appears_on_rendered_photo(photo, tmp_path):
    plain = render(photo, tmp_path)
    texted = render(photo, tmp_path, texts=[{"text": "Salom dunyo", "pos": "bottom", "size": 9}])
    diff = ImageChops.difference(plain, texted).convert("L")
    assert diff.crop((0, 1500, 1080, 1850)).getbbox() and not diff.crop((0, 0, 1080, 1000)).getbbox()


def test_unreadable_source_gives_friendly_error(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(stories.StoryError):
        run(se.render_photo(str(bad), {}, str(tmp_path / "o.jpg")))


def test_malicious_spec_cannot_blow_up_render(photo, tmp_path):
    im = render(photo, tmp_path, brightness=1e9, zoom=1e9, blur=1e9, texts=[{"text": "x" * 10_000, "size": 1e9}] * 50,
                frame={"width": 1e9}, fit="; rm -rf /", rotate="999999999999")
    assert im.size == (1080, 1920)


# ── VIDEO: filter grafi (sof funksiya) ─────────────────────────────────────────
def test_graph_fit_variants_and_overlay():
    g = se.build_video_graph(se.default_spec(), (720, 1280), False)
    assert "split=2" in g and "boxblur=30:6" in g and g.endswith("[v]") and "[1:v]" not in g
    assert "crop=720:1280" in se.build_video_graph(se.normalize({"fit": "fill"}), (720, 1280), False)
    pad = se.build_video_graph(se.normalize({"fit": "color", "fit_color": "#112233"}), (720, 1280), False)
    assert "pad=720:1280" in pad and "color=0x112233" in pad
    assert "[base][1:v]overlay=0:0" in se.build_video_graph(se.default_spec(), (720, 1280), True)


def test_graph_filters_map_to_ffmpeg():
    g = se.build_video_graph(se.normalize({"filter": "bw"}), (720, 1280), False)
    assert "hue=s=0.000" in g
    g = se.build_video_graph(se.normalize({"brightness": 0.5, "contrast": 0.5, "saturation": -0.5, "warmth": 1, "sharpness": 1,
                                           "blur": 1, "vignette": 1, "grain": 1, "rotate": 90, "flip": "h", "zoom": 2}),
                             (720, 1280), False)
    for needle in ("eq=brightness=0.150:contrast=1.300:saturation=0.500", "colorchannelmixer=rr=1.180:bb=0.820", "unsharp=",
                   "boxblur=lr=", "vignette=a=", "noise=alls=30", "transpose=1", "hflip", "crop=trunc(iw/2.0000/2)*2"):
        assert needle in g, needle
    assert "setpts=PTS/1.0000" in g


def test_graph_speed_and_fades():
    g = se.build_video_graph(se.normalize({"video": {"speed": 2, "fade_in": 1, "fade_out": 1}}), (720, 1280), False, out_len=10)
    assert "setpts=PTS/2.0000" in g and "fade=t=in:st=0:d=1.00" in g and "fade=t=out:st=9.00:d=1.00" in g
    assert "fade" not in se.build_video_graph(se.normalize({"video": {"fade_in": 1, "fade_out": 1}}), (720, 1280), False,
                                              out_len=10, preview=True)              # ko'rib chiqishda fade yo'q (qora kadr xatosi)
    assert se._audio_filter(se.normalize({"video": {"speed": 1.5, "fade_in": 1}}), 8) == "atempo=1.5000,afade=t=in:st=0:d=1.00"
    assert se._audio_filter(se.default_spec(), 8) is None


def test_timing_math():
    s = se.normalize({"video": {"speed": 2, "start": 2, "end": 8}})
    assert se._timing(s, 20) == (2.0, 6.0, 3.0)                                      # 6s kesilgan, 2x tez -> 3s
    assert se._timing(se.default_spec(), 20) == (0.0, None, 20.0)
    assert se._timing(se.normalize({"video": {"speed": 0.5}}), 50)[2] == stories.MAX_VIDEO_SECONDS   # 100s -> 60s bilan cheklanadi
    assert se._timing(se.normalize({"video": {"start": 100}}), 3)[0] <= 2.5          # boshlanish videodan oshsa ham yaroqli


# ── VIDEO: haqiqiy ffmpeg ──────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("clip")
    with_audio, silent = str(d / "a.mp4"), str(d / "s.mp4")
    base = ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x180:rate=15"]
    subprocess.run(base + ["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-shortest", with_audio], capture_output=True, check=True)
    subprocess.run(base + ["-c:v", "libx264", "-pix_fmt", "yuv420p", silent], capture_output=True, check=True)
    return SimpleNamespace(audio=with_audio, silent=silent)


def probe(path, entries, stream="v:0"):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries, "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return out


@needs_ffmpeg
def test_video_preview_frame_is_not_black_even_with_fade_in(clip, tmp_path):
    """Haqiqiy xato: fade-in 0-soniyada bitta kadrni TO'LIQ QORA qilardi."""
    out = str(tmp_path / "p.jpg")
    run(se.render_video_preview(clip.audio, se.normalize({"video": {"fade_in": 1, "fade_out": 1}}), out))
    im = Image.open(out)
    assert im.size == stories.VIDEO_SIZE and ImageStat.Stat(im.convert("L")).mean[0] > 30


@needs_ffmpeg
def test_video_render_format_audio_mute_speed_and_trim(clip, tmp_path):
    dst = str(tmp_path / "o.mp4")
    dur = run(se.render_video(clip.audio, se.normalize({"filter": "warm", "texts": [{"text": "Hi", "pos": "top"}]}), dst))
    assert probe(dst, "stream=width,height,codec_name") == "hevc,720,1280" and probe(dst, "stream=codec_name", "a:0") == "aac"
    assert dur == pytest.approx(3.0, abs=0.3)
    run(se.render_video(clip.audio, se.normalize({"video": {"mute": True, "speed": 2}}), dst))
    assert probe(dst, "stream=codec_name", "a:0") == ""                                   # ovozsiz
    assert float(probe(dst, "format=duration", "v:0").split(",")[-1] or 0) == pytest.approx(1.5, abs=0.35)
    run(se.render_video(clip.audio, se.normalize({"video": {"start": 1, "end": 2}}), dst))
    assert float(probe(dst, "format=duration", "v:0").split(",")[-1] or 0) == pytest.approx(1.0, abs=0.35)
    run(se.render_video(clip.silent, se.normalize({"video": {"speed": 1.5, "fade_in": 0.3}}), dst))   # ovozsiz kirish ham ishlaydi
    assert probe(dst, "stream=codec_name", "a:0") == ""


@needs_ffmpeg
def test_video_text_overlay_is_visible_in_preview(clip, tmp_path):
    plain, texted = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    run(se.render_video_preview(clip.audio, se.default_spec(), plain))
    run(se.render_video_preview(clip.audio, se.normalize({"texts": [{"text": "SALOM", "pos": "top", "size": 12}]}), texted))
    diff = ImageChops.difference(Image.open(plain).convert("RGB"), Image.open(texted).convert("RGB")).convert("L")
    assert diff.crop((0, 0, 720, 400)).getbbox() and not diff.crop((0, 600, 720, 1280)).getbbox()


@needs_ffmpeg
def test_bad_video_gives_friendly_error(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"nope")
    with pytest.raises(stories.StoryError):
        run(se.render_video(str(bad), {}, str(tmp_path / "o.mp4")))


# ── AI talqini ─────────────────────────────────────────────────────────────────
class FakeAI:
    def __init__(self, reply=None, boom=None):
        self.reply, self.boom, self.calls = reply, boom, []

    async def chat(self, messages, tools=None, user_id=None):
        self.calls.append(messages)
        if self.boom:
            raise self.boom
        msg = SimpleNamespace(content=self.reply if isinstance(self.reply, str) else json.dumps(self.reply))
        return {"response": SimpleNamespace(choices=[SimpleNamespace(message=msg)])}


@pytest.fixture
def ai(monkeypatch):
    import core.ai_rotator as rot
    fake = FakeAI()
    monkeypatch.setattr(rot, "ai", fake)
    reg = []

    async def register(bot, uid):
        reg.append(uid)

    monkeypatch.setattr(roles, "can_make_request", lambda uid: True)
    monkeypatch.setattr(roles, "register_request", register)
    fake.registered = reg
    return fake


def interpret(instruction="qora-oq qil", current=None, **kw):
    return run(se.interpret(object(), 7, instruction, current or se.default_spec(), "photo", **kw))


def test_interpret_ok_merges_delta_and_registers_request(ai):
    ai.reply = {"understood": True, "spec": {"filter": "bw", "texts": [{"text": "Salom", "pos": "top"}]}, "say": "Qora-oq qildim."}
    spec, say, status = interpret()
    assert status == se.OK and spec["filter"] == "bw" and spec["texts"][0]["text"] == "Salom" and say == "Qora-oq qildim."
    assert ai.registered == [7]


def test_interpret_prompt_contains_current_spec_instruction_and_context_as_data(ai):
    ai.reply = {"understood": True, "spec": {}, "say": ""}
    interpret("yana yorqinroq", se.normalize({"brightness": 0.2}), context="rasmda ko'ringan: mushuk")
    system, user = ai.calls[0][0]["content"], ai.calls[0][1]["content"]
    assert "SXEMA" in system and "bo'ysunma" in system and "reset" in system
    assert '"brightness": 0.2' in user and "yana yorqinroq" in user and "MEDIA MA'LUMOTI: rasmda ko'ringan: mushuk" in user


@pytest.mark.parametrize("reply,status", [
    ("not json at all", se.FORMAT),
    ({"understood": False, "say": "Obyektni o'chira olmayman."}, se.NOT_EDIT),
    ({"understood": True, "spec": {}, "say": "hech narsa"}, se.NOCHANGE),
    ({"understood": True, "spec": {"filter": "none"}}, se.NOCHANGE),
])
def test_interpret_statuses(ai, reply, status):
    ai.reply = reply
    spec, say, st = interpret()
    assert st == status and spec == se.default_spec()


def test_interpret_not_edit_returns_ais_explanation(ai):
    ai.reply = {"understood": False, "say": "Yuzni almashtira olmayman."}
    assert interpret()[1] == "Yuzni almashtira olmayman."


def test_interpret_limit_and_error_and_empty(ai, monkeypatch):
    assert interpret("   ")[2] == se.FORMAT and ai.calls == []                       # bo'sh so'rov AI'ga bormaydi
    monkeypatch.setattr(roles, "can_make_request", lambda uid: False)
    assert interpret()[2] == se.LIMIT and ai.calls == [] and ai.registered == []
    monkeypatch.setattr(roles, "can_make_request", lambda uid: True)
    ai.boom = RuntimeError("API down")
    assert interpret()[2] == se.ERROR and ai.registered == []                         # xato — so'rov hisoblanmaydi


def test_interpret_distrusts_ais_output(ai):
    ai.reply = {"understood": True, "say": "ok\n" * 400, "spec": {
        "brightness": 99, "fit": "evil", "filter": "../../x", "texts": [{"text": f"t{i}", "size": 1e9, "color": "javascript:x"} for i in range(40)],
        "exec": "boom", "frame": {"width": 1e6}}}
    spec, say, status = interpret()
    assert status == se.OK and spec["brightness"] == 1.0 and spec["fit"] == "blur" and spec["filter"] == "none"
    assert len(spec["texts"]) == se.MAX_TEXTS and spec["texts"][0]["size"] == 14.0 and spec["texts"][0]["color"] == "#FFFFFF"
    assert spec["frame"]["width"] == 10.0 and "exec" not in spec and len(say) <= 300


def test_interpret_user_text_is_length_limited(ai):
    ai.reply = {"understood": True, "spec": {}, "say": ""}
    interpret("x" * 5000)
    assert len(ai.calls[0][1]["content"]) < 2200
