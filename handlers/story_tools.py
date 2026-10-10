"""
Story qo'shimcha imkoniyatlari (handlers/profile.py oqimiga ulanadi):

  🎨 Tahrirlash   — tayyor tugmalar (hamma tarifda) + oddiy so'z bilan AI-tahrir (Plus/Pro, izoh bilan bir xil qoida):
                    filtr, rang, matn, ramka, kesish/zoom, fon, video tezligi/kesish/ovozsiz/fade. Natija joylashdan OLDIN
                    ko'rib chiqiladi (rasm/video kadri); asl fayl o'zgarmaydi (har safar asldan render).
  ⚙️ Qo'shimcha   — himoya (saqlash/forward taqiqi), profilda saqlash, havola va reaksiya maydonlari.
  🗂 Story'larim  — bot orqali qo'yilgan faol storylar va ularni o'chirish.
"""
import html
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

import core.roles as roles
import core.story_areas as story_areas
import core.story_edit as story_edit
import core.stories as stories
import core.tariffs as tariffs
from handlers.profile import _edit, _kb, _period_view, _state

logger = logging.getLogger("story_tools")
router = Router()

HIST_MAX = 6
TASHKENT = ZoneInfo("Asia/Tashkent")
PRESET_ROWS = [
    [("⚫ Qora-oq", "bw"), ("🌅 Iliq", "warm"), ("❄️ Sovuq", "cool")],
    [("🎞 Vintage", "vintage"), ("🌈 Yorqin", "vivid"), ("✨ Avto-yaxshi", "auto")],
    [("🔲 To'ldirish", "fill"), ("🌫 Xira fon", "blurbg"), ("◐ Vinyetka", "vignette")],
]


def _opts(st: dict) -> dict:
    return st.setdefault("opts", {"protect": False, "page": True, "links": [], "reactions": []})


def _spec(st: dict) -> dict:
    if st.get("spec") is None:
        st["spec"] = story_edit.default_spec()
    return st["spec"]


def _alive(call_or_msg):
    """(uid, holat) — holat yo'q bo'lsa None."""
    uid = call_or_msg.from_user.id
    return uid, _state(uid)


async def _delete_ui(bot: Bot, st: dict) -> None:
    ui = st.pop("ui", None)
    if ui:
        try:
            await bot.delete_message(*ui)
        except Exception:  # noqa: BLE001 — allaqachon o'chirilgan/eskirgan
            pass


def _files(st: dict) -> list:
    return [st.get("preview"), st.get("edited")]


def _cleanup_edit_files(st: dict) -> None:
    stories.cleanup(*_files(st))
    st["preview"] = st["edited"] = None


# ───────────────────────── 🎨 tahrirlash ─────────────────────────

def _edit_kb() -> InlineKeyboardMarkup:
    rows = [[(label, f"profile:ep:{name}") for label, name in row] for row in PRESET_ROWS]
    rows.append([("✅ Tayyor", "profile:ed:done"), ("↩️ Orqaga", "profile:ed:undo"), ("♻️ Asl holat", "profile:ed:reset")])
    rows.append([("❌ Tahrirni bekor qilish", "profile:ed:back")])
    return _kb(*rows)


def _hint(uid: int) -> str:
    if tariffs.can_caption(uid):
        return ("✍️ Yoki oddiy so'z bilan yozing, AI bajaradi. Masalan:\n"
                "• <i>qora-oq qil, tepaga «Xayrli tong» deb katta yozuv qo'y</i>\n"
                "• <i>yorqinroq va iliqroq qil, atrofiga oq ramka</i>\n"
                "• <i>fonni xiralashtir, pastga mos chiroyli gap yoz</i>\n"
                "• <i>(video) 2 barobar tez, ovozsiz, oxirida fade</i>")
    return "🔒 Erkin so'z bilan AI-tahrir Plus/Pro tarifida. Tayyor tugmalar hamma uchun ochiq."


