# Telegram AI Agent — Skeleton

Bu skeleton quyidagi shaxsiy repolaringizdagi patternlar asosida yig'ildi
(barcha 8 ta rejalashtirilgan repo endi ulandi: tgs-expert-bot, userbot-ai,
ms-file-toolkit, weChat, StokerDownloader, groq-pptx-bot, KanalKotibRobot,
mafia_host_bot):

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
| `core/roles.py`               | StokerDownloader (soddalashtirilgan) | 3-bosqichli ruxsat: superadmin/admin/tasdiqlangan-user + kunlik limit. **Referral/stars-wallet/premium OLIB TASHLANDI** — yopiq (faqat taklif qilingan) tizim uchun keraksiz |
| `tools/diagrams.py`           | groq-pptx-bot         | To'liq ko'chirilgan — pptx slaydlar: bullet, chart, flowchart, orgchart, venn, timeline, section, stat, quote, comparison |
| `tools/presentation_builder.py`| groq-pptx-bot (moslashtirilgan) | AI `create_presentation`/`create_diagram` tool'i chaqirganda haqiqiy `.pptx` yaratadi |
| `tools/slide_renderer.py`     | groq-pptx-bot         | `.pptx` slaydlarini PNG rasmga aylantiradi (LibreOffice + PyMuPDF) — "🖼 Ko'rish" tugmasi |
| `handlers/slide_preview.py`   | (yangi)               | Slaydlarni albom (media-group) sifatida yuboradi |
| `handlers/admin_terminal.py`  | weChat                | `exec:` — Live Python terminal, **FAQAT superadmin** (admin ham yo'q) |
| `core/user_api_keys.py`       | (yangi)               | Foydalanuvchi o'zining AI API kalitini ulashi (validatsiya bilan) |
| `handlers/api_integration.py` | (yangi)               | `/apikalit`, "🔑 AI API integratsiya" tugmasi |

## Shaxsiy AI API kalit ulash
Foydalanuvchi `/apikalit` yoki `/start`dagi "🔑 AI API integratsiya" tugmasi
orqali Groq/OpenAI/Anthropic'dan birini tanlaydi, kalitini yuboradi — kalit
**darhol haqiqiy so'rov bilan tekshiriladi** (`core/user_api_keys.validate_key`),
ishlasa shifrlab saqlanadi. Shundan keyin `core/ai_rotator.py` shu foydalanuvchi
uchun UMUMIY (bot egasining) kalitlari o'rniga FAQAT uning shaxsiy kalitini
ishlatadi — boshqa userlarga va sizning limitingizga tegmaydi (test qilindi:
shaxsiy kalit ulangan/ulanmagan userlar bir-biriga ta'sir qilmaydi).

## Ruxsat ierarxiyasi
- **superadmin** (`.env`dagi `SUPERADMIN_ID`, bitta) — adminlarni va barcha userlarni boshqaradi, istalgan vaqt ruxsatni bekor qila oladi
- **admin** (superadmin tayinlaydi) — FAQAT tasdiqlangan userlarni boshqaradi; boshqa adminlar yoki superadmin haqida hech narsa ko'rmaydi (panelda "Adminlar" bo'limi umuman chiqmaydi)
- **tasdiqlangan user** — admin yoki superadmin tasdiqlagan, kunlik so'rov limiti bilan (standart 50/kun, `/panel` orqali o'zgartiriladi)
- **pending** (yangi /start bosgan) — botdan foydalana olmaydi, so'rovi superadmin+barcha adminlarga tugma bilan yuboriladi

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

## Prezentatsiya/diagramma yaratish (groq-pptx-bot)
AI "prezentatsiya tayyorla" yoki "diagramma chiz" desa, `create_presentation`/
`create_diagram` tool'lari chaqiriladi — natija oddiy `ms-file-toolkit`ning
`create_pptx`'idan farqli o'laroq, 10 xil professional slayd turi (grafik,
flowchart, org-chart, Venn, timeline va h.k.) bilan yaratiladi. Fayl
yuborilgandan keyin **"🖼 Slaydlarni ko'rish"** tugmasi chiqadi — bosilsa,
PowerPoint ochmasdan har bir slaydni rasm sifatida ko'rish mumkin.

**Talab:** slayd-rasm ko'rish uchun serverda **LibreOffice** o'rnatilgan
bo'lishi kerak (bepul, https://www.libreoffice.org). Bo'lmasa, faqat shu
funksiya ishlamaydi — fayl yaratish/yuborish baribir ishlayveradi.

## ⚠️ Live Exec terminal (`exec:`) — juda ehtiyot bo'ling
Faqat **superadmin** (config.SUPERADMIN_ID) xabar sifatida `exec: <kod>`
yuborsa, kod serverda TO'G'RIDAN-TO'G'RI bajariladi (cheklanmagan RCE).
Bu — production'da debugging uchun kuchli, lekin xavfli vosita. Agar kerak
bo'lmasa, `main.py`da `admin_terminal_router`ni ro'yxatdan olib tashlang.
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
