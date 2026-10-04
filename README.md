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
| `tools/file_tools.py`         | ms-file-toolkit      | **v0.6.0ga yangilandi**: 36 dan **82 ta** tool'ga o'sdi — DOCX/XLSX/PPTX/PDF'dan tashqari endi: rasm tahrirlash (crop/resize/rotate/OCR), arxivlar (zip), kod fayllar bilan ishlash, OpenDocument (odt/ods/odp), **`search_web`/`fetch_url_text`/`download_file`** (internet qidiruv/o'qish/yuklab olish). Schema avtomatik konvertatsiya qilinadi, har foydalanuvchi uchun alohida xavfsiz papka, path-normalizatsiya `dir_path`ni ham qamrab oladi (test qilindi: traversal urinishi xavfsiz qoldi) |
| `core/thinking_indicator.py`  | (yangi)              | Native "Thinking…" (Bot API 9.3+ `sendMessageDraft`) + matnli fallback |
| `core/topic_sessions.py`      | (yangi)              | Shaxsiy chat Topics (Bot API 9.4, 2026) — har bir topic mustaqil suhbat konteksti bilan |
| `handlers/topics.py`          | (yangi)              | `/yangi_mavzu`, `/mavzular` komandalari |
| `core/pending_input.py`       | StokerDownloader      | Matn-kiritish orqali bosqichma-bosqich oqimlar (FSM, xotirada) |
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
  boshiga eng ko'pi 30 ta, eskilari avtomatik siljib chiqadi) va keyingi
  suhbatlarga avtomatik qaytariladi. **Eslatma qayerda aytilgan bo'lsa, faqat o'sha yerda ishlaydi:**
  guruhda aytilgani shu guruhga bog'lanadi (`db["group_notes"]`, boshqa guruhga va shaxsiy chatga chiqmaydi),
  shaxsiy chatda aytilgani esa guruhlarga chiqmaydi
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

## Botga yozgan HAR BIR foydalanuvchining ID+ism+username'i doimiy saqlanadi
`core/roles.touch_user_identity()` — botga chindan murojaat qilgan (shaxsiy
chatda yozgan, YOKI guruhda tag/reply qilgan) har bir foydalanuvchining
ID+ism+username'i sukut bo'yicha, **foydalanuvchi buni sezmasdan** yangilanadi
(`handlers/ai_chat.py`da avtomatik chaqiriladi). Bu, hatto foydalanuvchi
hali tasdiqlanmagan (pending) bo'lsa ham, ishlaydi.

**Admin uchun qulaylik**: `lookup_user` AI tool'i — admin/superadmin AI bilan
tabiiy tilda gaplashib, "Azizbek kim edi?", "@ali qanday foydalanyapti?"
desa, AI ism/username/ID bo'yicha qidirib, ID/rol/limit/bugungi ishlatilgan
sonini aytib beradi. **Oddiy foydalanuvchi bu tool'dan foydalana olmaydi**
(admin/superadmin tekshiruvi bilan himoyalangan). Test qilindi: avtomatik
saqlash, ism/username bo'yicha qidiruv, oddiy user bloklanishi, admin
ruxsati — barchasi to'g'ri ishladi.

## Foydalanuvchi profili — username, ID, ism, bio, profil rasmi
- **Avtomatik (har xabarda, qo'shimcha so'rovsiz)**: username, ID, ism,
  familiya — `core/user_profile.basic_info_line()` orqali AI'ning system
  promptiga qo'shiladi (`handlers/ai_chat.py`)
- **Talab bo'yicha (AI tool, faqat kerak bo'lganda)**: `get_user_profile` —
  bio'ni oladi (`bot.get_chat`) va eng so'nggi profil rasmini chatga
  yuboradi (`bot.get_user_profile_photos` + `send_photo`)
- **Maxfiylik**: o'z profilini har kim so'rashi mumkin; **boshqa birovning**
  profilini FAQAT admin/superadmin so'rashi mumkin — oddiy user so'rasa,
  aniq xato qaytariladi. Test qilindi: o'zini so'rash, boshqa birovni admin
  emas holda so'rash (bloklanadi), superadmin sifatida so'rash (ruxsat) —
  barchasi to'g'ri ishladi.
- **Cheklov**: bio faqat bot bilan SHAXSIY chatni boshlagan foydalanuvchilar
  uchun olinishi mumkin (Telegram API cheklovi).

