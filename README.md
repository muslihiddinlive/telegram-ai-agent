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
## Userbot olib tashlangan
Telethon asosidagi userbot (`/userbot`, `/kalitsoz_qoshish`, `/kalitsozlar`, `/away`) **butunlay olib tashlandi** —
Telegram session string hisobga to'liq kirish huquqi beradi, bu xavfli. Profilga ulash endi FAQAT Telegram'ning
rasmiy yo'li bilan: **Sozlamalar → Hisob → Chatlarni avtomatlashtirish** (Business chatbot), qarang «Profilga AI sifatida ulash».
Ishga tushganda `core/legacy_cleanup.py` eski sessiya ma'lumotlarini (`telegram_session`, `api_id`, `api_hash`) DB'dan o'chiradi
(shaxsiy AI API kalitlariga tegmaydi).

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