def _menu_text(uid: int, st: dict, note: str = "") -> str:
    now = story_edit.describe(_spec(st))
    return ("🎨 <b>Tahrirlash</b>\n"
            f"Hozirgi tahrir: {html.escape(now)}\n"
            + (f"\n{html.escape(note)}\n" if note else "") +
            f"\n{_hint(uid)}\n\n<i>Natija joylashdan oldin ko'rsatiladi; «Asl holat» hamma narsani bekor qiladi.</i>")


@router.callback_query(F.data == "profile:edit")
async def edit_open(call: CallbackQuery, bot: Bot):
    uid, st = _alive(call)
    if not st or st["step"] not in ("period", "edit"):
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    st.setdefault("orig_path", st["path"])                 # haqiqiy asl (tahrirsiz) tayyor fayl — birinchi kirishda
    st.setdefault("orig_duration", st["duration"])
    # "Bekor qilish" aynan SHU sessiya boshidagi holatga qaytaradi (oldin yakunlangan tahrirlar yo'qolmaydi)
    st["base"] = {"path": st["path"], "duration": st["duration"],
                  "spec": story_edit.normalize(st["spec"]) if st.get("spec") else None}
    st["spec_hist"] = []
    st["step"] = "edit"
    st["t"] = time.time()
    _spec(st)
    await _edit(call, _menu_text(uid, st), _edit_kb())
    await call.answer()


async def _show_preview(bot: Bot, uid: int, st: dict, chat_id: int, say: str = "") -> bool:
    """Joriy spec bilan ko'rib chiqish kadrini yuboradi (eskisini o'chirib). Muvaffaqiyatli bo'lsa True."""
    path = os.path.join(stories.work_dir(uid), f"preview_{int(time.time() * 1000)}.jpg")
    try:
        await story_edit.render_preview(st["kind"], st["src"], st["spec"], path)
    except stories.StoryError as e:
        stories.cleanup(path)
        await bot.send_message(chat_id, f"❌ Ko'rib chiqishni tayyorlab bo'lmadi: {html.escape(str(e))}")
        return False
    except Exception as e:  # noqa: BLE001
        logger.exception("Story preview xatosi")
        stories.cleanup(path)
        await bot.send_message(chat_id, f"❌ Tahrirni qo'llab bo'lmadi: {html.escape(str(e))[:200]}")
        return False
    await _delete_ui(bot, st)
    stories.cleanup(st.get("preview"))
    st["preview"] = path
    caption = (f"🎨 <b>Ko'rib chiqish</b>\n{html.escape(story_edit.describe(st['spec']))}\n"
               + (f"\n🤖 {html.escape(say)}\n" if say else "") +
               "\nYana o'zgartirish uchun matn yozing yoki tugmalarni bosing; tayyor bo'lsa «✅ Tayyor».")[:1000]
    sent = await bot.send_photo(chat_id, FSInputFile(path), caption=caption, reply_markup=_edit_kb())
    st["ui"] = (chat_id, sent.message_id)
    st["t"] = time.time()
    return True


def _push(st: dict) -> None:
    hist = st.setdefault("spec_hist", [])
    hist.append(story_edit.normalize(_spec(st)))
    del hist[:-HIST_MAX]


@router.callback_query(F.data.startswith("profile:ep:"))
async def edit_preset(call: CallbackQuery, bot: Bot):
    uid, st = _alive(call)
    name = call.data.split(":")[-1]
    if not st or st["step"] != "edit" or name not in story_edit.PRESETS:
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    if st.get("busy"):
        await call.answer("Biroz kuting…")
        return
    st["busy"] = True
    try:
        await call.answer("Qo'llanmoqda…")
        before = story_edit.normalize(_spec(st))
        st["spec"] = story_edit.apply_preset(st["spec"], name)
        if st["spec"] == before:
            await call.answer("Bu allaqachon qo'llangan", show_alert=False)
            return
        hist = st.setdefault("spec_hist", [])
        hist.append(before)
        del hist[:-HIST_MAX]
        if not await _show_preview(bot, uid, st, call.message.chat.id):
            st["spec"] = hist.pop()
    finally:
        st["busy"] = False