## AI o'z imkoniyatlarini biladi (CAPABILITIES_BLOCK)
`core/ai_persona.py`dagi `CAPABILITIES_BLOCK` — botning barcha imkoniyatlari
(hujjatlar, prezentatsiya/diagramma, rasm+OCR, arxiv, internet qidiruv,
doimiy xotira, topics) tushunarli tarzda tasvirlangan matn. Bu superadmin
belgilagan "kim ekanligi" (identifikatsiya) matnidan **ALOHIDA** — ikkalasi
`get_full_system_prompt()` orqali HAR DOIM birga qo'shiladi. Shuning uchun
superadmin `/panel → AI shaxsiyati`da faqat "kim ekanligini" yozadi
(masalan "Men Paradoks AI man..."), imkoniyatlarni alohida tasvirlashning
hojati yo'q — ular avtomatik. Test qilindi: standart holatda ham, custom
persona o'rnatilganda ham, ikkalasi to'g'ri birlashadi.

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

## Markdown -> Telegram HTML avtomatik konvertatsiya
AI odatda oddiy Markdown formatida javob beradi (`**qalin**`, `` `kod` ``,
```` ```kod bloki``` ````, `[link](url)`, `# Sarlavha`), lekin bot HTML
parse_mode'da ishlaydi — bular avval mos kelmasdi (`"**so'z**"` literal
yulduzchalar bilan ko'rinardi). `core/markdown_format.py` endi AI javobini
yuborishdan OLDIN avtomatik Telegram HTML'ga o'giradi (test qilindi:
qalin/kursiv/aralash, kod bloklari, linklar, sarlavhalar, va HTML-injection
xavfsizligi — `<script>` kabi matnlar avtomatik escape qilinadi).

**Muhim texnik nozik nuqta:** suhbat TARIXIGA (keyingi xabarlar uchun AI
kontekstiga) HTML'ga o'girilgan matn EMAS, AI'ning ASL (markdown) matni
saqlanadi — aks holda AI o'z tarixida `<b>` kabi teglarni ko'rib, ularni
o'zi ham qaytara boshlashi mumkin edi.

## Native "Thinking…" ko'rsatkichi — 3 bosqichli (sendRichMessageDraft)
Telegram'da ikkita YAQIN, lekin FARQLI AI-draft metodi bor:

- **`sendRichMessageDraft`** + `<tg-thinking>MATN</tg-thinking>` tegi — BOY
  (rich) draft. Bu YAGONA yo'l — matnni o'zimiz moslashtirib, SHU BILAN
  BIRGA native yulduzcha-logo+taymerni saqlab qolish mumkin. Rasmiy hujjat
  hatto maxsus emoji-ikonkalar tavsiya qiladi: https://t.me/addemoji/AIActions
  Manba: https://core.telegram.org/bots/api#sendrichmessagedraft
- **`sendMessageDraft`** (oddiy) + `text=""` — faqat BO'SH matn bilan native
  logo chiqadi; istalgan matn berilsa logo yo'qolib, oddiy yuborilgan
  xabarga aylanadi (buni foydalanuvchi bilan birga skrinshot orqali
  tasdiqladik). Manba: https://core.telegram.org/bots/api#sendmessagedraft

