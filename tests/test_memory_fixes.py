"""Xotira tuzatishlari: (1) UNUTISH haqiqatan o'chiradi (forget_note); (2) guruhda odamlar/laqablar aralashib ketmaydi."""
import asyncio
from types import SimpleNamespace

import pytest

import core.ai_persona as ai_persona
import core.ai_tools as ai_tools
import core.group_memory as gm
import core.history_summarizer as hs
import core.note_forget as nf
import core.tgdb as tgdb
import core.user_profile as user_profile

U, V, CHAT, OTHER_CHAT = 101, 102, -1001, -1002


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(monkeypatch):
    d = {"users": {}, "topics": {}, "group_notes": {}, "group_mem": {}, "nicknames": {}, "auto_nicknames": {}}
    monkeypatch.setattr(tgdb, "_cache", d)
    saves = []

    async def save(bot, force=False):
        saves.append(force)

    monkeypatch.setattr(tgdb, "save", save)
    d["_saves"] = saves
    return d


# ── moslashtirish ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("query,text,expected", [
    ("maktab sayti", "Men maktab haqida HTML sayt yasamoqchiman", True),     # qo'shimchalar: sayti ~ sayt
    ("maktab", "Maktabda dars bor", True),                                    # maktab ~ maktabda
    ("maktab sayti", "Mening itim bor", False),
    ("MAKTAB", "maktab", True),                                               # katta/kichik harf
    ("o‘zbek tili", "o'zbek tili kursi", True),                               # turli apostrof belgilari
    ("maktab sayt kitob", "Maktab sayt qilmoqchiman", True),                  # 3 tadan 2 tasi (yarmidan ko'pi) mos
    ("maktab sayt kitob", "Maktab haqida gap", False),                        # 3 tadan 1 tasi — yetarli emas
    ("maktab sayti", "Maktab kitoblarini sotadi", False),                     # 2 tadan 1 tasi — boshqa eslatma, O'CHMASIN
    ("maktab sayti", "Maktab saytini yasamoqchi", True),
    ("maktab", "Maktab kitoblarini sotadi", True),                            # bitta so'rov so'zi — shu so'z yetarli
    ("unut buni", "unut", False),                                             # faqat to'xtatuv so'zlar — mazmun yo'q
    ("", "salom", False),
])
def test_matching(query, text, expected):
    assert nf.matches(nf.query_tokens(query), text) is expected


@pytest.mark.parametrize("note,expected", [
    ("Foydalanuvchi maktab sayti haqida gapirgan, uni unutishim kerak", True),
    ("Maktab sayti ishini UNUT", True),
    ("esdan chiqar buni", True),
    ("xotiradan o'chir maktab", True),
    ("Foydalanuvchi qisqa javoblarni yoqtiradi", False),
    ("Har doim o'zbek tilida javob ber", False),
])
def test_forget_request_detector(note, expected):
    assert nf.looks_like_forget_request(note) is expected


def test_scrub_summary_drops_only_matching_sentences():
    s = "Foydalanuvchi maktab sayti yasamoqchi edi. U ob-havo haqida so'radi. Yana kitob tavsiya so'ragan."
    new, n = nf.scrub_summary(s, nf.query_tokens("maktab sayti"))
    assert n == 1 and "maktab" not in new and "ob-havo" in new and "kitob" in new


# ── forget: shaxsiy chat ───────────────────────────────────────────────────────
def private_setup(db):
    db["users"][str(U)] = {"notes": ["Maktab sayti HTML yasamoqchi", "Qisqa javoblarni yoqtiradi", "Maktab kitoblarini sotadi"]}
    db["users"][str(V)] = {"notes": ["Maktab sayti ustida ishlaydi"]}                       # BOSHQA odam — tegilmaydi
    db["topics"][str(U)] = {
        "general": {"history": [{"role": "user", "content": "Maktab sayti HTML yasab ber"},
                                {"role": "assistant", "content": "Mayli, maktab sayti uchun HTML tayyorlayman"},
                                {"role": "user", "content": "Ob-havo qanday?"}],
                    "summary": "U maktab sayti yasamoqchi edi. Keyin ob-havoni so'radi."},
        "55": {"history": [{"role": "user", "content": "Maktab saytining dizayni"}], "summary": ""}}
    db["topics"][str(V)] = {"general": {"history": [{"role": "user", "content": "Maktab sayti"}], "summary": "Maktab sayti."}}


