# Export hujjatlarini avtomatik yuborish boti (v2 — Partiya + Deklaratsiya tizimi)

## Hujjat komplekti va nomlash tartibi

Bot **7 ta hujjat** to'planmaguncha pochtaga hech narsa yubormaydi:

| Tur | Nima |
|---|---|
| `INV` | Invoys |
| `SPETS` | Spetsifikatsiya |
| `ST` | Sertifikat |
| `FITO` | Fitosanitariya (`FIT` deb yozilsa ham tushunadi) |
| `AKT` | Akt |
| `CMR` | CMR |
| `TIR` | TIR |

### Guruhga tashlash tartibi (masalan `NGS-25`, fura raqami `565`)

**1. Invoys guruhi:**
```
NGS-25 GALLAKTIKA ZAPIT 565.xlsx
NGS25INV.pdf
NGS25SPETS.pdf
```

**2. Skaner qilingan hujjatlar (albom qilib tashlansa ham bo'ladi):**
```
NGS-25 ST 565.jpg     NGS-25 FITO 565.jpg    NGS-25 AKT 565.jpg
NGS-25 CMR 565.jpg    NGS-25 TIR 565.jpg
```

**3. Yakuniy deklaratsiya:**
```
NGS-25.pdf     ← shundan keyin hujjatlar pochtaga ketadi
```

Oxirgi raqam (`565`) — **fura raqami**. Invoysdagi raqam eslab qolinadi va
keyingi hujjatlar shu bilan solishtiriladi.

### Bot guruhda nima yozadi

| Holat | Xabar |
|---|---|
| Oddiy hujjat kelsa | **Hech narsa** — bot jimgina yig'ib boradi |
| Komplekt to'liq | Ortiqcha gap yo'q — faqat yakuniy `✅ "NGS-11" — pochtaga yuborildi` + guruhlangan fayllar ro'yxati |
| Komplekt to'liq emas | `🛑 YUBORILMADI, komplekt to'liq emas [5/7]` + yetishmaganlar ro'yxati + **⚠️ Baribir yuborilsin / ⏳ Kutamiz** tugmalari |
| Fayl nomi xato | `⚠️ fura raqami invoysdagidan FARQ QILADI` / `⚠️ fura raqami yozilmagan` |
| Turi tanilmagan fayl | `ℹ️ Bu fayl(lar) hisobga OLINMADI` |
| Allaqachon yuborilgan fayl qayta tashlandi | `♻️ bu hujjat(lar) ALLAQACHON yuborilgan` + **✅ HA / ❌ YO'Q** tugmalari |

Bot hujjatlarni **jimgina** yig'ib boradi — guruhga xabar faqat deklaratsiya
kelganda yoki haqiqiy muammo bo'lganda yoziladi.
Tugmalarga guruh a'zolari javob bera oladi — admin bo'lish shart emas.

Xatga fayllar tartib bilan biriktiriladi: avval `xlsx → INV → SPETS`,
keyin `ST → FITO → AKT → CMR → TIR`, oxirida deklaratsiya.

### Hodim fayl nomini xato yozsa

| Xato | Bot nima qiladi |
|---|---|
| `NGS 25 TIR.jpg` (fura raqamisiz) | Qabul qiladi + ogohlantiradi, to'g'ri ko'rinishni ko'rsatadi |
| `NGS-25 CMR 999.jpg` (boshqa fura) | Qabul qiladi + "invoysdagidan farq qiladi" deb ogohlantiradi |
| `NGS-25 haydovchi.jpg` (turi noma'lum) | **Qabul qilmaydi** — yuklab ham olmaydi, mijozga ketmaydi. Guruhda bir marta ogohlantiradi |
| `NGS 25 FIT 269.JPG` | To'g'ri tushunadi (`FIT` = `FITO`) |
| Kodi umuman yo'q (`photo_2026-05-05.jpg`) | Butunlay e'tiborsiz qoldiradi |

### Begona fayllar mijozga ketmaydi

Guruhga chek, pasport nusxasi, haydovchi rasmi, oddiy suhbat rasmlari ham
tashlanadi. Bot **faqat tanilgan turdagi** hujjatlarni oladi:

`INV`, `SPETS`, `ST`, `FITO`, `AKT`, `CMR`, `TIR`, invoys `.xlsx` va deklaratsiya.

Boshqa har qanday fayl — hatto nomida partiya kodi bo'lsa ham (`NGS-25 chek 565.jpg`) —
**yuklab olinmaydi va xatga qo'shilmaydi**. Guruhda bitta qisqa xabar chiqadi:

```
ℹ️ Bu fayl(lar) hisobga OLINMADI — hujjat turi tanilmadi:
   • NGS-25 chek 565.jpg
Agar bu kerakli hujjat bo'lsa, to'g'ri nom bilan qayta tashlang:
   NGS-25 ST 565.jpg
```

Yuborish paytida ham ikkinchi marta tekshiriladi — eski partiyalarda qolib
ketgan begona fayl ham mijozga ketmaydi.

## Yangi ishlash mantig'i

Avvalgi versiyada har bir fayl kelganda darhol emailga yuborilardi. Endi:

1. Guruhga tashlangan hujjatlar **yig'ib boriladi** (hech narsa darhol yuborilmaydi)
2. **Deklaratsiya** fayli kelgach (kod nomli PDF, masalan `N-O-336.pdf` yoki `NG-23.pdf` —
   fayl nomida kod dan boshqa hech narsa yo'q), o'sha partiyaning **BARCHA** hujjatlari
   **bitta xatga ilova qilinib**, mijoz emailiga yuboriladi

### Qanday aniqlanadi — deklaratsiya yoki oddiy hujjat?

Fayl nomi **faqat kod**dan iborat bo'lsa (bo'sh joy, chiziqcha hisobga olinmaydi) VA
**PDF** formatida bo'lsa — bu deklaratsiya:

| Fayl | Deklaratsiyami? |
|---|---|
| `N-O-336 VIZOR STEP-ORC 567.xlsx` | ❌ yo'q (qo'shimcha matn bor) |
| `NO336INV.pdf` | ❌ yo'q (INV qo'shimchasi bor) |
| `N-O-336.pdf` | ✅ **HA** — hammasi yuboriladi |
| `NG-23 .xlsx` | ❌ yo'q (PDF emas) |
| `NG-23.pdf` | ✅ **HA** |

## Mijozni aniqlash — 3 usul (tartib bo'yicha tekshiriladi)

1. **Fayl nomidagi kompaniya nomi** — masalan fayl nomida "BMB GROUP" bo'lsa
2. **Kod-prefiks** — masalan barcha `NG-...` kodlar avtomatik bitta mijozga bog'langan bo'lsa
   (`/prefix_add NG | MIJOZ_NOMI` orqali sozlanadi)
3. **Eslab qolingan kod** — agar shu partiyaning bir fayli allaqachon mijozni aniqlagan bo'lsa

### Hujjat turi kod bilan chalkashmaydi

Fayl nomi odatda `AKT NG-1 SARBON-GALAKTIKA 384.JPG` ko'rinishida bo'ladi —
ya'ni oldida hujjat turi (AKT, CMR, FIT, INV, ST, TIR) turadi. Bot kodni
faqat **alohida so'z** sifatida qidiradi, shuning uchun bunday fayl `NG-1`
partiyasiga tushadi (avval xato ravishda `KTNG1` degan soxta partiya ochilardi).

## Fayllar

- `bot.py` — asosiy bot
- `customer_store.py` — mijozlar bazasi (nom, emaillar, prefikslar)
- `batch_store.py` — partiya fayllarini yig'ib turish
- `session_store.py` — fayl nomini tahlil qilish (kod, deklaratsiya, prefiks) va kod->mijoz xotirasi
- `unmatched_store.py` — mijozi aniqlanmagan fayllarni saqlab turish
- `storage.py` — JSON fayllarni xavfsiz (atomar) o'qish/yozish
- `gmail_sender.py` — Gmail SMTP orqali ko'p-fayl/ko'p-manzil xat yuborish
- `config.py` — bot token, guruh ID, admin ID, Gmail manzili va ilova paroli
- `backup_2026-09-01_docs/` — eski hujjatlarning zaxira nusxasi (kerak bo'lmasa o'chiring)

## O'rnatish

### 1. Kutubxonalar
```
pip install -r requirements.txt
```

### 2. Telegram bot yaratish
**@BotFather** ga yozing, `/newbot`, tokenni `config.py` dagi `BOT_TOKEN` ga qo'ying.

### 3. Gmail ruxsati — ilova paroli (App password)

Bot xatlarni **Gmail SMTP** orqali yuboradi. Google Cloud, OAuth, `token.json` —
hech biri kerak emas.

1. **2 bosqichli tasdiqlashni yoqing:**
   https://myaccount.google.com/signinoptions/twosv
   (usiz ilova paroli yaratib bo'lmaydi)
2. **Ilova paroli yarating:**
   https://myaccount.google.com/apppasswords
   Nom sifatida masalan `export bot` yozing. Google **16 belgili** parol beradi
   (masalan `abcd efgh ijkl mnop`).
3. **`config.py` ga yozing:**
   ```python
   GMAIL_ADDRESS      = "sizning.pochta@gmail.com"
   GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"   # probellar bilan ham bo'ladi
   ```
4. **Tekshiring:** botga shaxsiy chatda `/gmail_check` yozing → ✅ chiqishi kerak.

> **Nega OAuth emas?** Google "Testing" holatidagi OAuth ilovalariga refresh
> token'ni atigi **7 kunga** beradi — shu sabab bot har hafta `invalid_grant`
> xatoligi bilan xat yubora olmay qolardi. Ilova paroli esa **muddatsiz**:
> siz o'zingiz bekor qilmaguningizcha ishlayveradi.
>
> Bot ruxsat holatini har 6 soatda o'zi tekshiradi va muammo bo'lsa admin'ga
> darhol xabar beradi — hujjatlar to'planib qolishini kutmasdan.

> ⚠️ Ilova paroli — parol kabi maxfiy. `config.py` ni hech kimga bermang.
> Xavfsizroq yo'l — muhit o'zgaruvchisi (pastdagi bo'limga qarang).
> Bekor qilish/yangilash: o'sha `apppasswords` sahifasidan.

OAuth bilan bog'liq eski fayllar (`token.json`, `credentials.json`,
`gmail_auth_setup.py`) va `google-*` kutubxonalari olib tashlangan —
bot faqat Python'ning o'z `smtplib` moduli bilan ishlaydi.

### 4. Guruhga qo'shish
Botni guruhga qo'shing. **Muhim:** @BotFather'da `/setprivacy` -> `Disable` qiling —
aks holda bot guruhdagi fayllarni ko'ra olmaydi.

### 5. O'zingizni admin qilib belgilash
1. `python bot.py` bilan botni ishga tushiring
2. Botga **shaxsiy xabar** yozib, `/myid` deb yuboring — u sizga ID beradi
3. Shu raqamni `config.py` dagi `ADMIN_USER_ID` ga qo'ying
4. Botni qayta ishga tushiring

Shundan keyin botga `/start` yozing — tugmali menyu chiqadi, deyarli barcha
boshqaruvni matn yozmasdan, tugmalar orqali bajarish mumkin bo'ladi.

### 6. Guruh ID (ixtiyoriy)
Guruhda `/chatid` yozing, natijani `config.py` dagi `GROUP_CHAT_ID` ga qo'ying.

## Boshlang'ich mijozlar

Birinchi ishga tushganda avtomatik qo'shiladi:
- **SARBON** — galaxy@gmail.com, edwdw@mail.ru
- **BMB GROUP** — bmb23@mail.ru

## Tugmali menyu (/start)

Botga shaxsiy `/start` yozing — quyidagi menyu chiqadi:

```
👥 Mijozlar     📦 Partiyalar
❓ Noaniq fayllar   ℹ️ Yordam
```

Har bir bo'lim ichida kerakli amal tugma orqali bajariladi:
- **Mijozlar**: qo'shish (nom+email so'raladi), ro'yxat, o'chirish (tugmadan tanlanadi),
  alias qo'shish, prefiks bog'lash — hammasi tugma bosish + kerak bo'lganda bitta matn yozish
- **Partiyalar**: ro'yxat (kutish vaqti bilan), mijoz belgilash (ikkala tomon ham
  tugmadan tanlanadi — kod yozish shart emas), qo'lda yuborish, bekor qilish
- **Noaniq fayllar**: ro'yxat, partiyaga biriktirish (fayl va partiya ikkalasi ham tugmadan)

Eski matn buyruqlar (`/customer_add`, `/batch_send` va h.k.) ham ishlayveradi —
kimga qulay bo'lsa, shundan foydalanadi.

## Buyruqlar (botning shaxsiy chatida)

```
/customer_add SARBON | galaxy@gmail.com, edwdw@mail.ru
/customer_add VIZOR STEP-ORC | vizor@example.com
/customer_remove BMB GROUP
/customer_list
/customer_alias VIZOR STEP-ORC | VIZOR STEPORC, VIZOR   <- muqobil nomlar

/prefix_add NG | SARBON          <- endi barcha "NG-..." kodlar SARBON'ga boradi
/prefix_add NO | VIZOR STEP-ORC
/prefix_remove NG

/batches                          <- kutilayotgan partiyalar
/batch_assign NO336 | VIZOR STEP-ORC   <- mijoz aniqlanmagan partiyaga qo'lda belgilash
/batch_send NO336                 <- deklaratsiyani kutmasdan qo'lda yuborish
/batch_cancel NO336                <- partiyani bekor qilish

/unmatched                         <- mijozi aniqlanmagan fayllar ro'yxati
/batch_attach NO336 | u1           <- noaniq faylni partiyaga qo'lda biriktirish
/unmatched_delete u1               <- keraksiz noaniq faylni o'chirish

/status                            <- bot va sozlamalar holati (diagnostika)
/gmail_check                       <- Gmail ruxsati ishlayaptimi, tekshirish
/myid                              <- o'z Telegram ID ingizni bilish
/chatid                            <- guruh ID sini bilish (guruhda yoziladi)
/help                              <- barcha buyruqlar
```

## Sozlamalarni maxfiy saqlash (tavsiya etiladi)

`config.py` dagi qiymatlarni muhit o'zgaruvchilari orqali berish mumkin —
shunda token kod ichida yozilmaydi:

```
$env:BOT_TOKEN = "..."
$env:GROUP_CHAT_ID = "-1001234567890"
$env:ADMIN_USER_ID = "123456789"
$env:GMAIL_ADDRESS = "sizning.pochta@gmail.com"
$env:GMAIL_APP_PASSWORD = "abcdefghijklmnop"
python bot.py
```

⚠️ `config.py` — maxfiy fayl (bot tokeni + ilova paroli). GitHub'ga yuklamang.
- Bot tokeni ko'ringan bo'lsa: @BotFather → `/revoke`
- Ilova paroli ko'ringan bo'lsa: myaccount.google.com/apppasswords → o'chirib, yangisini yarating

## Guruhda nima bo'ladi

Guruh endi FAQAT hujjat qabul qiladi:
- **Oddiy hujjat** kelsa — bot **jim** turadi, faylni jimgina yig'ib boradi
  (guruhni shovqin bilan to'ldirmaslik uchun)
- **Deklaratsiya** kelsa: `📨 "N-O-336" — hujjatlar to'liq bo'ldi (5 ta fayl),
  pochtaga yuborilmoqda...` so'ng natija: `✅ "N-O-336" — pochtaga yuborildi`

Email manzillari guruhda **hech qachon** ko'rsatilmaydi — to'liq tafsilot
(qaysi manzilga yuborildi, xatolik sababi) faqat admin'ning shaxsiy chatiga boradi.

Agar partiya uchun mijoz aniqlanmasa, guruhda ogohlantirish chiqadi va admin'ga
shaxsiy xabar yuboriladi (agar `ADMIN_USER_ID` sozlangan bo'lsa) — shunda
`/batch_assign` bilan qo'lda belgilab, `/batch_send` bilan yuborish mumkin.

**Yuborilmasa nima bo'ladi:** agar birorta manzilga ham xat yetib bormasa
(Gmail ruxsati eskirgan, internet yo'q va h.k.), partiya **o'chirilmaydi** —
fayllar joyida qoladi va muammo hal bo'lgach `/batch_send KOD` bilan qayta
yuborish mumkin. Admin'ga xatolikning aniq sababi yoziladi.

## Hujjatni maksimal ishonchli aniqlash uchun qo'shilgan himoyalar

1. **Kodi yo'q fayllarga umuman tegmaydi** — guruhda odamlar gaplashishi,
   skrinshot, transport rasmlari tashlanishi mumkin. Fayl nomida (yoki rasm
   izohida) partiya kodi bo'lmasa, bot uni butunlay e'tiborsiz qoldiradi.
   **Kodi bor, lekin mijozi noma'lum** bo'lsa — fayl endi **yo'qolmaydi**:
   "noaniq fayllar" ro'yxatiga saqlanadi va admin'ga xabar boradi. Uni
   `/batch_attach KOD | ID` bilan partiyaga biriktirish yoki
   `/unmatched_delete ID` bilan o'chirish mumkin.
   (Avval bunday fayl jimgina tashlab yuborilardi — ya'ni ro'yxatga
   kiritilmagan mijozning hujjatlari yo'qolib ketardi.)
2. **Muqobil deklaratsiya belgilari** — fayl nomida "DEKL", "GTD", "DECLARATION"
   so'zlaridan biri bo'lsa ham, deklaratsiya deb tanib partiyani yakunlaydi.
3. **Eskirgan partiyalar haqida avtomatik eslatma** — partiya 24 soatdan ortiq
   deklaratsiyasiz kutsa, bot har 6 soatda tekshirib admin'ga xabar beradi
   (`STALE_HOURS`, `CHECK_INTERVAL_HOURS` — `bot.py` boshida sozlanadi).
4. **Rasm (photo) formatini ham qabul qiladi** — siqilgan rasm sifatida
   yuborilsa ham, caption'dan kod qidiriladi (mijoz/prefiks ro'yxatda
   bo'lgandagina qabul qilinadi, aks holda e'tiborsiz qoldiriladi).
5. **Dublikatni oldini olish** — bir xil fayl ikki marta qo'shilib ketmaydi
   (Telegram file ID orqali tekshiriladi).
6. **Moslashuvchan nom qidirish (alias)** — bitta mijoz uchun bir nechta nom
   varianti qo'shish mumkin (`/customer_alias`).
7. **Email manzillari guruhda hech qachon ko'rsatilmaydi** — yuborilgach
   guruhga faqat "yuborildi" deb yoziladi, to'liq manzil bilan tafsilot
   FAQAT admin'ning shaxsiy chatiga boradi.
8. **Yuborilmaguncha o'chirilmaydi** — kamida bitta manzilga xat yetib
   bormasa, fayllar diskda saqlanib qoladi (qayta yuborish mumkin).
9. **Ma'lumot fayllari buzilmaydi** — JSON fayllar atomar yoziladi, bot
   yozish paytida to'xtab qolsa ham baza yarim yozilgan holda qolmaydi.
10. **Fayl hajmi tekshiriladi** — Gmail chegarasidan (≈23 MB) oshsa,
    xat yuborilmaydi va admin'ga aniq sabab yoziladi.

## Diagnostika

Bot guruhdagi fayllarni "ko'rmayotgandek" tuyulsa — shaxsiy chatda `/status`
(yoki menyudagi 🩺 **Holat**) bosing. U guruh ID, admin ID, Gmail token holati
va kutilayotgan partiyalar sonini ko'rsatadi. Eng ko'p uchraydigan sabablar:

1. **Guruh ID mos emas.** Guruh "supergroup" ga aylantirilsa ID o'zgaradi.
   Guruhda `/chatid` yozib, `config.py` dagi `GROUP_CHAT_ID` ni yangilang.
2. **Privacy mode yoqiq.** @BotFather → `/setprivacy` → **Disable**.

## Botni doim ishlab turishi uchun

VPS serverga joylashtirish kerak bo'ladi — xohlasangiz shu bosqichda ham yordam bera olaman.#   g m a i l - b o t  
 