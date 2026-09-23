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
| `core/thinking_indicator.py`  | (yangi)              | Native "Thinking…" (Bot API 9.3+ `sendMessageDraft`) + matnli fallback |
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
| `core/shared_keys.py`         | (yangi)               | **UMUMIY** (bot egasiga tegishli) kalitlar — endi `.env` EMAS, FAQAT superadmin paneldan, provayder boshiga 1-10 ta, Round-Robin |

## Foydalanuvchi haqida DOIMIY xotira (uzoq muddatli, "meni ... deb chaqir")
**Muhim farq:**
- **Topic suhbat tarixi** (`core/topic_sessions.py`) — faqat oxirgi 20 xabar,
  shundan keyin unutiladi (qisqa muddatli kontekst)
- **`remember_note` tool** (`core/ai_tools.py`) — foydalanuvchi "eslab qol",
  "meni ... deb chaqir" desa, AI buni DB'ga DOIMIY yozadi (foydalanuvchi
  boshiga eng ko'pi 30 ta, eskilari avtomatik siljib chiqadi) va **HAR BIR
  keyingi suhbatga** (hatto boshqa kun/topic'da ham) avtomatik qaytariladi
  (`handlers/ai_chat.py` — system prompt'ga qo'shiladi). Test qilindi:
  saqlash, qaytarish, foydalanuvchilar orasida aralashmaslik — barchasi to'g'ri.

**Superadmin/admin nazorati (xavfsizlik va maxfiylik uchun):**
`/panel → Foydalanuvchilar → <user> → 🧠 Xotirani ko'rish` — har bir
foydalanuvchi haqida AI nimalarni "eslab qolgani"ni to'liq ko'rish, va
`🗑 Hammasini tozalash` bilan istalgan vaqt o'chirish mumkin (masalan
foydalanuvchi so'rasa, yoki noto'g'ri/nomaqbul narsa saqlangan bo'lsa).

**Shaffoflik bo'yicha eslatma:** bot yopiq (faqat tasdiqlangan userlar)
tizim bo'lgani uchun, foydalanuvchilarga botdan foydalanishdan oldin
suhbatlari va saqlangan eslatmalari admin tomonidan ko'rilishi/nazorat
qilinishi mumkinligini bildirish (masalan `/start` xabarida bir qatorda)
tavsiya etiladi — bu kod darajasida majburlanmagan, faqat tavsiya.

