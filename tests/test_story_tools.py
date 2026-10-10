"""Story kengaytmalari: bosiladigan maydonlar, joylash parametrlari/tarix, tahrir va sozlama oqimlari (handler), chatdagi AI tool."""
import asyncio
import os
import shutil
import time
from types import SimpleNamespace

import pytest
from PIL import Image
from aiogram.types import ReactionTypeEmoji

import core.stories as stories
import core.story_areas as sa
import core.story_caption as story_caption
import core.story_edit as se
import core.tariffs as tariffs
import core.tgdb as tgdb
import handlers.profile as profile
import handlers.story_tools as st_tools

U = 4242


def run(coro):
    return asyncio.run(coro)


# ── bosiladigan maydonlar ──────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("https://example.com/sahifa?x=1", "https://example.com/sahifa?x=1"),
    ("example.com", "https://example.com"),
    ("  t.me/paradoks  ", "https://t.me/paradoks"),
    ("http://sub.example.co.uk/a", "http://sub.example.co.uk/a"),
    ("https://xn--80ak6aa92e.com", "https://xn--80ak6aa92e.com"),
])
def test_clean_url_accepts(raw, expected):
    assert sa.clean_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "javascript:alert(1)", "ftp://example.com", "file:///etc/passwd", "https://", "https://localhost/x",
    "https://127.0.0.1/x", "https://10.0.0.5/admin", "https://[::1]/", "https://google.com@evil.com/", "https://a b.com",
    "https://nodot", "https://exa mple.com", "https://-bad-.com", "x" * 600, "https://example.com/\x00", "tg://resolve?domain=x",
])
def test_clean_url_rejects(raw):
    assert sa.clean_url(raw) is None


def test_build_areas_layout_and_caps():
    areas = sa.build(["https://a.com", "https://b.com", "https://c.com", "https://d.com"], ["❤", "🔥", "🤔", "👍", "😍", "🎉", "🤩"])
    links = [a for a in areas if a.type.type == "link"]
    reacts = [a for a in areas if a.type.type == "suggested_reaction"]
    assert len(links) == sa.MAX_LINKS and len(reacts) == sa.MAX_REACTIONS                      # 3 va 5 bilan cheklangan
    assert [a.type.url for a in links] == ["https://a.com", "https://b.com", "https://c.com"]
    assert [a.type.reaction_type.emoji for a in reacts] == ["❤", "🔥", "👍", "😍", "🎉"]        # 🤔 ruxsat etilmagan — tashlandi
    for a in areas:
        p = a.position
        assert 0 <= p.x_percentage - p.width_percentage / 2 and p.x_percentage + p.width_percentage / 2 <= 100
        assert 0 <= p.y_percentage - p.height_percentage / 2 and p.y_percentage + p.height_percentage / 2 <= 100
    ys = [a.position.y_percentage for a in links]
    assert len(set(ys)) == 3 and all(y > max(r.position.y_percentage for r in reacts) for y in ys)   # havolalar pastda, ustma-ust emas
    assert sa.build([], []) == [] and sa.build(["https://a.com"], [])[0].type.type == "link"


def test_summary():
    assert sa.summary([], []) == "" and "havolalar: 2" in sa.summary(["a", "b"], ["❤"]) and "❤" in sa.summary([], ["❤"])


# ── stories.post parametrlari va tarix ─────────────────────────────────────────
class PostBot:
    def __init__(self):
        self.kw = None

    async def post_story(self, **kw):
        self.kw = kw
        return SimpleNamespace(id=900 + len(kw))

    async def delete_story(self, **kw):
        self.deleted = kw


@pytest.fixture
def env(monkeypatch, tmp_path):
    db = {"users": {}}
    monkeypatch.setattr(tgdb, "_cache", db)
    monkeypatch.setattr(tgdb, "mark_dirty", lambda: None)
    monkeypatch.setattr(stories, "status", lambda uid: "ready")
    monkeypatch.setattr(stories, "get_connection", lambda uid: {"id": "conn1"})
    monkeypatch.setattr(stories, "work_dir", lambda uid: str(tmp_path))
    profile._waiting.clear()
    yield SimpleNamespace(db=db, tmp=tmp_path)
    profile._waiting.clear()


def test_post_passes_protect_page_and_areas(env, tmp_path):
    f = tmp_path / "p.jpg"
    Image.new("RGB", (50, 50)).save(f)
    bot = PostBot()
    areas = sa.build(["https://a.com"], ["🔥"])
    run(stories.post(bot, U, "photo", str(f), hours=12, caption="Salom", protect_content=True, post_to_chat_page=False, areas=areas))
    assert bot.kw["protect_content"] is True and bot.kw["post_to_chat_page"] is False and bot.kw["areas"] == areas
    assert bot.kw["active_period"] == stories.PERIODS[12] and bot.kw["business_connection_id"] == "conn1"
    run(stories.post(bot, U, "photo", str(f)))                                                  # standart: hech narsa o'zgarmagan
    assert bot.kw["protect_content"] is None and bot.kw["post_to_chat_page"] is True and bot.kw["areas"] is None


