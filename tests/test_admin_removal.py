"""Panel: adminlar inline ro'yxati va 2 bosqichli o'chirish — haqiqiy Dispatcher orqali."""
import asyncio
from types import SimpleNamespace

import pytest

import admin.panel as panel
import core.bot_identity as bot_identity
import core.moderation as moderation
import core.roles as roles
import core.tgdb as tgdb
import harness
import main

SUPER, A1, A2, USER = 1, 6484249357, 5302627260, 9
_n = [100]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(tgdb, "_cache", {"users": {}, "admins": {str(A1): {"name": None}, str(A2): {"name": "Ummu Zaynab"}}})
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)

    async def nosave(bot, force=False):
        return None

    monkeypatch.setattr(tgdb, "save", nosave)
    bot_identity.set_username(harness.BOT_USERNAME)
    bot_identity.set_id(harness.BOT_ID)
    panel._admin_del.clear()
    moderation._access_cache.clear()


def press(bot, uid, data):
    _n[0] += 1
    cq_update = harness.press_callback(main.dp, bot, uid, data, update_id=_n[0])
    run(cq_update)


def last_edit(bot):
    edits = [d for n, d in bot.session.calls if n == "EditMessageText"]
    return edits[-1]


def kb_of(call_data):
    kb = call_data["reply_markup"]
    rows = kb["inline_keyboard"] if isinstance(kb, dict) else kb.inline_keyboard
    return [(b["text"], b["callback_data"]) if isinstance(b, dict) else (b.text, b.callback_data) for row in rows for b in row]


def alerts(bot):
    return [d.get("text") for n, d in bot.session.calls if n == "AnswerCallbackQuery"]


def admin_ids():
    return set(roles.list_admins())


# ── ro'yxat ──────────────────────────────────────────────────────────────

def test_list_shows_every_admin_as_inline_button_with_name_or_id():
    bot = harness.make_bot()
    press(bot, SUPER, "panel:admins:0")
    buttons = kb_of(last_edit(bot))
    admin_buttons = [b for b in buttons if b[1].startswith("panel:adm:")]
    assert {b[1] for b in admin_buttons} == {f"panel:adm:{A1}", f"panel:adm:{A2}"}
    texts = " ".join(t for t, _ in admin_buttons)
    assert "Ummu Zaynab" in texts and str(A1) in texts                       # ismi bor bo'lsa — ism, bo'lmasa — ID
    assert ("➕ Admin qo'shish", "panel:add_admin") in buttons and ("🔙 Menyu", "panel:main") in buttons


def test_missing_names_are_fetched_from_telegram_and_remembered(monkeypatch):
    bot = harness.make_bot()

    async def fake_get_chat(chat_id):
        return SimpleNamespace(full_name="Aziz Karimov", first_name="Aziz", username="aziz_k")

    monkeypatch.setattr(bot, "get_chat", fake_get_chat)
    press(bot, SUPER, "panel:admins:0")
    assert any("Aziz Karimov (@aziz_k)" in t for t, _ in kb_of(last_edit(bot)))
    assert roles.list_admins()[str(A1)]["name"] == "Aziz Karimov (@aziz_k)"


def test_empty_list_message():
    tgdb.get()["admins"] = {}
    bot = harness.make_bot()
    press(bot, SUPER, "panel:admins:0")
    assert "Hozircha admin yo'q" in last_edit(bot)["text"]


# ── ikki bosqichli o'chirish ─────────────────────────────────────────────

def test_full_flow_needs_two_confirmations_then_removes_only_that_admin():
    bot = harness.make_bot()
    press(bot, SUPER, f"panel:adm:{A1}")                                     # 1: admin ustiga bosildi — "o'chirasizmi?"
    q1 = last_edit(bot)
    assert "olib tashlaysizmi" in q1["text"] and str(A1) in q1["text"] and admin_ids() == {str(A1), str(A2)}
    assert (f"panel:admdel1:{A1}") in [d for _, d in kb_of(q1)]
    press(bot, SUPER, f"panel:admdel1:{A1}")                                 # 2: "Ha, davom etish" — oxirgi tasdiq
    q2 = last_edit(bot)
    assert "OXIRGI TASDIQ" in q2["text"] and admin_ids() == {str(A1), str(A2)}  # hali o'chirilmagan
    press(bot, SUPER, f"panel:admdel2:{A1}")                                 # 3: "Ha, o'chirish"
    assert admin_ids() == {str(A2)}                                          # faqat tanlangani o'chdi
    assert "✅ Admin o'chirildi" in alerts(bot)
    after = last_edit(bot)
    assert [b[1] for b in kb_of(after) if b[1].startswith("panel:adm:")] == [f"panel:adm:{A2}"]   # ro'yxat yangilandi
    deletes = [d for n, d in bot.session.calls if n == "DeleteMyCommands"]
    assert deletes and deletes[0]["scope"]["chat_id"] == A1                  # shaxsiy '/' menyusidan /panel olib tashlandi