def test_forget_deletes_notes_history_and_summary_for_that_user_only(db):
    private_setup(db)
    r = run(nf.forget(None, U, None, query="maktab sayti"))
    assert r["status"] == "o'chirildi" and r["o'chirilgan_eslatmalar_soni"] == 1
    assert db["users"][str(U)]["notes"] == ["Qisqa javoblarni yoqtiradi", "Maktab kitoblarini sotadi"]   # "kitoblarini" mos EMAS
    gen = db["topics"][str(U)]["general"]
    assert [m["content"] for m in gen["history"]] == ["Ob-havo qanday?"]                    # user + assistant izlari ketdi
    assert "maktab" not in gen["summary"].lower() and "ob-havo" in gen["summary"]
    assert db["topics"][str(U)]["55"]["history"] == []                                      # boshqa mavzulardan ham
    assert r["suhbatdan_o'chirilgan_xabarlar"] == 3 and r["xulosadan_o'chirilgan_gaplar"] == 1
    assert db["users"][str(V)]["notes"] == ["Maktab sayti ustida ishlaydi"]                 # boshqa odam tegilmagan
    assert db["topics"][str(V)]["general"]["history"] and db["topics"][str(V)]["general"]["summary"] == "Maktab sayti."
    assert db["_saves"] == [True]                                                           # darhol saqlandi


def test_forget_nothing_found_changes_nothing_and_lists_notes(db):
    private_setup(db)
    before = {k: list(v["notes"]) for k, v in db["users"].items()}
    r = run(nf.forget(None, U, None, query="velosiped"))
    assert r["status"] == "topilmadi" and "Maktab sayti HTML yasamoqchi" in r["mavjud_eslatmalar"]
    assert {k: list(v["notes"]) for k, v in db["users"].items()} == before and db["_saves"] == []


def test_forget_vague_query_deletes_nothing(db):
    private_setup(db)
    r = run(nf.forget(None, U, None, query="unut buni"))
    assert "error" in r and len(db["users"][str(U)]["notes"]) == 3 and db["_saves"] == []


def test_forget_all_ignores_query_and_never_touches_conversation(db):
    private_setup(db)
    r = run(nf.forget(None, U, None, query="maktab sayti", all_notes=True))                  # all=true: query e'tiborga olinmaydi
    assert r["o'chirilgan_eslatmalar_soni"] == 3 and r["suhbatdan_o'chirilgan_xabarlar"] == 0
    assert len(db["topics"][str(U)]["general"]["history"]) == 3 and "maktab" in db["topics"][str(U)]["general"]["summary"].lower()


def test_forget_all_clears_only_notes_in_scope(db):
    private_setup(db)
    db["group_notes"] = {str(CHAT): {str(U): ["Guruh eslatmasi"]}}
    r = run(nf.forget(None, U, None, all_notes=True))
    assert r["o'chirilgan_eslatmalar_soni"] == 3 and db["users"][str(U)]["notes"] == []
    assert db["topics"][str(U)]["general"]["history"]                                       # suhbat tarixiga tegilmaydi
    assert db["group_notes"][str(CHAT)][str(U)] == ["Guruh eslatmasi"]                      # guruh eslatmalari alohida


# ── forget: guruh ──────────────────────────────────────────────────────────────
def group_setup(db):
    db["group_notes"] = {str(CHAT): {str(U): ["Maktab sayti kerak"], str(V): ["Maktab sayti kerak"]},
                         str(OTHER_CHAT): {str(U): ["Maktab sayti kerak"]}}
    db["users"][str(U)] = {"notes": ["Maktab sayti (shaxsiy chat)"]}
    mem = gm._mem(CHAT, None)
    mem["summary"] = "U maktab sayti haqida gapirdi."
    mem["log"] = [
        {"r": "u", "n": "Ali", "u": "ali", "i": U, "t": "maktab sayti yasab beringlar", "m": 1},
        {"r": "u", "n": "Vali", "u": "vali", "i": V, "t": "men ham maktab sayti xohlayman", "m": 2},
        {"r": "a", "t": "Maktab sayti uchun HTML tayyor"},
        {"r": "u", "n": "Ali", "u": "ali", "i": U, "t": "ob-havo qanday?", "m": 3}]
    gm._mem(OTHER_CHAT, None)["log"] = [{"r": "u", "n": "Ali", "u": "ali", "i": U, "t": "maktab sayti", "m": 9}]


