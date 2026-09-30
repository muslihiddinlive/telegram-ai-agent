"""
Asosiy AI-suhbat handler — agentic tool-use loop, ms-file-toolkit/example.py
patternidan (u yerda Claude API bilan qilingan edi, bu yerda umumiy
MultiProviderAI orqali amalga oshirilgan).

Qo'shimcha funksiyalar:
  - Shaxsiy chat Topics (Bot API 9.4, 2026-02-09): har bir topic — core/topic_sessions.py
    orqali MUSTAQIL suhbat tarixi/konteksti bilan ishlaydi (bitta umumiy xotira emas).
  - "O'ylab olay..." live-status: AI javob tayyorlagunча ekranda elapsed-time
    bilan yangilanib turadigan xabar ko'rsatiladi (core/thinking_indicator.py).
"""
import json
import os
import re
import logging
from aiogram import Router, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from core.ai_rotator import ai
from core.ai_tools import TOOLS, dispatch, get_user_notes, describe_tool_call
from core.thinking_indicator import ThinkingIndicator
import core.topic_sessions as topic_sessions
import core.roles as roles
import core.group_permissions as group_permissions
import core.preview_tokens as preview_tokens
import core.file_cleanup as file_cleanup
import core.ai_persona as ai_persona
import core.bot_identity as bot_identity
import core.user_profile as user_profile
import core.bot_loop_guard as bot_loop_guard
import core.clock as clock
import core.moderation as moderation
from core.output_files import output_files
from tools.file_tools import user_dir
import core.chat_mode as chat_mode
import config
from core.markdown_format import markdown_to_telegram_html

GROUP_CHAT_TYPES = ("group", "supergroup")
MAX_TOOL_ROUNDS = 4  # bitta so'rovda AI ketma-ket eng ko'pi bilan shuncha marta tool chaqira oladi

router = Router()
logger = logging.getLogger("ai_chat")


def _strip_bot_mention(text: str, bot_username: str | None) -> str:
    """'@BotUsername savol' -> 'savol' (AI'ga tozaroq matn borishi uchun)."""
    if not bot_username:
        return text
    return re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip() or text


MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # Bot API orqali yuklab olish chegarasi
UPLOAD_RETENTION_SECONDS = 3600       # yuklangan/yaratilgan fayllar 1 soat saqlanadi (ko'p bosqichli ish uchun)


def _safe_filename(name: str) -> str:
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[^\w.\- ()]", "_", name, flags=re.UNICODE)[:100].strip(" .")
    return name or "fayl"


