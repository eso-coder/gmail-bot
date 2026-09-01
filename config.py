"""
Bot sozlamalari.

Barcha maxfiy qiymatlar MUHIT O'ZGARUVCHILARI orqali beriladi — kod ichida
parol saqlanmaydi. Ikki xil usul bor:

1) KOMPYUTERDA ishlatish uchun — shu papkadagi `.env` faylini to'ldiring:

       BOT_TOKEN=123456:AAF...
       GROUP_CHAT_ID=-1001234567890
       ADMIN_USER_ID=123456789
       GMAIL_ADDRESS=sizning.pochta@gmail.com
       GMAIL_APP_PASSWORD=abcd efgh ijkl mnop

   `.env` fayli `.gitignore` da — u hech qachon GitHub'ga tushmaydi.

2) SERVERDA (Railway, VPS) — o'sha qiymatlarni server panelidagi
   "Variables" bo'limiga qo'yasiz. `.env` fayli kerak emas.

DIQQAT: bot tokeni va ilova paroli — parol kabi maxfiy ma'lumot.
"""

import os

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_APP_DIR, ".env")


def _load_env_file(path: str) -> None:
    """
    Oddiy .env o'quvchi (qo'shimcha kutubxonasiz).
    Allaqachon o'rnatilgan muhit o'zgaruvchilari USTUN turadi - shuning
    uchun serverdagi sozlamalar .env faylidan ustun bo'ladi.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_env_file(_ENV_FILE)


def _str_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _int_env(name: str, default=None):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    raw = raw.strip()
    if raw.lower() in ("none", "null"):
        return None
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Sozlama xato: {name} butun son bo'lishi kerak, berilgani: {raw!r}")


# BotFather'dan olingan token
BOT_TOKEN = _str_env("BOT_TOKEN")

# Hujjatlar tashlanadigan guruh ID raqami.
# Botni guruhga qo'shib, guruhda /chatid yuboring - bot ID ni ko'rsatadi.
# Bo'sh qoldirilsa, bot qo'shilgan BARCHA guruhlardan hujjat qabul qiladi.
# DIQQAT: guruh "supergroup" ga aylantirilsa, ID O'ZGARADI (-100... shaklga o'tadi).
GROUP_CHAT_ID = _int_env("GROUP_CHAT_ID")

# Botni BOSHQARADIGAN shaxsning Telegram user ID si.
# Buyruqlar FAQAT shu odam botning shaxsiy chatida yozganda ishlaydi.
# Buni bilmasangiz: botga shaxsiy xabar yozib, /myid deb yuboring.
ADMIN_USER_ID = _int_env("ADMIN_USER_ID")


# ---------- Gmail (SMTP + ilova paroli) ----------
#
# Bot xatlarni SHU manzildan yuboradi.
GMAIL_ADDRESS = _str_env("GMAIL_ADDRESS")

# ⚠️ Bu ODDIY GMAIL PAROLINGIZ EMAS!
# Bu — myaccount.google.com/apppasswords dan olingan 16 belgili maxsus parol.
# 2 bosqichli tasdiqlash yoqilgan bo'lishi shart.
GMAIL_APP_PASSWORD = _str_env("GMAIL_APP_PASSWORD")


def validate() -> list:
    """Sozlamalardagi muammolarni ro'yxat qilib qaytaradi (bo'sh = hammasi joyida)."""
    problems = []
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        problems.append(
            "BOT_TOKEN belgilanmagan yoki noto'g'ri. @BotFather bergan tokenni "
            ".env fayliga (yoki server Variables bo'limiga) qo'ying."
        )
    if ADMIN_USER_ID is None:
        problems.append(
            "ADMIN_USER_ID belgilanmagan - buyruqlardan HAMMA foydalana oladi. "
            "Botga /myid yozib, ID ingizni .env ga qo'ying."
        )
    if GROUP_CHAT_ID is None:
        problems.append(
            "GROUP_CHAT_ID belgilanmagan - bot BARCHA guruhlardan hujjat qabul qiladi. "
            "Guruhda /chatid yozib, ID ni .env ga qo'ying."
        )
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        problems.append(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD belgilanmagan - bot xat yubora "
            "olmaydi. myaccount.google.com/apppasswords dan ilova paroli oling."
        )
    return problems