def test_group_forget_touches_only_own_notes_and_own_lines_in_this_group(db):
    group_setup(db)
    r = run(nf.forget(None, U, CHAT, query="maktab sayti"))
    assert r["o'chirilgan_eslatmalar_soni"] == 1 and db["group_notes"][str(CHAT)][str(U)] == []
    log = db["group_mem"][gm._key(CHAT, None)]["log"]
    assert [e["m"] for e in log if "m" in e] == [2, 3]                                       # faqat Ali'ning mos xabari ketdi
    assert any(e["r"] == "a" for e in log)                                                   # bot javobi tegilmagan
    assert db["group_mem"][gm._key(CHAT, None)]["summary"] == "U maktab sayti haqida gapirdi."   # umumiy xulosa tegilmagan
    assert db["group_notes"][str(CHAT)][str(V)] == ["Maktab sayti kerak"]                    # Vali tegilmagan
    assert db["group_notes"][str(OTHER_CHAT)][str(U)] == ["Maktab sayti kerak"]              # boshqa guruh tegilmagan
    assert db["group_mem"][gm._key(OTHER_CHAT, None)]["log"]                                 # boshqa guruh logi tegilmagan
    assert db["users"][str(U)]["notes"] == ["Maktab sayti (shaxsiy chat)"]                   # shaxsiy eslatma tegilmagan


# ── AI tool: ulanish va qo'riqchi ──────────────────────────────────────────────
class Bot:
    pass


def ctx(group=False):
    return {"bot": Bot(), "chat_id": CHAT, "is_group": group}


def test_tool_registered_with_label_and_clear_description():
    names = [t["function"]["name"] for t in ai_tools.TOOLS]
    assert "forget_note" in names and "forget_note" in ai_tools.DISPATCH and "forget_note" in ai_tools._TOOL_STATUS_LABELS
    desc = {t["function"]["name"]: t["function"]["description"] for t in ai_tools.TOOLS}
    assert "meni ... deb chaqir" not in desc["remember_note"] and "forget_note" in desc["remember_note"]
    assert "HAQIQATAN" in desc["forget_note"]


def test_tool_uses_server_user_id_not_arguments(db):
    private_setup(db)
    run(ai_tools.dispatch("forget_note", U, {"query": "maktab sayti", "user_id": V}, ctx()))     # AI boshqa ID bersa ham
    assert db["users"][str(V)]["notes"] == ["Maktab sayti ustida ishlaydi"]
    assert db["users"][str(U)]["notes"] == ["Qisqa javoblarni yoqtiradi", "Maktab kitoblarini sotadi"]


def test_tool_in_group_scope(db):
    group_setup(db)
    run(ai_tools.dispatch("forget_note", U, {"query": "maktab sayti"}, ctx(group=True)))
    assert db["group_notes"][str(CHAT)][str(U)] == [] and db["users"][str(U)]["notes"] == ["Maktab sayti (shaxsiy chat)"]


def test_remember_note_refuses_to_store_a_forget_request(db):
    """AYNAN shu xato edi: 'unut' -> 'unutishim kerak' deb yangi eslatma yozilardi."""
    db["users"][str(U)] = {"notes": ["Maktab sayti yasamoqchi"]}
    r = run(ai_tools.dispatch("remember_note", U, {"note": "Foydalanuvchi maktab saytini unutishimni so'radi, unutishim kerak"}, ctx()))
    assert "forget_note" in r["error"] and db["users"][str(U)]["notes"] == ["Maktab sayti yasamoqchi"] and db["_saves"] == []
    ok = run(ai_tools.dispatch("remember_note", U, {"note": "Qisqa javoblarni yoqtiradi"}, ctx()))
    assert ok["status"] == "saqlandi" and len(db["users"][str(U)]["notes"]) == 2


# ── guruh: xulosalovchi muallifni saqlaydi ─────────────────────────────────────
class FakeAI:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools=None, user_id=None):
        self.calls.append(messages)
        msg = SimpleNamespace(content="xulosa")
        return {"response": SimpleNamespace(choices=[SimpleNamespace(message=msg)])}


