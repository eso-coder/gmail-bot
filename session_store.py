"""
Fayl nomidan partiya kodini ajratib olish, "deklaratsiya" faylini aniqlash,
va kod -> mijoz bog'lanishini eslab qolish (uzoq muddatli xotira, sessions.json).

MASALAN:
  "N-O-336 VIZOR STEP-ORC 567.xlsx" -> kod="NO336", deklaratsiya emas
  "NO336INV.pdf"                    -> kod="NO336", deklaratsiya emas
  "N-O-336.pdf"                     -> kod="NO336", DEKLARATSIYA (chunki fayl
                                        nomida kod dan boshqa hech narsa yo'q)
"""

import re

import storage

SESSIONS_FILE = storage.data_path("sessions.json")

LETTERS = "A-Za-zА-Яа-яЎўҚқҒғҲҳ"

# Kod odatda 1-4 ta harf va undan keyingi raqamlardan iborat:
#   "GJ-22", "GJ22", "NG-1", "N-O-336", "N O 336"
#
# Bu yerda IKKI JIDDIY XATOLIK tuzatilgan:
#
# 1) Boshidagi (?<!...) — kod so'zning O'RTASIDAN boshlanmasligi kerak.
#    Aks holda "AKT NG-1 ....JPG" fayli "KTNG1" degan soxta kod hosil qilardi
#    (AKT dagi "KT" + "NG" qo'shilib ketardi). Natijada bitta NG-1 partiyasi
#    "KTNG1", "MRNG1", "ITNG1", "NVNG1" kabi bir nechta soxta partiyaga
#    bo'linib ketardi va deklaratsiya kelganda hujjatlar YUBORILMAY qolardi.
#
# 2) Harflar orasida probel FAQAT bitta-bitta harflar uchun ruxsat etiladi
#    ("N O 336"). "ST NG-1" da esa ikkita alohida so'z bor — ular birlashib
#    "STNG1" bo'lib ketmasligi kerak, to'g'ri kod "NG1".
CODE_PATTERN = re.compile(
    rf"(?<![{LETTERS}0-9])"
    rf"(?:"
    # a) yonma-yon harflar + raqam: "NG-1", "NG1", "NOS-34", "NG 1"
    rf"[{LETTERS}]{{1,4}}[-\s]?\d{{1,6}}"
    # b) bitta-bitta ajratilgan harflar + raqam: "N-O-336", "N O 336"
    rf"|[{LETTERS}](?:[-\s][{LETTERS}]){{1,3}}[-\s]?\d{{1,6}}"
    rf")"
)

EXTENSION_PATTERN = re.compile(r"\.[A-Za-z0-9]{2,5}$")

# Bu so'zlardan biri fayl nomida bo'lsa ham, deklaratsiya deb hisoblanadi -
# hatto fayl nomida kod dan boshqa matn bo'lsa ham (masalan "NG-2 DEKLARATSIYA.pdf")
DECLARATION_KEYWORDS = ["DEKL", "DECLARATION", "GTD", "ГТД", "ДЕКЛАРАЦИЯ", "DEKLARATSIYA"]


def _has_declaration_keyword(filename: str) -> bool:
    upper = filename.upper()
    return any(kw in upper for kw in DECLARATION_KEYWORDS)


def parse(filename: str):
    """
    Fayl nomini to'liq tahlil qiladi.

    Qaytaradi dict yoki None (kod topilmasa):
        code        - normallashtirilgan kod, "NGS25"
        display     - fayl nomidagi asl ko'rinish, "NGS-25"
        prefix      - harf qismi, "NGS"
        remainder   - kod va kengaytmadan tashqari qism, " GALLAKTIKA ZAPIT 565"
        extension   - "xlsx"
        is_declaration - yakuniy deklaratsiyami
    """
    m = CODE_PATTERN.search(filename)
    if not m:
        return None

    raw = m.group(0)
    start, end = m.span()
    normalized = re.sub(rf"[^{LETTERS}0-9]", "", raw).upper()

    prefix_m = re.match(rf"^[{LETTERS}]+", normalized)
    prefix = prefix_m.group(0).upper() if prefix_m else None

    display = re.sub(r"\s+", " ", raw).strip().upper()

    name_no_ext = EXTENSION_PATTERN.sub("", filename)
    ext_match = EXTENSION_PATTERN.search(filename)
    extension = ext_match.group(0)[1:].lower() if ext_match else ""

    remainder = name_no_ext[:start] + name_no_ext[end:]
    remainder_clean = re.sub(r"[\s\-_.]+", "", remainder)

    is_declaration = (
        (remainder_clean == "" and extension == "pdf")
        or _has_declaration_keyword(filename)
    )

    return {
        "code": normalized,
        "display": display,
        "prefix": prefix,
        "remainder": remainder,
        "extension": extension,
        "is_declaration": is_declaration,
    }


def analyze_filename(filename: str):
    """
    Eskicha interfeys (parse() ning qisqartmasi).
    Qaytaradi: (kod, deklaratsiyami, prefiks, ko'rsatiladigan_kod)
    Agar kod topilmasa: (None, False, None, None)
    """
    p = parse(filename)
    if not p:
        return None, False, None, None
    return p["code"], p["is_declaration"], p["prefix"], p["display"]


def _load() -> dict:
    return storage.load_json(SESSIONS_FILE, {})


def _save(data: dict) -> None:
    storage.save_json(SESSIONS_FILE, data)


def remember(code: str, customer_name: str) -> None:
    if not code or not customer_name:
        return
    data = _load()
    if data.get(code) == customer_name:
        return  # o'zgarish yo'q - keraksiz yozishning hojati yo'q
    data[code] = customer_name
    _save(data)


def recall(code: str):
    return _load().get(code)


def clear(code: str) -> bool:
    data = _load()
    if code in data:
        del data[code]
        _save(data)
        return True
    return False


def forget_customer(customer_name: str) -> int:
    """Mijoz o'chirilganda, unga bog'langan kod xotirasini ham tozalaydi."""
    data = _load()
    codes = [c for c, name in data.items() if name == customer_name]
    for code in codes:
        del data[code]
    if codes:
        _save(data)
    return len(codes)


def all_sessions() -> dict:
    return _load()