## AI shaxsiyati (system prompt) — FAQAT superadmin
`/panel → 🎭 AI shaxsiyati` — AI o'zini kim deb tanishtirishini, qaysi
community/kanalga tegishli ekanini belgilaysiz (masalan: "Sen Paradoks AI
san, Paradoks Hub community'ning AI agentisan. Kanal: @ParadoksHub").
Bu matn HAR BIR foydalanuvchining HAR BIR xabariga avtomatik qo'shiladi
(`core/ai_persona.py`, `handlers/ai_chat.py`). "↩️ Standartga qaytarish"
tugmasi bilan bekor qilish mumkin.

**Texnik eslatma:** Anthropic (Claude) API `system` rolini messages
ro'yxati ICHIDA emas, alohida parametr sifatida talab qiladi — Groq/OpenAI/
DeepSeek/xKiro esa standart tarzda messages ichida qabul qiladi.
`core/ai_rotator.py` buni avtomatik ajratib beradi (test qilindi).

## Native "Thinking…" ko'rsatkichi (Bot API 9.3+)
Bu — Telegram'ning AI-botlar uchun MAXSUS rasmiy funksiyasi (`sendMessageDraft`,
2025-12-31, umumiy botlarga 2026-03-01'dan ochiq), oddiy matn-emoji emas —
Telegram klientining o'zi chizadigan native ko'rsatkich (o'z ikonkasi bilan).
Manba: https://core.telegram.org/bots/api#sendmessagedraft

- `bot.send_message_draft(text="")` — bo'sh matn "Thinking…" placeholder'ni
  ko'rsatadi; draft efemer (30s) bo'lgani uchun har 20s'da bir xil `draft_id`
  bilan yangilanadi (animatsiyali)
- Javob tayyor bo'lgach oddiy `send_message()` chaqiriladi — draft o'zi yopiladi
- **Talab:** shu funksiya ishlashi uchun botingizda BotFather orqali forum-topic
  rejimi yoqilgan bo'lishi kerak (Topics funksiyasi bilan bir xil sozlama
  bo'lishi mumkin — aniqlashtiring)
- **Avtomatik fallback:** agar bu sozlama yoqilmagan bo'lsa yoki xatolik
  chiqsa, kod avtomatik eski usulga (`"🌀 O'ylayapti... Ns"` matnli xabar,
  edit qilib turiladigan) o'tadi — funksionallik hech qachon butunlay
  ishlamay qolmaydi. Ikkala yo'l ham mock-test bilan tekshirildi.
- `requirements.txt`: `aiogram>=3.31` talab qilinadi (bu metod shu versiyada qo'shilgan)

## Superadmin panel orqali umumiy AI kalitlarni boshqarish
`.env`dagi `GROQ_API_KEYS` va h.k. endi faqat **fallback** (ixtiyoriy, eski
uslub). Asosiy usul: `/panel → 🔑 AI kalitlar → <provayder>` — har bir
provayderga (xKiro, Groq, OpenAI, Anthropic, DeepSeek) alohida **1 dan 10
tagacha** kalit qo'shiladi, kalit qo'shishdan oldin haqiqiy so'rov bilan
tekshiriladi. Bot qayta ishga tushirilishi SHART EMAS — kalit qo'shilishi
bilan `core/ai_rotator.py` DB'dan jonli o'qib, darhol ishlata boshlaydi
(test qilindi: rotatsiya, 10ta limit, kalit o'chirish — barchasi ishlaydi).

## xKiro provayderi (joriy deploy nishoni)
`xkiro-test-v7.html`dan aniqlandi: xKiro to'liq OpenAI-mos API
(`https://api.xkiro.com/v1`, standart `/chat/completions`). Superadmin
`/panel → AI kalitlar → xKiro → 🧠 Modelni o'zgartirish` orqali qaysi
modelni ishlatishni tanlaydi (standart: `qwen/qwen3.8-max:free`). `xkiro`
provayder ustuvorlik ro'yxatida BIRINCHI o'rinda turadi.

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

## Prezentatsiya sifati: standart "PRO"/premium + dark theme + brendlash
`create_presentation`/`create_diagram` endi ikkita muhim standart xatti-harakatga ega:

1. **Standart holatda "pro"** — agar foydalanuvchi prezentatsiya qanday
   bo'lishi kerakligini (uslub/uzunlik) aniq tasvirlamasa, AI'ga tool
   tavsifida (`core/ai_tools.py`) shunday ko'rsatma berilgan: kamida 6-10
   mazmunli slayd, turli slayd turlari (chart/stat/comparison/quote/timeline),
   to'liq gaplar — faqat qisqa bullet-content bilan cheklanmasin. Foydalanuvchi
   aniq "qisqa"/"3 slayd" desagina, shunga mos kichikroq variant tuziladi.
2. **Dark theme standart** (`tools/diagrams.py` — `_LIGHT_THEME`/`_DARK_THEME`,
   `set_theme()`) — `dark_theme` parametri berilmasa, TRUE. Ikkala tema ham
   vizual tekshirildi (rasm sifatida render qilib ko'rildi): kontrast,
   grafik ranglari, karta fonlari — barchasi to'g'ri ishladi.
   Foydalanuvchi "och/light rang" desa, AI `dark_theme: false` beradi.
3. **Fayl NOMIGA brendlash** (slaydga emas) — `core/bot_identity.py` orqali
   bot username'i (`main.py`da `bot.get_me()` bilan olinadi) fayl nomiga
   `_by_<username>` qo'shiladi, masalan `Hisobot_by_ParadoksAiBot_123.pptx`.

**Concurrency eslatma:** rang-tema `tools/diagrams.py`da modul darajasida
global (`set_theme()` orqali almashtiriladi), shuning uchun bir vaqtning
o'zida ikki xil temadagi qurilish aralashib ketmasligi uchun
`core/ai_tools.py`da `asyncio.Lock()` bilan barcha prezentatsiya/diagramma
qurilishlari ketma-ket (serial) qilib qo'yilgan.

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

## Xotira/disk tozalash (out-of-memory'dan himoya)
Render'ning kichik tarif rejalarida (512MB RAM) LibreOffice konvertatsiyasi
va generatsiya qilingan fayllar joy band qilib, xotira tugab qolishi mumkin.
`core/file_cleanup.py` buni oldini oladi (test qilindi):
- Yaratilgan fayl (docx/xlsx/pdf) foydalanuvchiga yuborilgach — **darhol** o'chiriladi
- `.pptx` — "🖼 Ko'rish" tugmasi uchun 15 daqiqa kutiladi, keyin avtomatik o'chiriladi
  (yoki tugma bosilishi bilan darhol)
- Slaydlarni rasm qilib ko'rsatishda LibreOffice yaratgan vaqtinchalik PDF+PNG
  papkasi rasmlar yuborilgach **darhol** o'chiriladi
- Bot qayta ishga tushganda (masalan qulab tushgandan keyin), 1 soatdan katta
  qoldiq fayllar avtomatik tozalanadi (`cleanup_stale_files`, `on_startup`da)

**Muhim:** bu faqat DISKDAGI VAQTINCHALIK fayllarga tegishli — DB'dagi hech
narsa (suhbat tarixi, foydalanuvchi holati, AI kalitlari va h.k.) bundan
ta'sirlanmaydi, ular Telegram-kanalda saqlanishda davom etadi.

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