def test_group_summarizer_keeps_attribution(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(hs, "ai", fake)
    msgs = [{"role": "user", "content": "Aka (@user101): meni Aka deb chaqir\nOpa (@user102): meni opa deb chaqir"},
            {"role": "assistant", "content": "Mayli"}]
    assert run(hs.summarize("", msgs, group=True)) == "xulosa"
    system, user = fake.calls[0][0]["content"], fake.calls[0][1]["content"]
    assert "GURUH" in system and "HECH QACHON birlashtirmang" in system and "laqab" in system.lower()
    assert "Aka (@user101): meni Aka deb chaqir" in user and "Opa (@user102): meni opa deb chaqir" in user
    assert "Foydalanuvchi:" not in user and "AI: Mayli" in user                    # odam qatorlari 'Foydalanuvchi:' bilan buzilmaydi


def test_private_summarizer_unchanged(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(hs, "ai", fake)
    run(hs.summarize("", [{"role": "user", "content": "salom"}, {"role": "assistant", "content": "ha"}]))
    assert fake.calls[0][0]["content"] == hs._SUMMARIZE_SYSTEM_PROMPT and "Foydalanuvchi: salom" in fake.calls[0][1]["content"]


def test_group_log_folding_uses_group_mode(db, monkeypatch):
    seen = {}

    async def fake_summarize(old, msgs, group=False):
        seen["group"] = group
        return "x"

    monkeypatch.setattr(hs, "summarize", fake_summarize)
    mem = gm._mem(CHAT, None)
    mem["log"] = [{"r": "u", "n": "Ali", "u": "ali", "i": U, "t": f"xabar {i}", "m": i} for i in range(gm.MAX_LOG + gm.FOLD_BATCH + 5)]
    run(gm.maybe_fold(Bot(), CHAT, None))
    assert seen == {"group": True}


# ── guruh: kim kim ─────────────────────────────────────────────────────────────
def test_roster_keeps_people_separate_with_their_own_nicknames(db):
    db["nicknames"] = {str(U): "Aka"}
    db["auto_nicknames"] = {str(V): {"n": "Opa"}}
    gm._mem(CHAT, None)["log"] = [
        {"r": "u", "n": "Ali Valiyev", "u": "user101", "i": U, "t": "meni Aka deb chaqir", "m": 1},
        {"r": "u", "n": "Gulnora", "u": "user102", "i": V, "t": "meni opa deb chaqir", "m": 2},
        {"r": "a", "t": "Mayli"},
        {"r": "u", "n": "Ali Valiyev", "u": "user101", "i": U, "t": "maktab haqida HTML yasab ber", "m": 3},
        {"r": "u", "n": "Gulnora", "u": "user102", "i": V, "t": "men ham", "m": 4}]
    people = gm.roster(CHAT, None)
    assert people == ["Opa (@user102) [haqiqiy ismi: Gulnora]", "Aka (@user101) [haqiqiy ismi: Ali Valiyev]"]   # eng YANGI yozgan birinchi
    block = gm.roster_block(CHAT, None)
    assert "ALOHIDA odam" in block and "Aka opa" in block and "birlashtirmang" in block
    assert all(p in block for p in people)


def test_roster_limit_and_empty(db):
    assert gm.roster_block(CHAT, None) == ""
    gm._mem(CHAT, None)["log"] = [{"r": "u", "n": f"N{i}", "u": f"u{i}", "i": 1000 + i, "t": "x", "m": i} for i in range(20)]
    assert len(gm.roster(CHAT, None, limit=8)) == 8


class Msg:
    def __init__(self, uid, username="user101", first="Ali", last="Valiyev"):
        self.from_user = SimpleNamespace(id=uid, username=username, first_name=first, last_name=last)


class NoBioBot:
    async def get_chat(self, uid):
        raise RuntimeError("yo'q")


def test_speaker_line_includes_the_speakers_own_nickname_only(db):
    db["nicknames"] = {str(U): "Aka"}
    line = run(user_profile.basic_info_line(NoBioBot(), Msg(U)))
    assert "FAQAT shunday chaqiring" in line and "«Aka»" in line and "ID=101" in line
    assert "Aka" not in run(user_profile.basic_info_line(NoBioBot(), Msg(V, "user102", "Gulnora", "")))   # boshqa odamga berilmaydi
    plain = run(user_profile.basic_info_line(NoBioBot(), Msg(V, "user102", "Gulnora", "")))
    assert "chaqirishni so'ragan" not in plain


# ── ulanish ────────────────────────────────────────────────────────────────────
def test_ai_chat_wires_roster_and_attribution_rule():
    src = open("handlers/ai_chat.py", encoding="utf-8").read()
    assert "group_memory.roster_block(message.chat.id, group_mem_thread)" in src
    assert "ALOHIDA odamniki" in src


def test_persona_no_longer_routes_nicknames_to_remember_and_mentions_forgetting():
    p = ai_persona.CAPABILITIES_BLOCK
    assert "masalan ismi/laqabi" not in p and "HAQIQATAN o'chirasiz" in p