`core/thinking_indicator.py` shu sababli **3 bosqichli** ishlaydi (har biri
mock-test bilan tekshirilgan):
1. `send_rich_message_draft` + `<tg-thinking>kulgili ibora</tg-thinking>` —
   ENG YAXSHISI (logo + o'zimizning matn birga)
2. Ishlamasa: `send_message_draft(text="")` — logo bor, matn yo'q
3. Ikkalasi ham ishlamasa: oddiy xabar + qo'lda edit (eski usul)

Yakunlashda (`finish()`): rich draft uchun `send_rich_message` (rasmiy
hujjat tavsiyasi), qolganlarida oddiy `send_message`/`edit_message_text`.
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
- **oddiy user** — /start bosgan har kim AVTOMATIK (admin tasdig'i kerak emas), kunlik so'rov limiti bilan (standart 50/kun, `/panel` orqali o'zgartiriladi)
- **blocked** — superadmin `/panel` orqali bloklagan user, shaxsiy chatda botdan foydalana olmaydi (qayta ochish mumkin)

## Tariflar (Telegram Stars) — `core/tariffs.py`, `handlers/tariff.py`
Oylik (30 kun) obuna, to'lov bot ichida **Telegram Stars (XTR)** bilan; muddat tugagach avtomatik **Bepul** tarifga qaytadi.
Hamma tarifda fayl/hujjat yaratish va rasm o'qish bor — farq **kunlik kvotada**:

| Tarif | So'rov/kun | Fayl yaratish/kun | Rasm o'qish/kun | Story izohi (caption) | Narx (standart) |
|---|---|---|---|---|---|
| Bepul | foydalanuvchining o'z limiti (standart 20) | 4 | 2 | yo'q | — |
| Plus ⭐ | 100 | 20 | 10 | ha | 150 ⭐ |
| Pro 💎 | 300 | 100 | 70 | ha | 400 ⭐ |

- **Superadmin hammasini tahrirlaydi:** `/panel → 💳 Tariflar → ✏️ <tarif>` — narx (⭐), so'rov/kun, fayl/kun, rasm/kun; Bepul uchun fayl/kun va rasm/kun.
  O'zgarish DB'da (`db["tariff_config"]`) saqlanadi va hammaga **darhol** amal qiladi; `0` — o'sha imkoniyatni yopish; ✱ — standartdan o'zgartirilgan,
  «↩️ Standartga qaytarish» bor. Mavjud obunachilarning muddati o'zgarmaydi; yangi narx faqat yangi hisob-fakturalarga (eskisi `pre_checkout`da rad etiladi).
  Env (`TARIFF_*_STARS/LIMIT`) faqat boshlang'ich qiymat. Bepul tarifning so'rov limiti har bir foydalanuvchida alohida (Foydalanuvchilar → Limit).
- **"Fayl yaratish"** = AI tool fayl chiqarsa (docx/xlsx/pptx/pdf/html/py/csv/rasm/arxiv, taqdimot, diagramma...): har bir shunday tool chaqiruvi 1 ta.
  Faqat o'qish/qidirish tool'lari (`read_*`, `get_*`, `list_*`, `search_*`, `fetch_*`...) sanalmaydi. **"Rasm o'qish"** = `look_at_image` muvaffaqiyatli chaqiruvi.
  Xato bilan tugagan tool kvotadan ayirilmaydi. Kvota tugasa tool **umuman ishga tushmaydi** (serverda, `ai_tools.dispatch`), AI foydalanuvchiga aytadi.
  Kvota kun almashganda (Toshkent) yangilanadi. Admin va VIP chatmode — cheksiz. Guruhda kvota hisobi to'layotgan odamdan (chatmode egasi) ketadi.
- **Story:** story qo'yish tarifga bog'liq emas (hamma uchun cheksiz); faqat story **izohi (caption)** Plus/Pro (yoki admin) uchun.
  Bepul foydalanuvchi izoh yozsa, story izohsiz chiqadi va buning sababi ko'rsatiladi.
- **Eslatma:** tarif tugashiga 3 kun va 1 kun qolganda hamda tugagach (7 kun ichida) foydalanuvchiga xabar boradi — har biri bir martadan,
  uzaytirilsa yangidan hisoblanadi (fon vazifasi har 30 daqiqada, `core/scheduler.py`).
- **Buyruq yo'q (`/tarif` olib tashlangan) — hammasi inline tugmalar orqali:** `/start` menyusidagi «💳 Tariflar»; so'rov limiti yoki fayl/rasm
  kvotasi tugaganda javob tagidagi «💳 Tariflar» tugmasi (guruhda tugma deep-link `?start=tariff` bo'lib shaxsiy chatda tariflarni ochadi,
  chunki to'lov faqat shaxsiy chatda); muddat eslatmalaridagi tugma; story izohi yopiq bo'lganda ham tugma chiqadi. Tugma → tariflar sahifasi
  (bugungi sarf bilan) → Stars hisob-fakturasi → to'lov. Narx/limitlarni faqat superadmin `/panel → 💳 Tariflar` da boshqaradi.
  Limit = max(foydalanuvchining o'z limiti, tarif limiti).
- Xarid qoidalari: o'sha tarifni uzaytirish (+30 kun); yuqoriroqqa o'tish (30 kun hozirdan, qolgan kunlar kuymaydi — oldindan ogohlantiriladi);
  faol yuqori tarif ustiga pastrog'ini sotib olib bo'lmaydi. To'lov idempotent (bir xil `charge_id` ikki marta hisoblanmaydi); `pre_checkout`da narx/foydalanuvchi/valyuta tekshiriladi.
- Superadmin `/panel → 💳 Tariflar`: faol obunachilar va jami tushum; foydalanuvchi sahifasida: 🎁 qo'lda berish (30 kun), ❌ bekor qilish,
  💸 oxirgi to'lovni **refund** qilish (Telegram `refundStarPayment`) va bugungi kvota sarfi. Murojaat — pastdagi «📨 Adminga murojaat» bo'limiga qarang.
- Hozircha sanalmaydi: story izohi uchun vision (OCR/rasm tavsifi) va foydalanuvchi o'z API kalitini ulagan holatlar.

## 📨 Adminga murojaat (`handlers/support.py`)
`/start` menyusi va tariflar sahifasidagi «📨 Adminga murojaat» inline tugmasi (matnli buyruq yo'q). Bosilganda pastda
reply-klaviatura chiqadi: **«✅ Yuborish» / «❌ Bekor qilish»**. Foydalanuvchi istalgancha xabar yozadi — matn, rasm, video, stiker, GIF, ovozli,
fayl, emoji — **har biri alohida xabar** bo'lib saqlanadi, lekin hech qayerga ketmaydi. Faqat «✅ Yuborish» bosilganda hammasi (har biri alohida,
o'z turida, `copy_message`) superadminga boradi; oldidan sarlavha (kim, tarifi, nechta xabar) va «✉️ Javob yozish» tugmasi (`/panel` xabar yozish oqimi).
- Sessiya xotirada: 30 daqiqa harakatsizlikdan keyin tugaydi; 20 tagacha xabar; soatiga 5 ta murojaat; bloklanganlar yoza olmaydi.
- Sessiya paytida komanda (masalan `/start`) yozilsa — murojaat bekor bo'ladi va komanda odatdagidek bajariladi. Adminga yetkazib bo'lmasa sessiya saqlanadi (qayta «Yuborish» mumkin).
- `/paysupport` (Telegram to'lov qabul qiladigan botdan talab qiladi) faqat shu tugmani ochadi; matn argumenti yo'q.

## Noto'g'ri yozilgan komandalar (`core/command_guard.py`)
Hech bir handler'ga mos kelmagan komanda ("/vipchaatmode: on") avval AI'ga tushib, u "VIP yoqildi" deb **yolg'on** yozardi. Endi harf xatosi bo'lsa
to'g'ri komanda taklif qilinadi va AI'ga yuborilmaydi; taklif faqat foydalanuvchi o'zi ishlata oladigan komandalardan (superadminga xos `/vipchatmode`
oddiy userga ko'rsatilmaydi; oddiy userga u hamon jim). Boshqa botga mo'ljallangan (`/cmd@BoshqaBot`) komandalar jim yutiladi; hech narsaga o'xshamagan
`/help` kabilar avvalgidek tegilmaydi. AI tizim ko'rsatmasiga ham "sozlamalarni o'zgartira olmaysiz, bajarilmagan amalni bajarilgan demang" qoidasi qo'shilgan.

## Adminlarni boshqarish (`/panel → 🛡 Adminlar`, faqat superadmin)
Har bir admin inline tugma (ism/@username va ID). Ustiga bosilsa: **1)** «Adminni olib tashlaysizmi?» → «⚠️ Ha, davom etish» → **2)** «OXIRGI TASDIQ» →
«🗑 Ha, adminni o'chirish». Ikkala tasdiq ham serverda majburlanadi (faqat shu admin uchun, ketma-ket, 2 daqiqa ichida, bir martalik) — eski xabardagi
tugmani qayta bosish yoki bosqichni o'tkazib yuborish ishlamaydi. O'chirilgan adminning shaxsiy `/` menyusidan `/panel` olib tashlanadi va moderatsiya
keshidagi eski huquqi tozalanadi. «❌ Yo'q» tugmalari hech narsani o'zgartirmaydi. Ismi saqlanmagan adminlar uchun ism Telegram'dan olinib eslab qolinadi.

## Panel orqali xabar yuborish (`core/admin_messaging.py`)
- **Bitta foydalanuvchiga** (superadmin va adminlar): `/panel → Foydalanuvchilar → <user> → ✉️ Xabar yozish`, so'ng matnni yozasiz.
  Xabar jo'natuvchi nomisiz, "📩 Admin xabari" sifatida boradi (panel superadmin identligini adminlardan yashirgani uchun).
  Oddiy adminlarga soatiga 30 ta xabar limiti bor, superadminga yo'q.
- **Hammaga (broadcast)** — FAQAT superadmin: `/panel → 📢 Hammaga xabar`. Matn yoziladi → ko'rinishi va qabul qiluvchilar soni
  ko'rsatiladi → «✅ Yuborish» bosilgandagina ketadi (ikki marta bosish qayta yubormaydi). Bloklanganlar va o'zingiz chiqarib tashlanadi;
  ~16 xabar/s, FloodWait'da kutib 1 marta qayta uriniladi, bir vaqtda faqat bitta broadcast. Oxirida hisobot keladi
  (yetkazildi/yetkazilmadi va sabablari — botni bloklaganlar yoki hech qachon /start bosmaganlar).
  Ruxsat serverda ham tekshiriladi: admin tugmani/callback'ni qo'lda yuborsa ham broadcast ishlamaydi.
- Matn HTML-escape qilinadi (admin yozgan `<`, `&` aynan o'zi ko'rinadi). Hozircha faqat matn (rasm/fayl yo'q). `/panel` yarim qolgan oqimni bekor qiladi.

## Yangilanish: debounced DB yozish (StokerDownloader patterni)
`core/tgdb.py` endi har `save()` chaqiruvida darhol Telegram'ga yozmaydi —
faqat "dirty" belgisini qo'yadi, background task har 5 soniyada bittalab
flush qiladi. Kritik amallar (session saqlash, premium/ruxsat berish) uchun
`tgdb.save(bot, force=True)` chaqiring — darhol yoziladi.

## ms-file-toolkit v0.6.0 — nima yangi va nima kerak edi
82 ta tool orasida eng muhimlari: **`search_web`** (internet qidiruv),
**`fetch_url_text`**/**`scrape_page_text`** (sahifa o'qish), **`download_file`**,
`read_image_text` (OCR — rasmdagi matnni o'qiydi), rasm tahrirlash
(crop/resize/rotate/convert), arxiv (zip) yaratish/o'qish, kod fayllar bilan
ishlash (yaratish/o'qish/tahrirlash/qidirish), OpenDocument formatlar.

**Yangilashda 2 ta muammo topilib tuzatildi:**
1. `Dockerfile`da faqat `libreoffice-impress` bor edi — `convert_docx_to_pdf`/
   `convert_xlsx_to_pdf` kabi funksiyalar ishlamas edi (test qilib aniqlandi).
   Endi `libreoffice-writer` + `libreoffice-calc` ham qo'shildi.
2. `read_image_text` (OCR) uchun tizim darajasidagi `tesseract-ocr` kerak —
   Dockerfile'ga qo'shildi (avval umuman yo'q edi).
3. Yangi `dir_path` parametri (`list_directory_files`, `search_in_files`)
   bizning xavfsizlik-normalizatsiyamizda yo'q edi — qo'shildi va
   path-traversal urinishi bilan test qilindi (xavfsiz qoldi).

## Fayl generatsiyasi qanday ishlaydi
Foydalanuvchi "menga hisobot yoz" desa, AI `create_docx`/`create_xlsx`/... tool'ini
chaqiradi, natija `data/user_files/<user_id>/` papkasida yaratiladi va bot uni
avtomatik hujjat sifatida yuboradi (`handlers/ai_chat.py`). `file_path` sifatida
AI qanday nom bersa ham, xavfsizlik uchun har doim foydalanuvchining o'z papkasi
ichiga normalizatsiya qilinadi (`tools/file_tools.py`).

## Guruhda bot bilan ishlash — qoidalari
Botni guruhga admin qilmasdan ham qo'shsa bo'ladi (admin huquqi faqat
pin/o'chirish/cheklash kabi moderatsiya amallari uchun kerak).

**Murojaat qilishning FAQAT 2 ta yo'li** (`handlers/ai_chat.py`, kod
darajasida qat'iy cheklangan — Group Privacy sozlamasiga tayanmaydi):
1. Botni **tag qilish**: `@BotUsername savolingiz`
2. Botning **o'z xabariga reply** qilish

Boshqa har qanday oddiy xabar botga umuman yetib bormaydi/e'tiborsiz
qoldiriladi. Tag qilinganda `@BotUsername` matndan avtomatik olib
tashlanadi (AI'ga toza savol boradi).

**Limit — kim yozsa, o'shaning hisobidan ketadi:** guruhda ham, shaxsiy
chatda ham BITTA UMUMIY kunlik limit ishlatiladi (chat bo'yicha emas,
foydalanuvchi bo'yicha). **Guruhda foydalanish uchun global tasdiqlash
(admin `/panel` orqali tasdiqlashi) SHART EMAS** — kimdir birinchi marta
guruhda botga yozganda, standart 20/kun limit bilan avtomatik
ro'yxatga olinadi. Shaxsiy chatda esa avvalgidek tasdiqlash talab qilinadi.

**Standart kunlik limit: 50 dan 20 ga tushirildi** (`DEFAULT_DAILY_LIMIT`).

**Fayl/prezentatsiya/diagramma yaratish — 3x qimmat** (`FILE_GENERATION_WEIGHT`),
guruhda ham, shaxsiy chatda ham bir xil qoida bilan.

Qo'shimcha: **shu GURUHNING Telegram-admini/egasi** (bizning superadmin/admin
tizimimizdan mustaqil) quyidagi komanda bilan botni faqat tanlangan
odamlarga javob beradigan qilib **yana ham** cheklashi mumkin:
```
/guruh_ruxsat @mira @ali @MuslihiddinDev
```
Ro'yxatda YO'Q odamlar yozsa, bot butunlay jim qoladi. Bekor qilish:
`/guruh_ruxsat_ochirish`.

Barchasi test qilindi: limit=20, guruhda tasdiqlashsiz avtomatik kvota,
20-so'rovdan keyin bloklanish, fayl-generatsiya 3x hisoblanishi, tag/reply
aniqlash va matn tozalash (katta-kichik harf farqisiz).

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
## Userbot (faqat o'qiydi, IXTIYORIY)
Eski ko'p-akkauntli userbot (`/userbot`, `/kalitsoz_qoshish`, `/away`) olib tashlangan. Uning o'rniga **bitta, egasining o'z
(ishlatilmaydigan) akkaunti** bilan ishlaydigan, faqat o'qiydigan modul bor (`core/userbot.py`, `core/userbot_tools.py`).
Session DB'da emas, faqat ENV'da turadi (`core/legacy_cleanup.py` DB'dagi eski sessiyalarni baribir tozalab turadi).

**Yoqish:** `python gen_userbot_session.py` (lokalda) → Render env'ga `USERBOT_API_ID`, `USERBOT_API_HASH`, `USERBOT_SESSION`.
Uchalasi bo'lmasa funksiya o'chiq, bot odatdagidek ishlaydi. Akkaunt kerakli guruh(lar)ga a'zo bo'lishi kerak.

**AI nima qila oladi:** guruh a'zolari ro'yxati (admin bo'lmaganlar ham; uzun bo'lsa .txt fayl), profil (ism/username/bio/shaxsiy kanal),
profil rasmlarini yuklab shu chatga yuborish, story'larni (faol + mahkamlangan) yuklab yuborish, ochiq kanal postlarini o'qish.
Story egasiga "ko'rildi" bildirilmaydi. Telegram maxfiligi (yopiq bio/story, yashirin a'zolar) o'z-o'zidan amal qiladi.

**Sozlamalar:** `USERBOT_ACCESS=all|admins` (standart `all`: hamma so'rashi mumkin; `admins`: faqat bot/guruh adminlari),
`USERBOT_RATE_PER_HOUR=15` (oddiy foydalanuvchi uchun soatlik limit; adminlarga tegmaydi).

**Muhim:** (1) shu session'ni boshqa joyda bir vaqtda ishlatmang — Telegram uni bekor qiladi (AUTH_KEY_DUPLICATED); shunda funksiya
o'zini o'chiradi, bot ishlashda davom etadi. (2) Render zero-downtime deploy paytida eski va yangi nusxa ozgina vaqt birga ishlashi mumkin
— shunda ham shu xato chiqishi mumkin; kerak bo'lsa qayta deploy qiling. (3) Telegram'ni ommaviy yig'ish uchun ishlatmang: akkaunt limitga/ban'ga tushishi mumkin.
Testlar: `pip install pytest && pytest tests`.

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

## Guruh chat rejimi va limitlar
- `/chatmode on|off` — **kim qila oladi:** guruh egasi/adminlari (Telegram), botning adminlari, superadmin. Boshqalarga ruxsat yo'q.
  Yoqilgan guruhda bot HAR BIR xabarga javob beradi. **Hisob tartibi:** 1) rejimni yoqqan odamning kunlik limiti → 2) u tugasa, xabar yozgan odamning o'z limiti → 3) ikkalasi ham tugasa javob yo'q.
  (Rejimni yoqqan odam superadmin/bot admini bo'lsa ham, chatmode so'rovlari uning kunlik hisobidan ketadi — ularning limiti `ADMIN_DAILY_LIMIT` (standart **100/kun**, `.env` orqali o'zgartiriladi).)
- `/vipchatmode on|off` — **faqat superadmin.** Shu guruhda CHEKSIZ: hech kimning limiti tekshirilmaydi ham, hisoblanmaydi ham. VIP rejimni faqat superadmin o'zgartira/o'chira oladi.
- Fayl/prezentatsiya/diagramma yaratish har doim 3x hisoblanadi.

## Profilga AI sifatida ulash va Story qo'yish (Telegram Business)
Bot foydalanuvchining profiliga "chatbot" sifatida ulanadi va (Bot API 9.0 `postStory` orqali) uning nomidan **story** qo'yadi.
- **Ulash (foydalanuvchi tomonida):** Telegram Premium kerak → Sozlamalar → Hisob → Chatlarni avtomatlashtirish → botni qo'shish → ruxsatlardan **story'larni boshqarish**ni yoqish. Bot `business_connection` update'ini olib, ulanishni saqlaydi (`core/stories.py`).
- **Menyu:** `/start` (yoki `/profil`) → 👤 Profil boshqaruvi → 📸 Story qo'yish → rasm/video yuboriladi (izoh = story matni) → muddat (6/12/24/48 soat) → joylanadi; keyin «🗑 O'chirish» tugmasi chiqadi.
- **AI orqali:** rasm/video yuborib «buni storyimga qo'y» deyish mumkin (`post_story` tool). Story ommaviy amal bo'lgani uchun AI uni faqat foydalanuvchi aniq so'raganda chaqiradi.
- **Formatlash:** rasm → 1080×1920 (xiralashtirilgan fon bilan), video → 720×1280 H.265/AAC, har soniyada key frame, ≤30 MB, ≤60 soniya (serverda **ffmpeg** kerak — Dockerfile'ga qo'shilgan).
- **Cheklovlar:** bot faqat ≤20 MB fayllarni yuklab ola oladi (Bot API chegarasi); video qayta ishlash serverning CPU'siga bog'liq (sekin bo'lishi mumkin).

## 👁 Rasm o'qish (vision) kalitlari — chatdan alohida
`/panel → 🔑 AI kalitlar` endi ikki bo'limga ega:
- **💬 Chat kalitlari** — oddiy suhbat uchun. Avval kiritilgan barcha kalitlar shu yerda qoladi (o'zgarmagan).
- **👁 Rasm o'qish kalitlari** — rasm/videoni «ko'rish» uchun alohida to'plam (DB'da `vision_keys`). Provayderlar: Groq, Gemini, xKiro, OpenAI, Anthropic (DeepSeek'da rasm API'si yo'q).
- **Groq kaliti rasm uchun avtomatik vision modeliga yo'naltiriladi** (chat modeli `llama-3.3-70b` rasm qabul qilmaydi): standart `meta-llama/llama-4-scout-17b-16e-instruct`; model eskirsa zaxira nomzodlarga o'tadi va Groq model ro'yxatidan o'zi topadi. Model nomini panelda o'zgartirish mumkin (🧠), o'zgartirgach mavjud kalit bilan darrov sinaladi.
- Kalit qo'shishda u kichik test rasm bilan HAQIQIY so'rovda tekshiriladi.
- **xKiro:** qaysi modellar rasm qabul qilishi noma'lum — avval `🧠 Modelni o'zgartirish` bilan vision modelini kiriting.
- Ishlatilishi: (1) story izohi — AI media tavsifini ko'rib yozadi; (2) suhbatda AI `look_at_image` tool orqali foydalanuvchi yuborgan rasm/videoni ko'radi (video uchun 3 ta kadr, ffmpeg).

## Moderatsiya: aniq buyruqlar va tekshiruv
- **AI'siz yo'l** (`core/mod_commands.py`): `mute ber`, `14 daqiqaga mute`, `ban qil`, `kick`/`hayda`, `unmute`, `unban` kabi aniq buyruqlar kodda aniqlanadi — nishon (text_mention → `@username` → reply → ismi aytilgan yagona a'zo), muddat (`core/duration.py`) va amal — AI'siz, limit sarflamasdan, limiti tugagan admin ham ishlata oladi. Savol, inkor ("mute qilma") va o'tgan zamon ("qildim") buyruq hisoblanmaydi — ular AI'ga ketadi. Faqat guruh admini (yoki bot admini/superadmin) uchun.
- **Har bir amal tekshiriladi** (`core/moderation.py`): bajarishdan oldin botning o'z huquqi («A'zolarni cheklash») va nishon (admin/egasi/guruhda yo'q); bajarilgandan keyin natija `get_chat_member` bilan qayta o'qib TASDIQLANADI. Telegram "ok" desa-yu amal qo'llanmasa, bot buni ochiq aytadi.
- **Qo'riqchi:** AI "mute qildim" deb yozsa-yu, hech bir moderatsiya tool'i muvaffaqiyatli bajarilmagan bo'lsa, yolg'on javob o'rniga ogohlantirish yuboriladi.
- Cheklash faqat **supergroup**'da ishlaydi; bot admin bo'lishi va «Restrict members» huquqiga ega bo'lishi shart.

## Yangi guruh imkoniyatlari
- **Shaxsiyat:** AI endi "Paradoks AI" sifatida tanishadi, botning egasini doim "aka" deb chaqiradi (`core/ai_persona.py`).
- **Taxalluslar (`/laqab`):** har bir foydalanuvchi o'z taxallusini o'rnatadi/o'chiradi; guruh xabarlarida va AI kontekstida ism o'rniga shu ishlatiladi (`core/nicknames.py`).
  **Avtomatik taxallus:** foydalanuvchi chatda "meni Mocci opa deb chaqir" desa va `/laqab` ishlatmagan bo'lsa, AI `set_my_nickname`
  orqali uni **hamma guruhda** ishlatiladigan taxallus qilib saqlaydi (`db["auto_nicknames"]`). `/laqab` bilan o'rnatilgani doim ustun;
  `/laqab -o'chir` ikkalasini ham o'chiradi. Reklama bo'lib ketmasligi uchun server tomonida qattiq filtr (`validate_auto`):
  eng ko'pi 24 belgi va 3 so'z, faqat harflar (havola, @, emoji, `_`, 2 tadan ko'p raqam yo'q), reklama/tijorat so'zlari
  (kripto, kazino, shop, obuna, kanal...) va admin/bot/rasmiy/support/bot nomiga o'xshash so'zlar rad etiladi, kuniga 3 martadan
  ko'p almashtirib bo'lmaydi. Laqabni faqat gapirgan odamning o'zi uchun qo'yish mumkin (tool'da boshqa odamni ko'rsatish parametri yo'q). ID 8054272729 standart holatda "Omirbayev aka" bilan boshlanadi (o'zi o'zgartira oladi).
- **Taqiqlangan so'zlar:** `/taqiq_qoshish`, `/taqiq_ochir`, `/taqiqlar` (admin). So'z uchrasa, xabar avtomatik o'chiriladi (guruh/bot adminlari TEKSHIRILMAYDI). Standart ro'yxatda "dnx" bor (`core/banned_words.py`).
- **Guruh qoidalari ("algoritm prompt"):** `/qoida_qoshish`, `/qoidalar`, `/qoida_ochir` (admin) — erkin matnli ko'rsatmalar AI'ning shu guruhdagi system prompt'iga doimiy qo'shiladi (`core/group_rules.py`).
- **Statistika:** `/statistika` — bot kuzatgan xabarlar soni va eng faol 5 a'zo (hammaga ochiq).
- **`/top_faollar`** (admin): bot **o'zi kuzatgan** (tag/reply/chatmode orqali ko'rgan) eng faol a'zolarni BITTA xabarda (20 tadan ko'p bo'lsa, bir nechta xabarda) tag qiladi. Bu guruhning BARCHA a'zosini emas, faqat faol/kuzatilganlarni qamraydi — session/userbot kerak emas.
- **Foydalanuvchi ma'lumoti va reaksiya:** `get_user_profile`/`lookup_user` tool'lari (username/ism/bio, admin uchun qidiruv) va yangi `react_to_message` tool (AI xabarga emoji bilan reaksiya qo'yadi) allaqachon mavjud edi/qo'shildi.

## Qo'shimcha guruh vositalari (2-bosqich)
- **VIP chatmode tuzatildi:** avval guruhga rasm/video yuborilganda `/vipchatmode`/`/chatmode`ning hisob-kitob mantig'i butunlay chetlab o'tilardi (rasm oddiy kunlik limitga tushib qolardi). Endi matn kabi to'g'ri ishlaydi.
- **GLOBAL qora ro'yxat** — FAQAT superadmin, `/panel → 🌐 Global qora ro'yxat` (inline tugmalar, komanda emas) — barcha guruhlarda birdek ishlaydi, so'z uchrasa xabar o'chadi; 3-marta buzilsa 60 daqiqaga mute, 5-marta — ban (24 soatlik oyna). Har guruhning o'z `/taqiq_*` ro'yxati bilan birga ishlaydi.
- **`/aireakmode: on|off`** — yoqilsa, bot mavzuga mos xabarlarga (javob yozmasdan) emoji bilan reaksiya qo'yadi; neytral/qisqa xabarlarga tegmaydi.
- **`/antispam on|off`** — flood nazorati: 8 soniyada 6+ xabar yoki bir xil xabarni 5+ marta takrorlash — avtomatik 10 daqiqaga mute.
- **`/statistika`** endi FAQAT guruh/bot adminlari va superadmin uchun ishlaydi (boshqalarga ruxsat yo'q xabari).
- **Kunlik avtomatik yuborish** (`core/scheduler.py`, har daqiqa tekshiradi, Toshkent vaqti, soat 20:00): admin AI'ga oddiy gap bilan ("har kuni eng faol userlarni tag qil") aytadi — AI `set_daily_top_active` tool orqali yoqadi/o'chiradi, alohida komanda yo'q.

## Guruh xotirasini butunlay tozalash
Admin AI'ga "hammasini unut", "guruh xotirasini tozala" kabi aniq aytsa, `wipe_group_memory` tool chaqiriladi.
Faqat SHU guruhga ta'sir qiladi, boshqa guruh va foydalanuvchilarning global ma'lumotiga (rol/limit, shaxsiy chat
eslatmalari, `/laqab` taxallusi) tegilmaydi. O'chirishdan OLDIN eski ma'lumotlar `.txt` fayl qilib guruhga yuboriladi (zaxira).

- **Xotira tozalash (standart):** suhbat jurnali/xulosasi, a'zolar indeksi, xabar statistikasi va guruhda aytilgan
  eslatmalar ("meni ... deb chaqir") DB'dan **haqiqatan o'chiriladi** + jarayon xotirasidagi keshlar tozalanadi.
  Admin sozlamalari (taqiqlangan so'zlar, qoidalar, chatmode/VIP, anti-spam...) saqlanadi.
- **To'liq reset (`full_reset`):** "to'liq reset", "sozlamalari bilan hammasini", "guruh yangi qo'shilgandek bo'lsin"
  deyilsa — yuqoridagilar + admin sozlamalari, ogohlantirishlar, blacklist strike'lar, kanal yozuvi ham o'chadi
  (zaxira faylga sozlamalar ham yoziladi). Faqat bot adminlari va guruh egasi uchun.

Tozalangan navbatda AI eski kontekst bilan javob yozmaydi (tayyor matn yuboriladi) va yangi bo'sh logga hech narsa yozilmaydi.