def test_history_records_lists_only_active_and_forgets(env, tmp_path):
    f = tmp_path / "p.jpg"
    Image.new("RGB", (50, 50)).save(f)
    bot = PostBot()
    s1 = run(stories.post(bot, U, "photo", str(f), hours=24, caption="birinchi"))
    s2 = run(stories.post(bot, U, "photo", str(f), hours=6, caption="x" * 200))
    posts = stories.list_posts(U)
    assert [p["id"] for p in posts] == [s2.id, s1.id] and len(posts[0]["c"]) == 60               # eng yangisi birinchi; izoh qisqartirilgan
    env.db["story_posts"][str(U)][1]["t"] -= 25 * 3600                                           # birinchisining muddati tugagan
    assert [p["id"] for p in stories.list_posts(U)] == [s2.id]
    run(stories.delete(bot, U, s2.id))
    assert stories.list_posts(U) == [] and bot.deleted == {"business_connection_id": "conn1", "story_id": s2.id}
    assert stories.list_posts(999) == []


def test_history_is_capped_and_never_breaks_posting(env, tmp_path, monkeypatch):
    for i in range(stories.HISTORY_LIMIT + 5):
        stories.remember_post(U, i, "photo", None, 24)
    assert len(env.db["story_posts"][str(U)]) == stories.HISTORY_LIMIT
    monkeypatch.setattr(tgdb, "_cache", None)                                                    # DB yo'q — joylash baribir ishlaydi
    f = tmp_path / "p.jpg"
    Image.new("RGB", (50, 50)).save(f)
    assert run(stories.post(PostBot(), U, "photo", str(f))).id


# ── handler soxtalari ──────────────────────────────────────────────────────────
class Sent(SimpleNamespace):
    async def edit_text(self, text, reply_markup=None):
        self.texts.append(text)

    async def delete(self):
        self.deleted = True


class Bot:
    def __init__(self):
        self.messages, self.photos, self.deleted, self._n, self.sent_objs = [], [], [], 100, []

    def _msg(self, chat_id):
        self._n += 1
        return Sent(message_id=self._n, chat=SimpleNamespace(id=chat_id), texts=[], deleted=False)

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.messages.append((chat_id, text, reply_markup))
        obj = self._msg(chat_id)
        self.sent_objs.append(obj)
        return obj

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kw):
        self.photos.append((chat_id, getattr(photo, "path", photo), caption, reply_markup))
        return self._msg(chat_id)

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class Call:
    def __init__(self, data, bot, uid=U):
        self.data, self.bot, self.from_user, self.answers, self.edits, self.sent = data, bot, SimpleNamespace(id=uid), [], [], []
        outer = self

        class M:
            chat = SimpleNamespace(id=uid)
            message_id = 50

            async def edit_text(self, text, reply_markup=None):
                outer.edits.append((text, reply_markup))

            async def answer(self, text, reply_markup=None):
                outer.sent.append(text)

        self.message = M()

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class Msg:
    def __init__(self, text, bot, uid=U):
        self.text, self.bot, self.from_user = text, bot, SimpleNamespace(id=uid)
        self.chat, self.replies = SimpleNamespace(type="private", id=uid), []

    async def answer(self, text, reply_markup=None):
        sent = Sent(texts=[text], deleted=False, message_id=1, chat=self.chat)
        self.replies.append(sent)
        return sent


def all_text(call_or_msg):
    if isinstance(call_or_msg, Msg):
        return " ".join(t for r in call_or_msg.replies for t in r.texts)
    return " ".join(t for t, _ in call_or_msg.edits)


def make_state(env, kind="photo", **extra):
    src, prepared = env.tmp / "src.jpg", env.tmp / "prepared.jpg"
    Image.new("RGB", (600, 400), (30, 90, 200)).save(src)
    shutil.copy(src, prepared)
    st = {"step": "period", "t": time.time(), "path": str(prepared), "src": str(src), "kind": kind, "duration": None, "anim": False,
          "orig_caption": None, "orig_entities": None, "regen": 0, "caption": None, "mode": story_caption.NONE, "reason": None,
          "entities": None, **extra}
    profile._waiting[U] = st
    return st


@pytest.fixture
def paid(monkeypatch):
    monkeypatch.setattr(tariffs, "can_caption", lambda uid: True)


@pytest.fixture
def free(monkeypatch):
    monkeypatch.setattr(tariffs, "can_caption", lambda uid: False)


