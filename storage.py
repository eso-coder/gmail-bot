"""
JSON ma'lumot fayllarini xavfsiz o'qish/yozish uchun umumiy yordamchi modul.

Nima uchun kerak:
1. Ma'lumot fayllari (customers.json, batches.json ...) endi HAR DOIM bot
   papkasida saqlanadi - botni qaysi papkadan ishga tushirishingizdan qat'i
   nazar. Avval nisbiy nom ishlatilgani uchun, botni boshqa papkadan
   ishga tushirsangiz, bo'sh baza yaratilib, mijozlar "yo'qolib" qolardi.
2. Yozish ATOMAR: avval vaqtinchalik faylga yoziladi, keyin o'rniga qo'yiladi.
   Yozish paytida bot to'xtab qolsa ham fayl yarim yozilgan holda qolmaydi.
3. O'qishda fayl buzilgan bo'lsa, bot ishdan chiqmaydi: buzilgan fayl
   ".corrupt" nomi bilan chetga olinadi va bo'sh baza qaytariladi.
"""

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# Kod turgan papka
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Ma'lumot fayllari (customers.json, batches.json, downloads/ ...) saqlanadigan
# papka. Odatda kod bilan bir joyda, LEKIN serverga (Railway, Docker va h.k.)
# joylashtirilganda konteyner fayl tizimi vaqtinchalik bo'ladi - har deploy'da
# hamma narsa o'chib ketadi. Shuning uchun u yerda DOIMIY disk (volume) ulanib,
# uning yo'li DATA_DIR muhit o'zgaruvchisiga yoziladi (masalan "/data").
BASE_DIR = (os.getenv("DATA_DIR") or "").strip() or APP_DIR

if BASE_DIR != APP_DIR:
    os.makedirs(BASE_DIR, exist_ok=True)
    logger.info("Ma'lumotlar shu papkada saqlanadi: %s", BASE_DIR)


def data_path(filename: str) -> str:
    """Fayl nomini bot papkasidagi to'liq yo'lga aylantiradi."""
    return os.path.join(BASE_DIR, filename)


def load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        logger.error("%s faylini o'qib bo'lmadi (%s). Fayl chetga olinmoqda.", path, e)
        try:
            os.replace(path, path + ".corrupt")
        except OSError:
            pass
        return default

    if not isinstance(data, type(default)):
        logger.error("%s faylining ichidagi ma'lumot noto'g'ri turda.", path)
        return default
    return data


def save_json(path: str, data) -> None:
    directory = os.path.dirname(path) or BASE_DIR
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # atomar almashtirish
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
