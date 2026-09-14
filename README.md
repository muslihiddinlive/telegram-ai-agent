# Telegram AI Agent — Skeleton

Bu skeleton quyidagi shaxsiy repolaringizdagi patternlar asosida yig'ildi:

| Modul                        | Manba repo          | Nima olindi |
|------------------------------|----------------------|-------------|
| `core/tgdb.py`                | mafia_host_bot       | Fayl + Telegram-document gibrid DB (pin orqali crash-safe) |
| `core/crypto_store.py`        | userbot-ai           | Session/API-key shifrlash (Fernet) |
| `core/accounts_store.py`      | userbot-ai           | Har bir foydalanuvchi uchun shifrlangan session saqlash |
| `core/ai_rotator.py`          | tgs-expert-bot       | Ko'p-provayder API key rotatsiyasi + cooldown |
| `core/ai_tools.py`            | tgs-expert-bot + ms-file-toolkit | Function-calling tool registry va dispatch |
| `core/channels.py`            | KanalKotibRobot      | Dinamik kanal aniqlash + admin-based ruxsat |
| `admin/panel.py`              | StokerDownloader     | Superadmin panel (foydalanuvchilar/guruhlar/kanallar boshqaruvi) |
| `tools/file_tools.py`         | ms-file-toolkit      | **To'liq ulandi** (PyPI v0.4.0): 36 ta DOCX/XLSX/PPTX/PDF tool, schema Claude→Groq formatiga avtomatik konvertatsiya qilinadi, har foydalanuvchi uchun alohida xavfsiz papka (`data/user_files/<user_id>/`) |
| `core/thinking_indicator.py`  | (yangi)              | "O'ylab olay... Ns" live-status xabari + forum-topic (`message_thread_id`) qo'llab-quvvatlash |
| `core/topic_sessions.py`      | (yangi)              | Shaxsiy chat Topics (Bot API 9.4, 2026) — har bir topic mustaqil suhbat konteksti bilan |
| `handlers/topics.py`          | (yangi)              | `/yangi_mavzu`, `/mavzular` komandalari |
| `core/pending_input.py`       | StokerDownloader      | Matn-kiritish orqali bosqichma-bosqich oqimlar (FSM, xotirada) |
| `core/userbot_login.py`       | StokerDownloader      | Telethon: telefon → SMS kod → 2FA parol → session olish |
| `core/userbot_runtime.py`     | (yangi)               | Saqlangan session orqali userbot'ni ishga tushirish, xabar tinglash |
| `core/auto_reply.py`          | StokerDownloader      | Kalit-so'z auto-reply + "away" (band) tizimi |
| `handlers/userbot_commands.py`| (yangi)               | `/userbot`, `/kalitsoz_qoshish`, `/kalitsozlar`, `/away` |
| `handlers/pending_text.py`    | (yangi)               | pending_input holatidagi matnlarni yo'naltiradi (ai_chat'dan OLDIN ishlaydi) |

## Yangilanish: debounced DB yozish (StokerDownloader patterni)
`core/tgdb.py` endi har `save()` chaqiruvida darhol Telegram'ga yozmaydi —
faqat "dirty" belgisini qo'yadi, background task har 5 soniyada bittalab
flush qiladi. Kritik amallar (session saqlash, premium/ruxsat berish) uchun
`tgdb.save(bot, force=True)` chaqiring — darhol yoziladi.

## Fayl generatsiyasi qanday ishlaydi
Foydalanuvchi "menga hisobot yoz" desa, AI `create_docx`/`create_xlsx`/... tool'ini
chaqiradi, natija `data/user_files/<user_id>/` papkasida yaratiladi va bot uni
avtomatik hujjat sifatida yuboradi (`handlers/ai_chat.py`). `file_path` sifatida
AI qanday nom bersa ham, xavfsizlik uchun har doim foydalanuvchining o'z papkasi
ichiga normalizatsiya qilinadi (`tools/file_tools.py`).

## Userbot avtomatik qayta ulanishi
Bot qayta ishga tushganda (`on_startup`), oldin ulangan barcha userbot
sessiyalari DB'dan o'qilib, avtomatik qayta ulanadi — foydalanuvchi
qayta `/userbot` qilishi shart emas.
1. Foydalanuvchi `/userbot` yozadi
2. Bot API ID, API HASH (https://my.telegram.org dan), telefon so'raydi
3. Telegram SMS/ilova orqali kod yuboradi — foydalanuvchi shu yerga yozadi
4. Agar 2FA yoqilgan bo'lsa — parol so'raladi
5. Session shifrlab saqlanadi, keyin `/kalitsoz_qoshish` bilan avto-javob qoidalari sozlanadi

## ⚠️ Muhim: Private Chat Topics yoqish
Bu funksiya ishlashi uchun: **@BotFather → /mybots → botingiz → Bot Settings**
ichida "Topics"/"Private Chat Topics" ni yoqing (2026-yil fevral, Bot API 9.4
bilan qo'shilgan). Aks holda `createForumTopic` xato qaytaradi.

## Stack (default tanlov)
- **aiogram 3.x** (async) — ko'pchilik repolaringizda webhook+Render kombinatsiyasi ishlatilgani uchun shu davom ettirildi
- **Webhook mode** (Render uchun tayyor)
- DB: Telegram supergroup (`DB_GROUP_ID`) — alohida tashqi DB shart emas

> Eslatma: bu ishlaydigan skeleton, production emas — har bir modulda `# TODO` joylar sizning aniq talablaringizga moslashtirish uchun qoldirilgan.

## O'rnatish
```bash
pip install -r requirements.txt
cp .env.example .env   # to'ldiring
python main.py
```