# ── 🎨 tahrirlash: tayyor tugmalar ─────────────────────────────────────────────
def test_edit_open_and_preset_flow(env, free):
    st, bot = make_state(env), Bot()
    c = Call("profile:edit", bot)
    run(st_tools.edit_open(c, bot))
    assert st["step"] == "edit" and st["orig_path"] == st["path"] and "Plus/Pro" in all_text(c)          # bepul: erkin matn yopiq
    c = Call("profile:ep:bw", bot)
    run(st_tools.edit_preset(c, bot))
    assert st["spec"]["filter"] == "bw" and len(bot.photos) == 1 and os.path.exists(st["preview"])
    assert Image.open(st["preview"]).size == (1080, 1920) and "qora-oq" in bot.photos[0][2]
    assert st["ui"][1] == 101 and st["spec_hist"][-1]["filter"] == "none" and st["busy"] is False
    c = Call("profile:ep:bw", bot)                                                                       # xuddi shu tahrir — qayta render yo'q
    run(st_tools.edit_preset(c, bot))
    assert len(bot.photos) == 1 and c.answers[-1][0] == "Bu allaqachon qo'llangan"
    c = Call("profile:ep:warm", bot)
    run(st_tools.edit_preset(c, bot))
    assert st["spec"]["filter"] == "warm" and len(bot.photos) == 2 and (U, 101) in bot.deleted           # eski ko'rib chiqish o'chirildi


def test_preset_render_failure_reverts_spec(env, free, monkeypatch):
    st, bot = make_state(env, step="edit"), Bot()

    async def boom(kind, src, spec, dst):
        raise stories.StoryError("render buzildi")

    monkeypatch.setattr(se, "render_preview", boom)
    run(st_tools.edit_preset(Call("profile:ep:bw", bot), bot))
    assert se.is_noop(st["spec"]) and st["spec_hist"] == [] and "render buzildi" in bot.messages[-1][1] and st["busy"] is False


def test_busy_flag_blocks_parallel_taps(env, free):
    st, bot = make_state(env, step="edit", busy=True), Bot()
    c = Call("profile:ep:bw", bot)
    run(st_tools.edit_preset(c, bot))
    assert c.answers == [("Biroz kuting…", False)] and bot.photos == []


@pytest.mark.parametrize("handler,data", [("edit_open", "profile:edit"), ("edit_preset", "profile:ep:bw"), ("edit_done", "profile:ed:done"),
                                          ("edit_undo", "profile:ed:undo"), ("edit_reset", "profile:ed:reset"), ("edit_back", "profile:ed:back")])
def test_edit_handlers_need_live_session(env, free, handler, data):
    bot = Bot()
    c = Call(data, bot)
    run(getattr(st_tools, handler)(c, bot))
    assert c.answers and "Sessiya tugagan" in c.answers[0][0] and c.answers[0][1] is True and bot.photos == []


def test_unknown_preset_is_rejected(env, free):
    make_state(env, step="edit")
    bot, c = Bot(), Call("profile:ep:rm-rf", None)
    c.bot = bot
    run(st_tools.edit_preset(c, bot))
    assert "Sessiya tugagan" in c.answers[0][0] and bot.photos == []


# ── 🎨 tahrirlash: erkin matn (AI) ─────────────────────────────────────────────
def patch_interpret(monkeypatch, result):
    calls = []

    async def fake(bot, uid, instruction, current, kind, context=""):
        calls.append((instruction, current, kind, context))
        return result

    monkeypatch.setattr(se, "interpret", fake)
    return calls


def test_free_user_cannot_use_ai_text(env, free, monkeypatch):
    make_state(env, step="edit")
    calls = patch_interpret(monkeypatch, (se.default_spec(), "", se.OK))
    bot, m = Bot(), Msg("qora-oq qil", None)
    m.bot = bot
    run(st_tools.edit_text(m, bot))
    assert calls == [] and "Plus/Pro" in all_text(m) and bot.photos == []


def test_ai_text_applies_spec_and_shows_preview(env, paid, monkeypatch):
    st, bot = make_state(env, step="edit", media_cache={"vision": "dengiz va quyosh", "ocr": "SALOM"}), Bot()
    new = se.normalize({"filter": "vintage", "texts": [{"text": "Xayrli tong", "pos": "top"}]})
    calls = patch_interpret(monkeypatch, (new, "Vintage qildim.", se.OK))
    m = Msg("vintage qil, tepaga Xayrli tong yoz", bot)
    run(st_tools.edit_text(m, bot))
    assert st["spec"] == new and len(bot.photos) == 1 and "Vintage qildim." in bot.photos[0][2] and "Xayrli tong" in bot.photos[0][2]
    assert calls[0][2] == "photo" and "dengiz va quyosh" in calls[0][3] and "SALOM" in calls[0][3]      # kontekst ma'lumot sifatida
    assert m.replies[0].deleted is True and st["busy"] is False                                         # "tushunilmoqda" xabari tozalandi