def _waiting_edit_text(message: Message) -> bool:
    if message.chat.type != "private" or not message.from_user or not message.text or message.text.startswith("/"):
        return False
    st = _state(message.from_user.id)
    return bool(st and st["step"] == "edit")


@router.message(_waiting_edit_text)
async def edit_text(message: Message, bot: Bot):
    uid = message.from_user.id
    st = _state(uid)
    if not tariffs.can_caption(uid):
        await message.answer("🔒 Erkin so'z bilan AI-tahrir Plus/Pro tarifida. Pastdagi tayyor tugmalardan foydalaning "
                             "yoki tarifni oling.", reply_markup=_kb([(tariffs.PLANS_BUTTON_TEXT, tariffs.PLANS_CALLBACK)]))
        return
    if st.get("busy"):
        await message.answer("⏳ Oldingi tahrir tayyorlanmoqda, biroz kuting…")
        return
    st["busy"] = True
    wait = await message.answer("🤖 So'rovingiz tushunilmoqda…")
    try:
        ctx = " | ".join(x for x in (f"rasmda ko'ringan: {st['media_cache'].get('vision')}" if st.get("media_cache", {}).get("vision") else "",
                                      f"rasmdagi yozuv: {st['media_cache'].get('ocr')}" if st.get("media_cache", {}).get("ocr") else "") if x)
        new, say, status = await story_edit.interpret(bot, uid, message.text, _spec(st), st["kind"], context=ctx[:600])
        reply = {
            story_edit.LIMIT: "⚠️ Kunlik so'rov limitingiz tugagan — AI-tahrir hozir ishlamaydi. Tayyor tugmalar ishlaydi.",
            story_edit.ERROR: "⚠️ AI xizmati hozir javob bermadi. Birozdan keyin qayta yozing yoki tayyor tugmalardan foydalaning.",
            story_edit.FORMAT: "🤔 So'rovni tushunolmadim. Boshqacha, aniqroq yozib ko'ring (masalan: «qora-oq qil va tepaga Salom yoz»).",
            story_edit.NOT_EDIT: f"🙅 {say or 'Buni qila olmayman: men filtr, rang, matn, ramka, kesish va video sozlamalarini o‘zgartira olaman.'}",
            story_edit.NOCHANGE: f"ℹ️ Hech narsa o'zgarmadi. {say}".strip(),
        }.get(status)
        if reply:
            await wait.edit_text(reply)
            return
        before = story_edit.normalize(_spec(st))
        st["spec"] = new
        await wait.delete()
        hist = st.setdefault("spec_hist", [])
        hist.append(before)
        del hist[:-HIST_MAX]
        if not await _show_preview(bot, uid, st, message.chat.id, say):
            st["spec"] = hist.pop()
    finally:
        st["busy"] = False


async def _back_to_period(bot: Bot, uid: int, st: dict, chat_id: int) -> None:
    st["step"] = "period"
    st["t"] = time.time()
    await _delete_ui(bot, st)
    text, kb = _period_view(st)
    await bot.send_message(chat_id, text, reply_markup=kb)