def _unique_path(directory: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    path, n = os.path.join(directory, filename), 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{base}_{n}{ext}")
        n += 1
    return path


async def _save_upload(message: Message, user_id: int) -> tuple[str | None, str | None]:
    """Yuborilgan rasm/hujjatni foydalanuvchining shaxsiy papkasiga saqlaydi.
    (saqlangan_nom, None) yoki (None, xato_matni) qaytaradi."""
    if message.photo:
        media = message.photo[-1]
        filename = f"foto_{message.message_id}.jpg"
    else:
        media = message.document
        filename = _safe_filename(media.file_name or f"fayl_{message.message_id}")
    if media.file_size and media.file_size > MAX_UPLOAD_BYTES:
        return None, f"Fayl juda katta ({media.file_size // (1024 * 1024)} MB). Ruxsat: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB gacha."
    dest = _unique_path(user_dir(user_id), filename)
    try:
        await message.bot.download(media, destination=dest)
    except Exception as e:  # noqa: BLE001
        logger.warning("Faylni yuklab olib bo'lmadi: %s", e)
        return None, "Faylni yuklab olib bo'lmadi. Qayta yuboring."
    file_cleanup.schedule_file_delete(dest, delay_seconds=UPLOAD_RETENTION_SECONDS)
    return os.path.basename(dest), None


def _user_files_line(user_id: int) -> str:
    """AI foydalanuvchining hozirgi fayllarini bilishi uchun (albom/ko'p bosqichli ish)."""
    try:
        names = sorted(n for n in os.listdir(user_dir(user_id)) if os.path.isfile(os.path.join(user_dir(user_id), n)))
    except OSError:
        return ""
    if not names:
        return ""
    shown = ", ".join(f"'{n}'" for n in names[:30]) + (f" ...(+{len(names) - 30})" if len(names) > 30 else "")
    return (
        f"Foydalanuvchining hozir mavjud fayllari (1 soat saqlanadi): {shown}. Tool'larda file_path/image_paths "
        "sifatida AYNAN shu nomlarni ishlating; fayl kerak bo'lsa va ro'yxatda yo'q bo'lsa, uni yuborishni so'rang."
    )


@router.message(F.text | F.photo | F.document)
async def handle_message(message: Message):
    user_id = message.from_user.id
    is_group = message.chat.type in GROUP_CHAT_TYPES
    raw_text = message.text or message.caption or ""
    has_media = bool(message.photo or message.document)
    user_text = raw_text
    requester_id_for_limit = user_id  # chatmode'da pastda owner yoki yozuvchiga aniqlanadi
    charge_mode = "user"  # "user" — oddiy hisob | "owner" — chatmode owner'i (force) | "none" — VIP guruh, hisoblanmaydi

    if is_group:
        bot_username = bot_identity.get_username()
        is_mentioned = bool(bot_username) and f"@{bot_username.lower()}" in raw_text.lower()
        is_reply_to_bot = (
            message.reply_to_message is not None
            and message.reply_to_message.from_user is not None
            and message.reply_to_message.from_user.id == bot_identity.get_id()
        )

        # /chatmode on — guruh admin/egasi yoqsa, bot HAR BIR xabarga (tag/reply
        # shart emas) javob beradi. Standart holatda esa faqat IKKI yo'l bilan
        # murojaat qilinadi: (1) botni tag qilish, (2) botning O'Z xabariga
        # reply qilish — boshqa har qanday xabar E'TIBORSIZ qoldiriladi.
        chat_mode_rec = chat_mode.get(message.chat.id)
        if has_media:
            # Rasm/hujjat guruhda FAQAT bot tag/reply qilinganda qabul qilinadi — chatmode
            # ham bunga taalluqli emas (aks holda guruhdagi HAR bir rasm diskka tushardi).
            if not (is_mentioned or is_reply_to_bot):
                return
            chat_mode_rec = None
        elif chat_mode_rec is None and not (is_mentioned or is_reply_to_bot):
            return

        if chat_mode_rec is None:
            # Bot-to-Bot Communication Mode yoqilgani uchun endi guruhda BOSHQA
            # botlardan ham xabar kelishi mumkin — ular bir-birini cheksiz
            # "tag"lab, RUNAWAY tsiklga tushib qolishi mumkin (Telegram BotFather
            # ham shu haqda ochiq ogohlantiradi). Ketma-ket N martadan ortiq
            # bot-javob bo'lsa, zanjir jimgina uziladi; haqiqiy INSON yozishi
            # bilan hisoblagich qayta nolga tushadi.
            # ESLATMA: chatmode YOQILGAN guruhda bu himoya ATAYLAB o'chirilgan —
            # guruh egasi ongli ravishda "botlar cheksiz gaplashaversin" deb
            # tanlagani uchun (core/chat_mode.py).
            is_from_bot = bool(message.from_user.is_bot)
            if not bot_loop_guard.register_incoming(message.chat.id, is_from_bot):
                if bot_loop_guard.should_warn_once(message.chat.id):
                    try:
                        await message.bot.send_message(
                            config.SUPERADMIN_ID,
                            "⚠️ Bot-bot cheksiz tsikl xavfi aniqlandi va to'xtatildi.\n"
                            f"Guruh: {message.chat.title or message.chat.id} (ID: <code>{message.chat.id}</code>)\n"
                            f"Boshqa bot: @{message.from_user.username or message.from_user.full_name}",
                        )
                    except Exception:
                        logger.exception("Superadminga bot-loop ogohlantirishini yuborib bo'lmadi")
                return

        # Botga murojaat qilgan (yoki chatmode YOQILGAN guruhda — HAR BIR)
        # foydalanuvchining ID+ism+username'i sukut bo'yicha, sezilmasdan
        # yangilanadi — admin keyinchalik AI orqali "Falonchi kim edi?" deb
        # topa olishi uchun.
        await roles.touch_user_identity(message.bot, user_id, message.from_user.full_name, message.from_user.username)

        # Guruh admini /guruh_ruxsat bilan ro'yxat o'rnatgan bo'lsa, ro'yxatda
        # yo'q foydalanuvchilarga bot BUTUNLAY jim qoladi
        if not group_permissions.is_allowed_in_group(message.chat.id, message.from_user.username):
            return

        if chat_mode_rec is not None:
            if chat_mode_rec.get("vip"):
                # /vipchatmode (faqat superadmin yoqadi) — CHEKSIZ: hech kimning
                # limiti tekshirilmaydi va hisoblanmaydi.
                charge_mode = "none"
            else:
                # /chatmode on — avval yoqqan odamning limiti, u tugasa xabar
                # YOZGAN odamning o'z limiti, ikkalasi ham tugasa — javob yo'q.
                owner_id = chat_mode_rec["owner_id"]
                payer = roles.resolve_chatmode_payer(owner_id, user_id)
                if payer is None:
                    await message.reply(
                        "🚫 Bugungi limit tugadi (guruh chat rejimi egasining ham, sizning ham). "
                        "Ertaga qayta urinib ko'ring."
                    )
                    return
                requester_id_for_limit = payer
                charge_mode = "owner" if payer == owner_id else "user"
        else:
            # Standart guruh: bloklash/tasdiqlash tekshirilmaydi —
            # faqat kunlik limit tekshiriladi (avtomatik 20/kun bilan boshlanadi)
            if not roles.can_use_in_group(user_id):
                await message.reply("🚫 Bugungi so'rov limitingiz tugadi. Ertaga qayta urinib ko'ring.")
                return

        user_text = _strip_bot_mention(raw_text, bot_username)

    else:
        # SHAXSIY chatda yozgan HAR BIR foydalanuvchining ID+ism+username'i
        # ham sukut bo'yicha yangilanadi (hatto /start bosmasdan yozgan bo'lsa ham)
        await roles.touch_user_identity(message.bot, user_id, message.from_user.full_name, message.from_user.username)

        # SHAXSIY chatda — admin tasdig'i kerak emas, faqat bloklanmagan bo'lish shart
        if not roles.can_use_bot(user_id):
            await message.answer("🚫 Sizga botdan foydalanish cheklangan.")
            return
        if not roles.can_make_request(user_id):
            await message.answer("🚫 Bugungi so'rov limitingiz tugadi. Ertaga qayta urinib ko'ring.")
            return

    mod_access = await moderation.get_access(message.bot, message.chat.id, user_id) if is_group else None
    ctx = {
        "bot": message.bot, "chat_id": message.chat.id, "thread_id": message.message_thread_id,
        "is_group": is_group, "mod": mod_access,
    }
    thread_id = message.message_thread_id  # shaxsiy chatdagi topic bo'lsa to'ldiriladi

    if has_media:
        saved_name, upload_error = await _save_upload(message, user_id)
        if upload_error:
            await message.reply(f"⚠️ {upload_error}")
            return
        note = f"[Foydalanuvchi fayl yubordi, saqlangan nomi: '{saved_name}']"
        user_text = f"{note} {user_text}".strip() if user_text else f"{note} Shu fayl bilan nima qila olasiz?"

    extra_files_line = _user_files_line(user_id)
    if extra_files_line:
        user_text = f"{user_text}\n\n({extra_files_line})"

    # Shu TOPIC'ga tegishli suhbat tarixini olamiz — boshqa topic'lar bilan aralashmaydi
    history = topic_sessions.get_history(user_id, thread_id)

    # Foydalanuvchi O'ZINING shaxsiy AI API kalitini ulagan bo'lsa (/apikalit) —
    # bu FAQAT SHAXSIY chatda ishlaydi. GURUHDA — hatto shaxsiy kalit ulagan
    # bo'lsa ham — har doim UMUMIY (admin) kalit va odatdagi guruh-limiti
    # ishlatiladi (guruhda hamma bir xil "hovuz"dan foydalanishi kerak).
    import core.user_api_keys as user_api_keys
    uses_personal_key = (not is_group) and (user_api_keys.get_any_personal_key(user_id) is not None)

    if uses_personal_key:
        messages = history + [{"role": "user", "content": user_text}]
    else:
        system_prompt = ai_persona.get_full_system_prompt()
        system_prompt += f"\n\n{await user_profile.basic_info_line(message.bot, message)}"
        # AI'ning "soati": hozirgi sana/vaqt (aks holda model bugungi sanani bilmaydi)
        system_prompt += f"\n\n{clock.time_context_line()}"
        if mod_access is not None:
            system_prompt += f"\n\n{moderation.SYSTEM_HINT}{await moderation.context_line(message.bot, message)}"
        if is_group:
            # Guruhda uzun javoblar chatni "to'ldirib" tashlaydi — QISQA yozish
            # kerak. Fayl/hujjat/kod so'ralganda esa bu cheklov qo'llanilmaydi
            # (o'sha holatlarda tabiiy ravishda batafsilroq bo'lishi kerak bo'lsa).
            system_prompt += (
                "\n\nMUHIM (guruh chati): javobingiz QISQA bo'lsin — odatda 1-4 gap "
                "yetarli. Faqat foydalanuvchi ANIQ batafsil tushuntirish so'rasa, "
                "yoki hujjat/fayl/kod yaratish kabi vazifa uzunroq matn talab qilsa, "
                "shundagina kengroq yozing."
            )
        # DOIMIY eslatmalar (remember_note orqali saqlangan) — topic tarixidan farqli
        # o'laroq, bular HAR DOIM (20-xabar chegarasidan tashqari ham) qo'shiladi.
        saved_notes = get_user_notes(user_id)
        if saved_notes:
            notes_block = "\n".join(f"- {n}" for n in saved_notes)
            system_prompt += f"\n\nBu foydalanuvchi haqida siz avval eslab qolgan narsalar:\n{notes_block}"

        # Suhbatning ESKI (endi so'z-ma-so'z tarixda saqlanmaydigan) qismi —
        # "rolling summary" (core/history_summarizer.py) — shu tufayli suhbat
        # qancha uzun bo'lmasin, muhim kontekst UMUMAN yo'qolmaydi.
        conv_summary = topic_sessions.get_summary(user_id, thread_id)
        if conv_summary:
            system_prompt += f"\n\nSuhbatning OLDINGI (eski, xulosalangan) qismi:\n{conv_summary}"

        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_text}]

    indicator = await ThinkingIndicator(
        bot=message.bot, chat_id=message.chat.id, thread_id=thread_id,
        reply_to_message_id=message.message_id,
    ).start()

    final_text = "..."       # Telegram'ga YUBORILADIGAN (HTML'ga o'girilgan) matn
    raw_text_for_history = "..."  # suhbat tarixiga SAQLANADIGAN asl (markdown) matn —
                                    # HTML teglarini tarixga saqlasak, AI keyingi safar
                                    # o'sha teglarni o'zi ham qaytara boshlashi mumkin edi
    tool_outputs: list[tuple[str, dict]] = []

    # Moderatsiya tool'lari faqat GURUHDA, yozuvchi admin BO'LSA va xabar shu mavzuda
    # bo'lsagina qo'shiladi — har xabarga behuda ~20 ta schema token yemasin.
    # DIQQAT: faqat JORIY xabarni emas, so'nggi tarixni ham tekshiramiz — aks holda
    # bot "kimning ID'sini bilmoqchisiz?" deb so'ragach, foydalanuvchi shunchaki
    # ID'ni yuborsa (o'zida "mute"/"ban" so'zi bo'lmaydi), tool yana yo'qolib qolardi.
    active_tools = TOOLS
    if mod_access is not None:
        recent_context = " ".join((m.get("content") or "") for m in history[-6:]) + " " + user_text
        if moderation.looks_like_mod_request(recent_context):
            mod_schemas = moderation.tool_schemas(message.bot, mod_access)
            if mod_schemas:
                active_tools = TOOLS + mod_schemas

    try:
        # GURUHDA user_id=None yuboriladi — shu bilan ai.chat() shaxsiy kalitni
        # UMUMAN tekshirmaydi, har doim umumiy/admin kalitidan foydalanadi
        # (guruhda hamma so'rovi bir xil hisob-kitobga tushishi uchun).
        chat_user_id = None if is_group else user_id
        convo = list(messages)  # tool round-trip xabarlari shu yerga qo'shib boriladi
        result = await ai.chat(convo, tools=active_tools, user_id=chat_user_id)
        choice = result["response"].choices[0].message

        # AGENTIC TSIKL: AI tool chaqirsa — natijani unga QAYTARIB beramiz, u esa
        # tabiiy javob yozadi (yoki kerak bo'lsa keyingi tool'ni chaqiradi).
        # Avval tool natijasi xom dict ko'rinishida to'g'ridan-to'g'ri foydalanuvchiga
        # ko'rsatilardi ("[search_web]: {'query': ...}") — endi bunday bo'lmaydi.
        # MAX_TOOL_ROUNDS — cheksiz tsikldan himoya.
        file_done = False
        rounds = 0
        while choice.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            # "Miyamni ishga solyapman..." o'rniga ANIQ nima qilinayotganini
            # ko'rsatamiz (masalan "ParadoksHub" haqida PPTX yaratilmoqda...).
            first_call = choice.tool_calls[0]
            try:
                first_args = json.loads(first_call.function.arguments)
            except (ValueError, TypeError):
                first_args = {}
            await indicator.update_status(describe_tool_call(first_call.function.name, first_args))

            assistant_msg = {
                "role": "assistant",
                "content": choice.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in choice.tool_calls
                ],
            }
            tool_result_msgs = []
            for tool_call in choice.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments)
                except (ValueError, TypeError):
                    args = {}
                tool_result = await dispatch(tool_call.function.name, user_id, args, ctx)
                tool_outputs.append((tool_call.function.name, tool_result))
                tool_result_msgs.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:8000],
                })

            has_file = any(output_files(r) for _, r in tool_outputs)
            if has_file:
                # Fayl yaratilgan — u pastda alohida yuboriladi; qayta AI so'rovi
                # (qo'shimcha xarajat) shart emas.
                file_done = True
                final_text = "Tayyor ✅"
                raw_text_for_history = final_text
                break

            convo = convo + [assistant_msg] + tool_result_msgs
            result = await ai.chat(convo, tools=active_tools, user_id=chat_user_id)
            choice = result["response"].choices[0].message

        if not file_done:
            if choice.tool_calls:
                # Tsikl chegarasiga yetildi, lekin AI hali ham tool chaqirmoqchi —
                # xavfsizlik uchun to'xtatamiz va bor natijani ko'rsatamiz.
                final_text = "⚠️ Juda ko'p bosqichli so'rov — natijalar:\n" + "\n".join(
                    f"[{n}]: {str(r)[:500]}" for n, r in tool_outputs
                )
                raw_text_for_history = final_text
            else:
                raw_text_for_history = choice.content or "..."
                final_text = markdown_to_telegram_html(choice.content) if choice.content else "..."

    except Exception as e:
        final_text = f"⚠️ Xatolik yuz berdi: {e}"
        raw_text_for_history = final_text

    await indicator.finish(final_text)

    # Fayl/prezentatsiya/diagramma yaratish — 3x qimmatroq (guruhda ham,
    # shaxsiy chatda ham bir xil qoida)
    has_file_result = any(output_files(r) for _, r in tool_outputs)
    weight = roles.FILE_GENERATION_WEIGHT if has_file_result else 1
    if charge_mode == "owner":
        await roles.register_request(message.bot, requester_id_for_limit, weight=weight, force=True)
    elif charge_mode == "user":
        await roles.register_request(message.bot, requester_id_for_limit, weight=weight)
    # charge_mode == "none" (VIP chatmode) — hisoblanmaydi

    # Fayl yaratgan tool'lar bo'lsa — statusdan keyin haqiqiy fayllarni yuboramiz
    # (bitta tool bir nechta fayl qaytarishi mumkin — masalan extract_pdf_images, split_pdf)
    for tool_name, tool_result in tool_outputs:
        for file_path in output_files(tool_result):
            try:
                kb = None
                if file_path.lower().endswith(".pptx"):
                    token = preview_tokens.store(file_path)
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🖼 Slaydlarni ko'rish", callback_data=f"preview:{token}")]
                    ])
                # message_thread_id BERILMAYDI — aiogram buni message.is_topic_message
                # orqali o'zi avtomatik to'g'ri biriktiradi; qo'lda ham berilsa,
                # "got multiple values for keyword argument" xatosi chiqadi.
                # reply_document — foydalanuvchi/botning ASL xabariga REPLY qilib
                # yuboradi (kim so'ragani aniq bo'lishi uchun, guruhda bir nechta
                # AI-bot bir-biriga javob berayotganda ham aralashib ketmasin).
                await message.reply_document(
                    FSInputFile(file_path),
                    caption=f"📄 {os.path.basename(file_path)} ({tool_name})",
                    reply_markup=kb,
                    allow_sending_without_reply=True,
                )
            except Exception as e:
                # ENG MUHIMI: avval bu yerda xatolik jimgina yutilib ketardi (foydalanuvchi
                # "Tayyor" degan xabardan keyin hech narsa ko'rmasdi). Endi xato ko'rinadi.
                logger.exception("Faylni yuborishda xatolik: %s", file_path)
                await message.reply(f"⚠️ Faylni yuborishda xatolik: {e}")
                continue

            # Telegram faylni allaqachon qabul qildi — diskda saqlashning hojati yo'q.
            # .pptx uchun "🖼 Ko'rish" tugmasi bosilishi mumkinligi uchun 15 daqiqa
            # kutamiz, qolganlarini (docx/xlsx/pdf) DARHOL o'chiramiz.
            if kb is not None:
                file_cleanup.schedule_file_delete(file_path, delay_seconds=900)
            else:
                file_cleanup.delete_file_now(file_path)

    # Shu topic'ning tarixiga user xabari + AI javobini yozib qo'yamiz
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "user", user_text)
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "assistant", raw_text_for_history)


