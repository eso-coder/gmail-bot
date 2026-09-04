"""
Bojxona deklaratsiyasi (PDF) dan xat mavzusi uchun ma'lumot ajratish.

Deklaratsiyaning birinchi sahifasida shunday qator bo'ladi:

    18 Транспортное средство при отправлении  19 Конт.  20 Условия поставки
    АВТО: 40249PCA / 407119BA   860 0 14  DAР - г. Шымкент, Республика Казахстан  50

Bizga kerak:
    • avto raqamlar  -> "40249PCA/407119BA"   (18-graf)
    • yetkazish sharti va SHAHAR -> "DAP - Шымкент"   (20-graf)

Natijada xat mavzusi:
    NGS-4  ||  40249PCA/407119BA  ||  DAP - Шымкент

MUHIM: bu modul HECH QACHON xat yuborishni to'xtatmaydi. Biror narsa
o'qilmasa, None qaytaradi va bot odatdagi mavzudan foydalanadi.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# Xalqaro yetkazib berish shartlari (Incoterms)
INCOTERMS = [
    "EXW", "FCA", "FAS", "FOB", "CFR", "CIF",
    "CPT", "CIP", "DAP", "DAT", "DPU", "DDP", "DDU", "DAF",
]

# Deklaratsiyada "DAP" ba'zan kirill harflari bilan yoziladi ("DAР" - oxirgi
# harf kirill "Р"). Ko'z bilan farq qilmaydi, dastur uchun boshqa belgi.
# Shuning uchun tekshirishdan oldin o'xshash harflarni lotinga o'tkazamiz.
LOOKALIKE = str.maketrans("АВСЕНКМОРТХУ", "ABCEHKMOPTXY")

# Shahar nomi oldidagi qisqartmalar
# "г." bilan ham, nuqtasiz "г " bilan ham yoziladi. Nuqta yoki probel talab
# qilinadi - aks holda "Гомель" kabi shahar nomining birinchi harfi kesilardi.
CITY_PREFIX = re.compile(r"^\s*(?:г\.|г\s|гор\.|город\s|ш\.|шаҳар\s)\s*", re.IGNORECASE)


def _clean_city(text: str) -> str:
    """
    "г. Шымкент, Республика Казахстан" -> "Шымкент"
    ".Шымкент"                          -> "Шымкент"
    "Ташкент"                           -> "Ташкент"
    """
    city = text.split(",")[0]              # birinchi vergulgacha
    city = CITY_PREFIX.sub("", city)       # "г." kabi qisqartmani olib tashlash
    return city.strip(" .,;:-–—")


def parse_text(text: str) -> dict:
    """
    Deklaratsiya matnidan maydonlarni ajratadi.
    Qaytaradi: {"plates": "...", "terms": "..."} - topilmagani None bo'ladi.
    """
    result = {"plates": None, "terms": None}

    for line in text.splitlines():
        if "АВТО" not in line:
            continue

        # ---- Avto raqamlar (18-graf) ----
        # "АВТО: 40249PCA / 407119BA"  yoki bitta raqam
        m = re.search(r"АВТО\s*:?\s*([A-Z0-9]{5,12})\s*(?:/\s*([A-Z0-9]{5,12}))?", line)
        if m:
            result["plates"] = f"{m.group(1)}/{m.group(2)}" if m.group(2) else m.group(1)

        # ---- Yetkazish sharti (20-graf) ----
        # Qatordagi har bir so'zni Incoterms ro'yxati bilan solishtiramiz
        words = line.split()
        for i, word in enumerate(words):
            token = word.translate(LOOKALIKE).upper().strip(".,:;-")
            if token not in INCOTERMS:
                continue
            tail = " ".join(words[i + 1:])
            tail = re.sub(r"\s+\d{1,3}\s*$", "", tail)   # oxiridagi xizmat kodi
            tail = tail.lstrip("-–— ").strip()
            city = _clean_city(tail)
            result["terms"] = f"{token} - {city}" if city else token
            break
        break

    return result


def parse_pdf(path: str) -> dict:
    """PDF fayldan maydonlarni ajratadi. Xato bo'lsa bo'sh natija."""
    empty = {"plates": None, "terms": None}
    if not path or not os.path.exists(path):
        return empty
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber o'rnatilmagan - deklaratsiya o'qilmaydi")
        return empty

    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return empty
            text = pdf.pages[0].extract_text() or ""
    except Exception as e:
        logger.warning("Deklaratsiyani o'qib bo'lmadi (%s): %s", os.path.basename(path), e)
        return empty

    return parse_text(text)


def find_declaration(files: list):
    """Partiyadagi fayllardan deklaratsiyani topadi."""
    for f in files:
        if f.get("doc_type") == "DEKL" and f.get("path"):
            return f
    return None


def build_subject(display_code: str, files: list):
    """
    Xat mavzusini yig'adi.

    Qaytaradi: (mavzu yoki None, ma'lumot dict)
    None qaytsa - deklaratsiyadan o'qib bo'lmadi, odatdagi mavzu ishlatilsin.
    """
    decl = find_declaration(files)
    if not decl:
        return None, {}

    info = parse_pdf(decl["path"])
    if not info.get("plates") or not info.get("terms"):
        return None, info

    return f"{display_code}  ||  {info['plates']}  ||  {info['terms']}", info
