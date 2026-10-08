"""
core/note_forget.py
-------------------
"UNUT" — xotirani HAQIQATAN o'chirish (avval bot "unutishim kerak" deb YANGI eslatma yozib qo'yardi, o'chirish tool'i yo'q edi).

Nima o'chadi (faqat SHU foydalanuvchining o'zi haqidagi narsalar):
  * shaxsiy chat: doimiy eslatmalari + barcha mavzulardagi suhbat tarixidan mos xabarlar + eski xulosadagi mos gaplar;
  * guruh: shu guruhdagi eslatmalari + guruh logidagi O'ZINING mos xabarlari (boshqalarning xabarlari, bot javoblari va
    umumiy guruh xulosasiga TEGILMAYDI — ular boshqa odamlarga ham tegishli).
Moslik: so'rovdagi mazmunli so'zlarning kamida yarmi matnda uchrasa (o'zbekcha qo'shimchalarga chidamli: "maktab" ~ "maktabda").
Aniq bo'lmagan so'rov hech narsani o'chirmaydi; hech narsa topilmasa mavjud eslatmalar ro'yxati qaytariladi (AI aniqlashtirsin).
"""
from __future__ import annotations

import re
from typing import Optional

_APOS = "’ʻʼ`‘"
_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)
_STOP = {"va", "bilan", "uchun", "haqida", "bu", "shu", "ham", "deb", "degan", "men", "meni", "mening", "sen", "seni",
         "siz", "sizni", "unut", "unutish", "unutgin", "esdan", "chiqar", "chiqarib", "tashla", "o'chir", "o'chirib",
         "bekor", "qil", "qilish", "qilmoqchi", "qilmoqchiman", "aytgandim", "aytgan", "falon", "ishni", "narsani",
         "ya'ni", "endi", "kerak", "emas", "eslatma", "xotira", "xotiradan", "buni", "shuni", "uni", "bularni",
         "shularni", "o'sha", "osha", "narsa", "gapni", "gap"}
MAX_SHOWN = 10


def _norm(text: str) -> str:
    t = (text or "").lower()
    for ch in _APOS:
        t = t.replace(ch, "'")
    return t


def words(text: str) -> list[str]:
    return _WORD_RE.findall(_norm(text))


def _same(a: str, b: str) -> bool:
    n = min(len(a), len(b), 5)
    return a == b if n < 4 else a[:n] == b[:n]


def query_tokens(query: str) -> list[str]:
    seen, out = set(), []
    for w in words(query):
        if len(w) >= 3 and w not in _STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def matches(tokens: list[str], text: str) -> bool:
    """So'rov tokenlarining YARMIDAN KO'PI matnda uchraydimi (1 ta -> 1; 2 ta -> 2; 3 ta -> 2; 4 ta -> 3).
    Qaytarib bo'lmaydigan amal: 'maktab sayti' so'rovi faqat 'maktab' so'zi bor BOSHQA eslatmani (masalan 'maktab kitoblari')
    o'chirib yubormasligi kerak; ortiqcha qattiq bo'lsa — 'topilmadi' + ro'yxat qaytadi va AI aniqlashtiradi."""
    if not tokens:
        return False
    ws = words(text)
    hit = sum(1 for q in tokens if any(_same(q, w) for w in ws))
    return hit * 2 > len(tokens)


def looks_like_forget_request(note: str) -> bool:
    """remember_note'ga kelgan matn aslida 'unut' iltimosimi (xatolikni ushlash uchun)."""
    n = _norm(note)
    return bool(re.search(r"unut|esdan chiqar|xotira\w*\s+(?:dan\s+)?o'chir", n))


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def scrub_summary(summary: str, tokens: list[str]) -> tuple[str, int]:
    """Xulosadan mos gaplarni olib tashlaydi -> (yangi_xulosa, o'chirilgan_gaplar_soni)."""
    if not summary or not tokens:
        return summary, 0
    sents = _sentences(summary)
    kept = [s for s in sents if not matches(tokens, s)]
    return " ".join(kept), len(sents) - len(kept)


def _short(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


async def forget(bot, user_id: int, chat_id: Optional[int], query: str = "", all_notes: bool = False) -> dict:
    """AI tool'i (forget_note) uchun. chat_id — guruh (None — shaxsiy chat). user_id — SERVER bergan (xabar egasi)."""
    import core.tgdb as tgdb
    db = tgdb.get()

    if chat_id is not None:
        notes = db.setdefault("group_notes", {}).setdefault(str(chat_id), {}).setdefault(str(user_id), [])
    else:
        notes = db["users"].setdefault(str(user_id), {}).setdefault("notes", [])

    tokens = query_tokens(query)
    if not all_notes and not tokens:
        return {"error": "Nimani unutish kerakligi aniq emas: query'ga o'sha narsaning kalit so'zlarini yozing "
                         "(masalan 'maktab sayti'), yoki hammasini unutish so'ralsa all=true bering.",
                "mavjud_eslatmalar": [_short(n) for n in notes[:MAX_SHOWN]]}

    removed_notes: list[str] = []
    if all_notes:
        removed_notes, notes[:] = list(notes), []
    else:
        kept = [n for n in notes if not matches(tokens, n)]
        removed_notes = [n for n in notes if matches(tokens, n)]
        notes[:] = kept

    removed_msgs = removed_sents = 0
    if tokens and not all_notes:            # "hammasini unut" — faqat eslatmalar (butun suhbatni o'chirish boshqa buyruq)
        if chat_id is None:
            for session in db.get("topics", {}).get(str(user_id), {}).values():
                before = len(session.get("history", []))
                session["history"] = [m for m in session.get("history", []) if not matches(tokens, m.get("content", ""))]
                removed_msgs += before - len(session["history"])
                session["summary"], n = scrub_summary(session.get("summary", ""), tokens)
                removed_sents += n
        else:
            import core.group_wipe as group_wipe
            for key in group_wipe._group_mem_keys(chat_id):
                log = db["group_mem"][key].get("log", [])
                keep = [e for e in log if not (e.get("r") == "u" and e.get("i") == user_id and matches(tokens, e.get("t", "")))]
                removed_msgs += len(log) - len(keep)
                db["group_mem"][key]["log"] = keep

    if not (removed_notes or removed_msgs or removed_sents):
        return {"status": "topilmadi", "mavjud_eslatmalar": [_short(n) for n in notes[:MAX_SHOWN]],
                "eslatma": "Mos eslatma yoki suhbat izi topilmadi. Mavjud eslatmalarni ko'rib, kerak bo'lsa foydalanuvchidan "
                           "aniqlashtiring yoki boshqa kalit so'z bilan qayta urinib ko'ring. Yangi eslatma YOZMANG."}

    await tgdb.save(bot, force=True)
    return {"status": "o'chirildi", "o'chirilgan_eslatmalar": [_short(n) for n in removed_notes[:MAX_SHOWN]],
            "o'chirilgan_eslatmalar_soni": len(removed_notes), "suhbatdan_o'chirilgan_xabarlar": removed_msgs,
            "xulosadan_o'chirilgan_gaplar": removed_sents,
            "eslatma": "Foydalanuvchiga nima o'chirilganini qisqa ayting va bu mavzuni endi o'zingiz tilga olmang."}