@pytest.mark.parametrize("status,needle", [
    (se.LIMIT, "limit"), (se.ERROR, "AI xizmati"), (se.FORMAT, "tushunolmadim"), (se.NOT_EDIT, "Yuzni almashtira"),
    (se.NOCHANGE, "o'zgarmadi"),
])
def test_ai_text_statuses_do_not_change_anything(env, paid, monkeypatch, status, needle):
    st, bot = make_state(env, step="edit"), Bot()
    patch_interpret(monkeypatch, (se.default_spec(), "Yuzni almashtira olmayman." if status == se.NOT_EDIT else "", status))
    m = Msg("biror narsa", bot)
    run(st_tools.edit_text(m, bot))
    assert needle in all_text(m) and bot.photos == [] and se.is_noop(st["spec"] or se.default_spec()) and st["busy"] is False


def test_ai_text_render_failure_reverts(env, paid, monkeypatch):
    st, bot = make_state(env, step="edit"), Bot()
    patch_interpret(monkeypatch, (se.normalize({"filter": "bw"}), "", se.OK))

    async def boom(kind, src, spec, dst):
        raise RuntimeError("ffmpeg yo'q")

    monkeypatch.setattr(se, "render_preview", boom)
    run(st_tools.edit_text(Msg("qora-oq", bot), bot))
    assert se.is_noop(st["spec"]) and st["spec_hist"] == [] and st["busy"] is False


def test_text_filters_only_match_the_right_step(env, paid):
    make_state(env, step="period")
    assert st_tools._waiting_edit_text(Msg("salom", None)) is False
    profile._waiting[U]["step"] = "edit"
    assert st_tools._waiting_edit_text(Msg("salom", None)) is True and st_tools._waiting_edit_text(Msg("/start", None)) is False
    profile._waiting[U]["step"] = "link"
    assert st_tools._waiting_link(Msg("example.com", None)) is True and st_tools._waiting_edit_text(Msg("x", None)) is False
    stranger = Msg("salom", None, uid=999)
    assert st_tools._waiting_edit_text(stranger) is False and st_tools._waiting_link(stranger) is False


# ── undo / reset / back / done ─────────────────────────────────────────────────
def test_undo_reset_and_back(env, free):
    st, bot = make_state(env), Bot()
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    orig = st["path"]
    run(st_tools.edit_preset(Call("profile:ep:bw", bot), bot))
    run(st_tools.edit_preset(Call("profile:ep:warm", bot), bot))
    c = Call("profile:ed:undo", bot)
    run(st_tools.edit_undo(c, bot))
    assert st["spec"]["filter"] == "bw"
    run(st_tools.edit_undo(Call("profile:ed:undo", bot), bot))
    assert se.is_noop(st["spec"])                                                                        # to'liq qaytdi — menyu
    c = Call("profile:ed:undo", bot)
    run(st_tools.edit_undo(c, bot))
    assert c.answers[-1] == ("Orqaga qaytadigan narsa yo'q", True)
    run(st_tools.edit_preset(Call("profile:ep:vivid", bot), bot))
    run(st_tools.edit_reset(Call("profile:ed:reset", bot), bot))
    assert se.is_noop(st["spec"]) and "bekor qilindi" in bot.messages[-1][1]
    run(st_tools.edit_preset(Call("profile:ep:sepia" if False else "profile:ep:cool", bot), bot))
    preview = st["preview"]
    run(st_tools.edit_back(Call("profile:ed:back", bot), bot))
    assert st["step"] == "period" and st["spec"] is None and st["path"] == orig and st["preview"] is None
    assert not os.path.exists(preview) and "Story qancha vaqt" in bot.messages[-1][1]


def test_done_photo_uses_the_reviewed_file(env, free):
    st, bot = make_state(env), Bot()
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    orig = st["path"]
    run(st_tools.edit_preset(Call("profile:ep:bw", bot), bot))
    reviewed = st["preview"]
    run(st_tools.edit_done(Call("profile:ed:done", bot), bot))
    assert st["step"] == "period" and st["path"] == reviewed == st["edited"] and st["path"] != orig and os.path.exists(orig)
    assert Image.open(st["path"]).size == (1080, 1920)
    last = bot.messages[-1][1]
    assert "Tahrir:" in last and "qora-oq" in last                                                       # davomiylik ko'rinishida tahrir ko'rinadi


