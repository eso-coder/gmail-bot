# Botni Railway'ga joylashtirish

## ⚠️ Eng muhim narsa — DOIMIY DISK (Volume)

Railway konteynerlarida fayl tizimi **vaqtinchalik**. Har safar yangi versiya
deploy qilinganda (yoki konteyner qayta ishga tushganda) barcha fayllar
o'chib ketadi. Bu bot esa hamma narsani fayllarda saqlaydi:

| Fayl | Nima yo'qoladi |
|---|---|
| `customers.json` | Mijozlar, emaillar, prefikslar |
| `batches.json` + `downloads/` | **Yig'ilib turgan, hali yuborilmagan hujjatlar** |
| `sessions.json` | Kod → mijoz xotirasi |
| `sent.json` | Yuborilganlar tarixi |

Shuning uchun **Volume ulash SHART**. Usiz bot ishlaydi-yu, har deploy'da
mijozlar ro'yxati va yarim yig'ilgan komplektlar yo'qoladi.

---

## 1-qadam: GitHub'ga yuklash

Railway kodni GitHub'dan oladi.

```bash
git init
git add .
git commit -m "Export hujjatlar boti"
git branch -M main
git remote add origin https://github.com/FOYDALANUVCHI/gmail-bot.git
git push -u origin main
```

`.gitignore` allaqachon sozlangan — `.env`, `downloads/`, JSON ma'lumotlari
va `.venv/` GitHub'ga **tushmaydi**.

> ✅ `git status` da `.env` ko'rinmasligi kerak. Ko'rinsa — to'xtang va
> `.gitignore` ni tekshiring. Token va parol GitHub'ga tushmasin.

---

## 2-qadam: Railway'da loyiha yaratish

1. [railway.app](https://railway.app) → **Login with GitHub**
2. **New Project** → **Deploy from GitHub repo** → repozitoriyani tanlang
3. Railway o'zi Python'ni tanib, `Procfile` dagi `worker: python bot.py` ni ishlatadi

---

## 3-qadam: Volume ulash (o'tkazib yubormang!)

1. Loyihadagi servisni oching → yuqoridagi **Settings** yonidan **Volumes**
2. **New Volume** → Mount path: **`/data`**
3. Saqlang

---

## 4-qadam: Variables (sozlamalar)

Servis → **Variables** → **Raw Editor** ga quyidagilarni qo'ying.
Qiymatlarni kompyuteringizdagi `.env` faylidan ko'chiring:

```
BOT_TOKEN=<.env dagi qiymat>
GROUP_CHAT_ID=<.env dagi qiymat>
ADMIN_USER_ID=<.env dagi qiymat>
GMAIL_ADDRESS=<.env dagi qiymat>
GMAIL_APP_PASSWORD=<.env dagi qiymat>
DATA_DIR=/data
TZ=Asia/Tashkent
```

> ⛔ **Haqiqiy token va parolni HECH QACHON shu faylga (yoki boshqa
> git'ga tushadigan faylga) yozmang.** Ular faqat `.env` da va server
> panelidagi Variables bo'limida turishi kerak.

| O'zgaruvchi | Nima uchun |
|---|---|
| `DATA_DIR=/data` | **Majburiy** — 3-qadamdagi volume yo'li |
| `TZ=Asia/Tashkent` | Vaqtlar Toshkent bo'yicha ko'rsatilsin (aks holda UTC) |

---

## 5-qadam: Mahalliy botni TO'XTATING

Bir bot tokeni bilan ikkita nusxa ishlay olmaydi — Telegram
`Conflict: terminated by other getUpdates request` xatosini beradi va
ikkalasi ham to'g'ri ishlamaydi.

Kompyuterdagi botni yoping (`Ctrl+C`) yoki:

```powershell
Get-Process python | Where-Object { $_.Path -like '*gmail_bot*' } | Stop-Process -Force
```

---

## 6-qadam: Tekshirish

Deploy tugagach botga shaxsiy chatda yozing:

1. `/status` — hammasi ✅ bo'lishi kerak
2. `/gmail_check` — **birinchi navbatda shuni tekshiring**

> Ba'zi hosting provayderlar chiquvchi SMTP portlarini (465/587) bloklaydi.
> Agar `/gmail_check` da "Gmail serveriga ulanib bo'lmadi" chiqsa — demak
> Railway shu portni bloklagan. Bu holda menga ayting, SMTP o'rniga
> boshqa yo'l (masalan Resend yoki Brevo API) qo'shamiz.

3. Guruhga bitta test komplekt tashlab ko'ring

---

## Ma'lumotlarni ko'chirish (ixtiyoriy)

Kompyuterdagi mijozlar ro'yxatini serverga o'tkazish uchun `customers.json`
va `sessions.json` ni volume'ga qo'yish kerak. Eng oson yo'li — botga
`/customer_add` buyruqlari orqali qaytadan kiritish (mijozlar 3 ta xolos):

```
/customer_add SARBON | goldxack@gmail.com
/customer_add FRUKT-SITI | goldxack@gmail.com
/customer_add GALLAKTIKA | goldxack@gmail.com
/prefix_add NG | SARBON
/prefix_add NOS | FRUKT-SITI
/prefix_add NGS | GALLAKTIKA
/customer_alias SARBON | SARBON-GALAKTIKA
/customer_alias FRUKT-SITI | TRADEWAVE-SARMANT 4X, TRADEWAVE
/customer_alias GALLAKTIKA | GLASS-GALAKTIKA-ZAPIT
```

---

## Narx

Railway'da bepul tarif yo'q — $5 sinov krediti berilади, keyin **Hobby $5/oy**.
Bu bot kichkina, oyiga taxminan $3–5 sarflaydi.

**Muqobil:** oddiy VPS (Hetzner, Contabo — oyiga ~$4). U yerda doimiy disk
o'z-o'zidan bor, volume sozlash kerak emas va SMTP bloklanmaydi. Lekin
Linux'ni qo'lda sozlash kerak (`systemd` xizmati). Xohlasangiz shu bo'yicha
ham qo'llanma yozib beraman.

---

## Nosozliklar

| Muammo | Sabab / yechim |
|---|---|
| Bot javob bermayapti | Railway → **Deployments** → loglarni oching |
| `Conflict: terminated by other getUpdates` | Ikkita nusxa ishlayapti — mahalliy botni to'xtating |
| Deploy'dan keyin mijozlar yo'qolgan | `DATA_DIR=/data` qo'yilmagan yoki volume ulanmagan |
| `/gmail_check` ❌ | SMTP bloklangan yoki ilova paroli o'zgargan |
| Guruhdagi fayllarni ko'rmayapti | @BotFather → `/setprivacy` → **Disable** |