def test_cannot_skip_the_first_confirmation_or_replay_old_buttons():
    bot = harness.make_bot()
    press(bot, SUPER, f"panel:admdel2:{A1}")                                 # to'g'ridan-to'g'ri oxirgi tugma (bosqichlarsiz)
    assert admin_ids() == {str(A1), str(A2)} and any("muddati tugagan" in (t or "") for t in alerts(bot))
    press(bot, SUPER, f"panel:admdel1:{A1}")                                 # 1-bosqichsiz 2-bosqich
    assert admin_ids() == {str(A1), str(A2)}
    press(bot, SUPER, f"panel:adm:{A1}")
    press(bot, SUPER, f"panel:admdel2:{A1}")                                 # 1-tasdiqdan keyin 2-tasdiqsiz sakrash
    assert admin_ids() == {str(A1), str(A2)}


def test_confirmation_is_for_one_specific_admin_only():
    bot = harness.make_bot()
    press(bot, SUPER, f"panel:adm:{A1}")
    press(bot, SUPER, f"panel:admdel1:{A1}")
    press(bot, SUPER, f"panel:admdel2:{A2}")                                 # A1 uchun tasdiqlangan, A2 ni o'chirishga urinish
    assert admin_ids() == {str(A1), str(A2)}


def test_confirmation_expires():
    bot = harness.make_bot()
    press(bot, SUPER, f"panel:adm:{A1}")
    press(bot, SUPER, f"panel:admdel1:{A1}")
    panel._admin_del[SUPER]["t"] -= panel.ADMIN_DEL_TTL + 5
    press(bot, SUPER, f"panel:admdel2:{A1}")
    assert admin_ids() == {str(A1), str(A2)}


def test_second_press_of_final_button_does_nothing_more():
    bot = harness.make_bot()
    for step in ("adm", "admdel1", "admdel2"):
        press(bot, SUPER, f"panel:{step}:{A1}")
    assert admin_ids() == {str(A2)}
    press(bot, SUPER, f"panel:admdel2:{A1}")                                 # qayta bosish
    assert admin_ids() == {str(A2)} and len([1 for n, _ in bot.session.calls if n == "DeleteMyCommands"]) == 1


def test_no_button_cancel_paths_keep_admin():
    bot = harness.make_bot()
    press(bot, SUPER, f"panel:adm:{A1}")
    press(bot, SUPER, "panel:admins:0")                                      # "Yo'q, qoldirish"
    assert admin_ids() == {str(A1), str(A2)} and SUPER not in panel._admin_del
    press(bot, SUPER, f"panel:admdel2:{A1}")                                 # bekor qilingandan keyin eski tugma ishlamaydi
    assert admin_ids() == {str(A1), str(A2)}


# ── ruxsat ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", [A1, A2, USER])
def test_only_superadmin_can_open_or_remove_admins(who):
    bot = harness.make_bot()
    panel._admin_del[who] = {"uid": str(A1), "step": 2, "t": __import__("time").time()}   # hatto holat soxtalashtirilsa ham
    for data in ("panel:admins:0", f"panel:adm:{A1}", f"panel:admdel1:{A1}", f"panel:admdel2:{A1}"):
        press(bot, who, data)
    assert admin_ids() == {str(A1), str(A2)}
    assert all(a == "Ruxsat yo'q" for a in alerts(bot) if a)


def test_removed_admin_loses_powers_and_cached_access_is_cleared():
    moderation._access_cache[(-1001, A1)] = (1e12, "eski admin huquqi")
    moderation._access_cache[(-1001, A2)] = (1e12, "boshqa admin")
    assert roles.is_admin(A1)
    assert run(roles.remove_admin(None, A1)) is True
    assert not roles.is_admin(A1) and roles.is_admin(A2)
    assert (-1001, A1) not in moderation._access_cache and (-1001, A2) in moderation._access_cache
    assert run(roles.remove_admin(None, A1)) is False                        # allaqachon yo'q


def test_removed_admin_cannot_open_panel_anymore():
    bot = harness.make_bot()
    for step in ("adm", "admdel1", "admdel2"):
        press(bot, SUPER, f"panel:{step}:{A1}")
    bot2 = harness.make_bot()
    run(main.dp.feed_update(bot2, harness.message_update(7, A1, A1, "/panel", chat_type="private")))
    assert bot2.session.texts(A1) == []                                      # /panel endi jim (admin emas)