def test_done_without_changes_keeps_original(env, free):
    st, bot = make_state(env), Bot()
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    orig = st["path"]
    c = Call("profile:ed:done", bot)
    run(st_tools.edit_done(c, bot))
    assert st["step"] == "period" and st["path"] == orig and st["spec"] is None and "Tahrir:" not in bot.messages[-1][1]


def finish_edit(st, bot, preset):
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    run(st_tools.edit_preset(Call(f"profile:ep:{preset}", bot), bot))
    run(st_tools.edit_done(Call("profile:ed:done", bot), bot))


def test_cancel_returns_to_session_start_not_to_the_original(env, free):
    """Yakunlangan tahrirdan keyin qayta kirib 'bekor qilish' — oldingi yakunlangan tahrirni YO'QOTMASLIGI kerak."""
    st, bot = make_state(env), Bot()
    orig = st["path"]
    finish_edit(st, bot, "bw")
    first = st["path"]
    assert first != orig and st["spec"]["filter"] == "bw"
    run(st_tools.edit_open(Call("profile:edit", bot), bot))                         # qayta kirdik
    run(st_tools.edit_preset(Call("profile:ep:warm", bot), bot))                    # boshqa tahrir sinadik
    assert st["spec"]["filter"] == "warm"
    run(st_tools.edit_back(Call("profile:ed:back", bot), bot))                      # bekor qildik
    assert st["path"] == first and os.path.exists(first) and st["spec"]["filter"] == "bw" and st["spec_hist"] == []
    assert st["preview"] is None and st["step"] == "period"
    assert os.path.exists(orig)


def test_cancel_on_first_session_restores_original(env, free):
    st, bot = make_state(env), Bot()
    orig = st["path"]
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    run(st_tools.edit_preset(Call("profile:ep:vivid", bot), bot))
    run(st_tools.edit_back(Call("profile:ed:back", bot), bot))
    assert st["path"] == orig and st["spec"] is None


def test_reset_then_done_restores_the_original_file_and_cleans_up(env, free):
    st, bot = make_state(env), Bot()
    orig = st["path"]
    finish_edit(st, bot, "bw")
    edited = st["path"]
    assert edited != orig and os.path.exists(edited)
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    run(st_tools.edit_reset(Call("profile:ed:reset", bot), bot))
    run(st_tools.edit_done(Call("profile:ed:done", bot), bot))
    assert st["path"] == orig and st["spec"] is None and st.get("edited") is None       # spec va fayl MUVOFIQ
    assert not os.path.exists(edited) and "Tahrir:" not in bot.messages[-1][1]


def test_second_done_does_not_leak_the_previous_edited_file(env, free):
    st, bot = make_state(env), Bot()
    finish_edit(st, bot, "bw")
    first = st["path"]
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    run(st_tools.edit_preset(Call("profile:ep:warm", bot), bot))
    run(st_tools.edit_done(Call("profile:ed:done", bot), bot))
    assert st["path"] != first and not os.path.exists(first) and os.path.exists(st["path"])
    assert st["spec"]["filter"] == "warm"                                              # tahrir davom ettirilgan (bw ustiga warm emas, almashgan)


def test_reentering_edit_starts_from_the_applied_spec(env, free):
    st, bot = make_state(env), Bot()
    finish_edit(st, bot, "bw")
    c = Call("profile:edit", bot)
    run(st_tools.edit_open(c, bot))
    assert "qora-oq" in all_text(c)                                                    # qo'llangan tahrir menyuda ko'rinadi


def test_done_video_renders_full_clip(env, free, monkeypatch):
    st, bot = make_state(env, kind="video", duration=9.0), Bot()
    seen = {}

    async def preview(kind, src, spec, dst):
        Image.new("RGB", (720, 1280), (10, 20, 30)).save(dst)

    async def render_video(src, spec, dst):
        seen["spec"] = spec
        open(dst, "wb").write(b"video")
        return 4.5

    monkeypatch.setattr(se, "render_preview", preview)
    monkeypatch.setattr(se, "render_video", render_video)
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    run(st_tools.edit_preset(Call("profile:ep:vivid", bot), bot))
    run(st_tools.edit_done(Call("profile:ed:done", bot), bot))
    assert st["path"].endswith(".mp4") and st["duration"] == 4.5 and seen["spec"]["filter"] == "vivid" and st["step"] == "period"


def test_done_video_render_failure_keeps_editing(env, free, monkeypatch):
    st, bot = make_state(env, kind="video"), Bot()

    async def preview(kind, src, spec, dst):
        Image.new("RGB", (72, 128)).save(dst)

    async def boom(src, spec, dst):
        raise stories.StoryError("Video 30 MB dan kichik qilib siqilmadi")

    monkeypatch.setattr(se, "render_preview", preview)
    monkeypatch.setattr(se, "render_video", boom)
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    run(st_tools.edit_preset(Call("profile:ep:vivid", bot), bot))
    run(st_tools.edit_done(Call("profile:ed:done", bot), bot))
    assert st["step"] == "edit" and st["busy"] is False and st["path"] == st["orig_path"]       # tahrirni davom ettirish mumkin
    assert "30 MB" in bot.sent_objs[-1].texts[-1] and st.get("edited") is None