@router.callback_query(F.data == "profile:ed:done")
async def edit_done(call: CallbackQuery, bot: Bot):
    uid, st = _alive(call)
    if not st or st["step"] != "edit":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    if st.get("busy"):
        await call.answer("Biroz kuting…")
        return
    st["busy"] = True
    try:
        spec = _spec(st)
        if story_edit.is_noop(spec, st["kind"]):
            stories.cleanup(st.get("edited"))
            st["edited"], st["spec"] = None, None
            st["path"] = st.get("orig_path", st["path"])                         # oldingi tahrir bo'lgan bo'lsa ham — asl fayl
            st["duration"] = st.get("orig_duration", st["duration"])
            await call.answer("Tahrir yo'q — asl holat")
        elif st["kind"] == "photo":
            if not st.get("preview") or not os.path.exists(st["preview"]):          # ko'rib chiqishsiz bosilgan bo'lsa
                await call.answer("Tayyorlanmoqda…")
                if not await _show_preview(bot, uid, st, call.message.chat.id):
                    return
            if st.get("edited") and st["edited"] != st["preview"]:
                stories.cleanup(st["edited"])                                    # oldingi tahrir fayli diskda qolib ketmasin
            st["edited"], st["preview"] = st["preview"], None                    # ko'rib chiqilgan fayl — aynan o'sha natija
            st["path"] = st["edited"]
            await call.answer("Tayyor ✅")
        else:
            await call.answer("Video tayyorlanmoqda…")
            wait = await bot.send_message(call.message.chat.id, "⏳ Tahrirlangan video tayyorlanmoqda… (bir necha daqiqagacha)")
            out = os.path.join(stories.work_dir(uid), f"edited_{int(time.time())}.mp4")
            try:
                st["duration"] = await story_edit.render_video(st["src"], spec, out)
            except stories.StoryError as e:
                stories.cleanup(out)
                await wait.edit_text(f"❌ {html.escape(str(e))}")
                return
            except Exception as e:  # noqa: BLE001
                logger.exception("Story video render xatosi")
                stories.cleanup(out)
                await wait.edit_text(f"❌ Videoni tayyorlab bo'lmadi: {html.escape(str(e))[:200]}")
                return
            stories.cleanup(st.get("edited"))
            st["edited"] = st["path"] = out
            await wait.delete()
        await _back_to_period(bot, uid, st, call.message.chat.id)
    finally:
        st["busy"] = False


@router.callback_query(F.data == "profile:ed:undo")
async def edit_undo(call: CallbackQuery, bot: Bot):
    uid, st = _alive(call)
    if not st or st["step"] != "edit":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    hist = st.get("spec_hist") or []
    if not hist:
        await call.answer("Orqaga qaytadigan narsa yo'q", show_alert=True)
        return
    if st.get("busy"):
        await call.answer("Biroz kuting…")
        return
    st["busy"] = True
    try:
        await call.answer("Qaytarilmoqda…")
        st["spec"] = hist.pop()
        if story_edit.is_noop(st["spec"], st["kind"]):
            await _delete_ui(call.bot, st)
            await call.bot.send_message(call.message.chat.id, _menu_text(uid, st), reply_markup=_edit_kb())
        else:
            await _show_preview(bot, uid, st, call.message.chat.id)
    finally:
        st["busy"] = False


@router.callback_query(F.data == "profile:ed:reset")
async def edit_reset(call: CallbackQuery, bot: Bot):
    uid, st = _alive(call)
    if not st or st["step"] != "edit":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    if not story_edit.is_noop(_spec(st), st["kind"]):
        _push(st)
    st["spec"] = story_edit.default_spec()
    await call.answer("Asl holat")
    await _delete_ui(bot, st)
    sent = await bot.send_message(call.message.chat.id, _menu_text(uid, st, "Barcha tahrir bekor qilindi."), reply_markup=_edit_kb())
    st["ui"] = (call.message.chat.id, sent.message_id)


@router.callback_query(F.data == "profile:ed:back")
async def edit_back(call: CallbackQuery, bot: Bot):
    """Tahrirni bekor qilib, asl (tahrirsiz) holatga qaytadi."""
    uid, st = _alive(call)
    if not st or st["step"] != "edit":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    base = st.get("base") or {}
    st["path"] = base.get("path", st.get("orig_path", st["path"]))
    st["duration"] = base.get("duration", st["duration"])
    st["spec"], st["spec_hist"] = base.get("spec"), []
    stories.cleanup(st.get("preview"))                                           # yakunlangan tahrir fayli (edited) saqlanadi
    st["preview"] = None
    await call.answer("Tahrir bekor qilindi")
    await _back_to_period(bot, uid, st, call.message.chat.id)