def test_drop_cleans_every_temp_file(env, free):
    st, bot = make_state(env), Bot()
    run(st_tools.edit_open(Call("profile:edit", bot), bot))
    run(st_tools.edit_preset(Call("profile:ep:bw", bot), bot))
    st["edited"] = str(env.tmp / "edited.jpg")
    shutil.copy(st["src"], st["edited"])
    files = [st["path"], st["orig_path"], st["src"], st["preview"], st["edited"]]
    assert all(os.path.exists(f) for f in files)
    profile._drop(U)
    assert not any(os.path.exists(f) for f in files) and U not in profile._waiting


# ── ⚙️ sozlamalar ──────────────────────────────────────────────────────────────
def test_options_toggle_and_view(env):
    st, bot = make_state(env), Bot()
    c = Call("profile:opts", bot)
    run(st_tools.opts_open(c))
    assert "Himoya" in all_text(c) and "Profilda saqlash" in all_text(c)
    run(st_tools.opts_toggle(Call("profile:o:protect", bot)))
    run(st_tools.opts_toggle(Call("profile:o:page", bot)))
    assert st["opts"]["protect"] is True and st["opts"]["page"] is False
    text, _ = profile._period_view(st)
    assert "himoyalangan" in text and "profilda saqlanmaydi" in text and "yo'qoladi" in text
    run(st_tools.opts_toggle(Call("profile:o:protect", bot)))
    assert st["opts"]["protect"] is False


def test_link_flow_validates_dedupes_and_caps(env):
    st, bot = make_state(env), Bot()
    run(st_tools.opts_link_ask(Call("profile:o:link", bot)))
    assert st["step"] == "link"
    m = Msg("javascript:alert(1)", bot)
    run(st_tools.opts_link_receive(m))
    assert st["step"] == "link" and st["opts"]["links"] == [] and "yaroqsiz" in all_text(m)
    for url in ("example.com", "https://example.com", "https://b.com", "https://c.com"):                # takror qo'shilmaydi, 3 tadan ortmaydi
        st["step"] = "link"
        run(st_tools.opts_link_receive(Msg(url, bot)))
    assert st["opts"]["links"] == ["https://example.com", "https://b.com", "https://c.com"] and st["step"] == "period"
    c = Call("profile:o:link", bot)
    run(st_tools.opts_link_ask(c))
    assert c.answers[-1][1] is True and st["step"] == "period"                                            # 4-chi havolaga ruxsat yo'q
    run(st_tools.opts_toggle(Call("profile:o:clear", bot)))
    assert st["opts"]["links"] == [] and st["opts"]["reactions"] == []


def test_reactions_toggle_cap_and_back(env):
    st, bot = make_state(env), Bot()
    answers = []
    for i in range(6):
        c = Call(f"profile:o:r:{i}", bot)
        run(st_tools.react_toggle(c))
        answers.append(c.answers[-1])
    assert st["opts"]["reactions"] == sa.REACTIONS[:5]
    assert answers[5][1] is True and "Eng ko'pi" in answers[5][0] and all(not a[1] for a in answers[:5])   # 6-chisiga ruxsat yo'q
    run(st_tools.react_toggle(Call("profile:o:r:0", bot)))
    assert sa.REACTIONS[0] not in st["opts"]["reactions"]
    run(st_tools.react_toggle(Call("profile:o:r:99", bot)))                                               # yaroqsiz indeks — jim
    run(st_tools.react_toggle(Call("profile:o:r:abc", bot)))
    c = Call("profile:o:back", bot)
    run(st_tools.opts_back(c))
    assert "Story qancha vaqt" in all_text(c) and st["step"] == "period"


def test_story_post_sends_options_and_areas(env, monkeypatch):
    st, bot = make_state(env, opts={"protect": True, "page": False, "links": ["https://a.com"], "reactions": ["🔥"]}), Bot()
    got = {}

    async def fake_post(bot_, uid, kind, path, **kw):
        got.update(kw, kind=kind, path=path)
        return SimpleNamespace(id=555)

    monkeypatch.setattr(stories, "post", fake_post)
    c = Call("profile:post:24", bot)
    run(profile.story_post(c, bot))
    assert got["protect_content"] is True and got["post_to_chat_page"] is False and got["hours"] == 24
    assert [a.type.type for a in got["areas"]] == ["link", "suggested_reaction"] and got["path"] == st["path"]
    msg = all_text(c)
    assert "Saqlash va forward taqiqlangan" in msg and "yo'qoladi" in msg and "havolalar: 1" in msg
    assert U not in profile._waiting                                                                       # joylangach holat tozalanadi