# ───────────────────────── ⚙️ qo'shimcha sozlamalar ─────────────────────────

def _opts_view(st: dict) -> tuple[str, InlineKeyboardMarkup]:
    o = _opts(st)
    links = "\n".join(f"   • {html.escape(u[:60])}" for u in o["links"]) or "   —"
    text = (
        "⚙️ <b>Story sozlamalari</b>\n\n"
        f"🔒 <b>Himoya:</b> {'yoqilgan — storyni saqlash va forward qilish taqiqlanadi' if o['protect'] else 'o‘chiq'}\n"
        f"📌 <b>Profilda saqlash:</b> {'yoqilgan — muddat tugagach ham profilingizda qoladi' if o['page'] else 'o‘chiq — muddat tugagach yo‘qoladi'}\n"
        f"🔗 <b>Havolalar</b> ({len(o['links'])}/{story_areas.MAX_LINKS}):\n{links}\n"
        f"❤️ <b>Reaksiya maydonlari</b> ({len(o['reactions'])}/{story_areas.MAX_REACTIONS}): "
        f"{' '.join(o['reactions']) or '—'}\n\n"
        "<i>Havola va reaksiyalar story ustida bosiladigan maydon bo'lib chiqadi.</i>"
    )
    kb = _kb(
        [(f"🔒 Himoya: {'✅' if o['protect'] else '❌'}", "profile:o:protect")],
        [(f"📌 Profilda saqlash: {'✅' if o['page'] else '❌'}", "profile:o:page")],
        [(f"🔗 Havola qo'shish ({len(o['links'])}/{story_areas.MAX_LINKS})", "profile:o:link"),
         ("❤️ Reaksiyalar", "profile:o:react")],
        [("🧹 Maydonlarni tozalash", "profile:o:clear")],
        [("⬅️ Orqaga", "profile:o:back")],
    )
    return text, kb


@router.callback_query(F.data == "profile:opts")
async def opts_open(call: CallbackQuery):
    uid, st = _alive(call)
    if not st or st["step"] not in ("period", "link"):
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    st["step"] = "period"
    st["t"] = time.time()
    text, kb = _opts_view(st)
    await _edit(call, text, kb)
    await call.answer()


@router.callback_query(F.data.in_({"profile:o:protect", "profile:o:page", "profile:o:clear"}))
async def opts_toggle(call: CallbackQuery):
    uid, st = _alive(call)
    if not st or st["step"] != "period":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    o = _opts(st)
    what = call.data.split(":")[-1]
    if what == "protect":
        o["protect"] = not o["protect"]
    elif what == "page":
        o["page"] = not o["page"]
    else:
        o["links"], o["reactions"] = [], []
    st["t"] = time.time()
    text, kb = _opts_view(st)
    await _edit(call, text, kb)
    await call.answer()


@router.callback_query(F.data == "profile:o:back")
async def opts_back(call: CallbackQuery):
    uid, st = _alive(call)
    if not st or st["step"] not in ("period", "link"):
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    st["step"] = "period"
    st["t"] = time.time()
    text, kb = _period_view(st)
    await _edit(call, text, kb)
    await call.answer()


@router.callback_query(F.data == "profile:o:link")
async def opts_link_ask(call: CallbackQuery):
    uid, st = _alive(call)
    if not st or st["step"] != "period":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    if len(_opts(st)["links"]) >= story_areas.MAX_LINKS:
        await call.answer(f"Eng ko'pi {story_areas.MAX_LINKS} ta havola.", show_alert=True)
        return
    st["step"] = "link"
    st["t"] = time.time()
    await _edit(call, "🔗 Havolani yuboring (masalan <code>https://example.com/sahifa</code> yoki <code>example.com</code>).\n"
                      "Faqat http/https havolalar qabul qilinadi.", _kb([("⬅️ Bekor", "profile:opts")]))
    await call.answer()