def test_story_post_defaults_unchanged(env, monkeypatch):
    make_state(env)
    got = {}

    async def fake_post(bot_, uid, kind, path, **kw):
        got.update(kw)
        return SimpleNamespace(id=1)

    monkeypatch.setattr(stories, "post", fake_post)
    run(profile.story_post(Call("profile:post:6", Bot()), Bot()))
    assert got["protect_content"] is False and got["post_to_chat_page"] is True and got["areas"] == []


# ── 🗂 story'larim ─────────────────────────────────────────────────────────────
def test_my_stories_lists_active_and_has_delete_buttons(env):
    stories.remember_post(U, 11, "photo", "birinchi", 24)
    stories.remember_post(U, 12, "video", None, 6)
    c = Call("profile:mine", Bot())
    run(st_tools.my_stories(c))
    text, kb = c.edits[0]
    assert "1." in text and "2." in text and "«birinchi»" in text and "📷" in text and "🎬" in text
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "profile:del:11" in datas and "profile:del:12" in datas and "profile:menu" in datas
    stories.forget_post(U, 11)
    stories.forget_post(U, 12)
    c = Call("profile:mine", Bot())
    run(st_tools.my_stories(c))
    assert "yo'q" in c.edits[0][0]


def test_menu_has_my_stories_button(env):
    _, kb = profile._menu(U)
    assert "profile:mine" in [b.callback_data for row in kb.inline_keyboard for b in row]


def test_router_registered_before_ai_chat():
    src = open("main.py", encoding="utf-8").read()
    assert src.index("include_router(story_tools_router)") < src.index("include_router(ai_chat_router)")


# ── chatdagi AI tool: post_story ───────────────────────────────────────────────
import core.ai_tools as ai_tools  # noqa: E402


class ToolBot:
    def __init__(self):
        self.photos = []

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.photos.append((chat_id, caption))
        return SimpleNamespace(message_id=1)


@pytest.fixture
def tool(env, monkeypatch):
    f = env.tmp / "rasm.jpg"
    Image.new("RGB", (600, 400), (30, 90, 200)).save(f)
    monkeypatch.setattr("tools.file_tools.user_dir", lambda uid: str(env.tmp))
    posts, prepared = [], []

    async def prepare(kind, src, wd):
        new = os.path.join(wd, f"prepared_{len(prepared)}.jpg")
        shutil.copy(src, new)
        prepared.append(new)
        return new, None

    async def fake_post(bot, uid, kind, path, **kw):
        posts.append(dict(kw, kind=kind, path=path, exists=os.path.exists(path)))
        return SimpleNamespace(id=321)

    monkeypatch.setattr(stories, "prepare", prepare)
    monkeypatch.setattr(stories, "post", fake_post)
    ai_tools._STORY_PENDING.clear()
    monkeypatch.setattr(tariffs, "can_caption", lambda uid: True)
    return SimpleNamespace(posts=posts, prepared=prepared, bot=ToolBot(), env=env)


def call_tool(t, args, message_id=1, **ctx):
    full = {"bot": t.bot, "chat_id": U, "is_group": False, "message_id": message_id, **ctx}
    return run(ai_tools._post_story(U, {"file_name": "rasm.jpg", **args}, full))


def test_tool_plain_post_unchanged(tool):
    r = call_tool(tool, {"hours": 12})
    assert r["status"] == "story qo'yildi" and tool.posts[0]["hours"] == 12 and tool.prepared and tool.bot.photos == []
    assert not os.path.exists(tool.prepared[0]) and os.path.exists(tool.env.tmp / "rasm.jpg")        # vaqtinchalik fayl tozalandi, asl qoladi
    assert tool.posts[0]["protect_content"] is False and tool.posts[0]["areas"] == []


def test_tool_free_users_cannot_use_caption_or_edit(tool, monkeypatch):
    monkeypatch.setattr(tariffs, "can_caption", lambda uid: False)
    for args in ({"caption": "Salom"}, {"edit": {"filter": "bw"}}):
        r = call_tool(tool, args)
        assert "Plus/Pro" in r["error"]
    assert tool.posts == [] and tool.bot.photos == []
    assert call_tool(tool, {})["status"] == "story qo'yildi"                                              # izoh/tahrirsiz — hamma uchun
    assert call_tool(tool, {"edit": {"brightness": 0}})["status"] == "story qo'yildi"                     # bo'sh tahrir — tahrir emas


def test_tool_edit_requires_preview_then_confirmation_in_later_message(tool):
    edit = {"filter": "bw", "texts": [{"text": "Salom", "pos": "top"}]}
    r = call_tool(tool, {"edit": edit}, message_id=10)                                                    # 1) ko'rib chiqish
    assert "ko'rib chiqish yuborildi" in r["status"] and len(tool.bot.photos) == 1 and tool.posts == []
    r = call_tool(tool, {"edit": edit, "confirmed": True}, message_id=10)                                 # 2) o'sha xabarda tasdiq — bo'lmaydi
    assert "ko'rib chiqish yuborildi" in r["status"] and tool.posts == [] and len(tool.bot.photos) == 2
    r = call_tool(tool, {"edit": edit, "confirmed": True}, message_id=11)                                 # 3) keyingi xabarda — joylanadi
    assert r["status"] == "story qo'yildi" and len(tool.posts) == 1 and tool.posts[0]["exists"] is True
    assert Image.open(tool.env.tmp / "rasm.jpg").size == (600, 400)                                       # asl fayl tegilmagan
    assert call_tool(tool, {"edit": edit, "confirmed": True}, message_id=12)["status"].startswith("ko'rib")  # tasdiq bir martalik


def test_tool_confirmation_needs_matching_edit_and_fresh_preview(tool, monkeypatch):
    call_tool(tool, {"edit": {"filter": "bw"}}, message_id=1)
    r = call_tool(tool, {"edit": {"filter": "sepia"}, "confirmed": True}, message_id=2)                   # boshqa tahrir — qayta ko'rsatiladi
    assert r["status"].startswith("ko'rib") and tool.posts == []
    ai_tools._STORY_PENDING[U] = (ai_tools._STORY_PENDING[U][0], 2, time.time() - ai_tools._STORY_CONFIRM_TTL - 1)
    assert call_tool(tool, {"edit": {"filter": "sepia"}, "confirmed": True}, message_id=3)["status"].startswith("ko'rib")   # muddati o'tgan
    assert call_tool(tool, {"edit": {"filter": "sepia"}, "confirmed": "true"}, message_id=4)["status"].startswith("ko'rib")  # faqat haqiqiy True


def test_tool_unconfirmed_never_posts_without_previous_preview(tool):
    r = call_tool(tool, {"edit": {"filter": "bw"}, "confirmed": True}, message_id=5)
    assert r["status"].startswith("ko'rib") and tool.posts == []


def test_tool_video_edit_goes_through_render_video(tool, monkeypatch):
    (tool.env.tmp / "klip.mp4").write_bytes(b"x")
    out = {}

    async def rp(kind, src, spec, dst):
        Image.new("RGB", (72, 128)).save(dst)

    async def rv(src, spec, dst):
        out["spec"] = spec
        open(dst, "wb").write(b"v")
        return 3.0

    monkeypatch.setattr(se, "render_preview", rp)
    monkeypatch.setattr(se, "render_video", rv)
    args = {"file_name": "klip.mp4", "edit": {"video": {"speed": 2}}}
    run(ai_tools._post_story(U, args, {"bot": tool.bot, "chat_id": U, "is_group": False, "message_id": 1}))
    r = run(ai_tools._post_story(U, dict(args, confirmed=True), {"bot": tool.bot, "chat_id": U, "is_group": False, "message_id": 2}))
    assert r["status"] == "story qo'yildi" and out["spec"]["video"]["speed"] == 2.0 and tool.posts[0]["duration"] == 3.0


def test_tool_links_reactions_and_protect(tool):
    r = call_tool(tool, {"links": ["example.com", "https://t.me/x"], "reactions": ["🔥", "🤔", "❤"], "protect_content": True})
    assert r["status"] == "story qo'yildi"
    p = tool.posts[0]
    assert p["protect_content"] is True and [a.type.type for a in p["areas"]] == ["link", "link", "suggested_reaction", "suggested_reaction"]
    bad = call_tool(tool, {"links": ["https://ok.com", "javascript:alert(1)"]})
    assert "Havola yaroqsiz" in bad["error"] and len(tool.posts) == 1


def test_tool_guards(tool, monkeypatch):
    assert "faqat shaxsiy" in call_tool(tool, {}, is_group=True)["error"]
    assert "topilmadi" in run(ai_tools._post_story(U, {"file_name": "../../etc/passwd"}, {"bot": tool.bot, "chat_id": U, "is_group": False}))["error"]
    monkeypatch.setattr(stories, "status", lambda uid: "none")
    assert "ulanmagan" in call_tool(tool, {})["error"]


def test_tool_schema_describes_new_parameters():
    props = next(t for t in ai_tools.TOOLS if t["function"]["name"] == "post_story")["function"]["parameters"]["properties"]
    for key in ("edit", "confirmed", "protect_content", "links", "reactions"):
        assert key in props