def _waiting_link(message: Message) -> bool:
    if message.chat.type != "private" or not message.from_user or not message.text or message.text.startswith("/"):
        return False
    st = _state(message.from_user.id)
    return bool(st and st["step"] == "link")


@router.message(_waiting_link)
async def opts_link_receive(message: Message):
    st = _state(message.from_user.id)
    url = story_areas.clean_url(message.text)
    if not url:
        await message.answer("⚠️ Havola yaroqsiz. To'g'ri havola yuboring (masalan <code>https://example.com</code>) "
                             "yoki «⬅️ Bekor» ni bosing.")
        return
    o = _opts(st)
    if url not in o["links"] and len(o["links"]) < story_areas.MAX_LINKS:
        o["links"].append(url)
    st["step"] = "period"
    st["t"] = time.time()
    text, kb = _opts_view(st)
    await message.answer("✅ Havola qo'shildi.\n\n" + text, reply_markup=kb)


def _react_view(st: dict) -> tuple[str, InlineKeyboardMarkup]:
    chosen = _opts(st)["reactions"]
    rows, row = [], []
    for i, emoji in enumerate(story_areas.REACTIONS):
        row.append((("✅ " if emoji in chosen else "") + emoji, f"profile:o:r:{i}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    rows += [row] if row else []
    rows.append([("⬅️ Orqaga", "profile:opts")])
    return (f"❤️ Story'ga qo'shiladigan reaksiya maydonlari (eng ko'pi {story_areas.MAX_REACTIONS} ta). "
            "Tomoshabinlar ularni bosib tezda javob bera oladi.", _kb(*rows))


@router.callback_query(F.data == "profile:o:react")
async def react_open(call: CallbackQuery):
    uid, st = _alive(call)
    if not st or st["step"] != "period":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    text, kb = _react_view(st)
    await _edit(call, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("profile:o:r:"))
async def react_toggle(call: CallbackQuery):
    uid, st = _alive(call)
    if not st or st["step"] != "period":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    try:
        emoji = story_areas.REACTIONS[int(call.data.split(":")[-1])]
    except (ValueError, IndexError):
        await call.answer()
        return
    chosen = _opts(st)["reactions"]
    if emoji in chosen:
        chosen.remove(emoji)
    elif len(chosen) >= story_areas.MAX_REACTIONS:
        await call.answer(f"Eng ko'pi {story_areas.MAX_REACTIONS} ta.", show_alert=True)
        return
    else:
        chosen.append(emoji)
    st["t"] = time.time()
    text, kb = _react_view(st)
    await _edit(call, text, kb)
    await call.answer()


# ───────────────────────── 🗂 story'larim ─────────────────────────

@router.callback_query(F.data == "profile:mine")
async def my_stories(call: CallbackQuery):
    uid = call.from_user.id
    if not roles.can_use_bot(uid):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    posts = stories.list_posts(uid)
    back = [("🔙 Profil boshqaruvi", "profile:menu")]
    if not posts:
        await _edit(call, "🗂 <b>Story'larim</b>\n\nBot orqali qo'yilgan faol (muddati tugamagan) story yo'q.", _kb(back))
        await call.answer()
        return
    lines, rows = [], []
    for i, p in enumerate(posts[:10], 1):
        when = datetime.fromtimestamp(p["t"], TASHKENT).strftime("%d.%m %H:%M")
        left = max(0, int((p["t"] + p["h"] * 3600 - time.time()) // 3600))
        icon = "📷" if p["k"] == "photo" else "🎬"
        cap = f" «{html.escape(p['c'])}»" if p.get("c") else ""
        lines.append(f"{i}. {icon} {when} · yana ~{left} soat{cap}")
        rows.append([(f"🗑 {i}-ni o'chirish", f"profile:del:{p['id']}")])
    rows.append(back)
    await _edit(call, "🗂 <b>Story'larim</b> (bot orqali qo'yilgan, faol)\n\n" + "\n".join(lines), _kb(*rows))
    await call.answer()
