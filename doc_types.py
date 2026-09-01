"""
Export hujjat turini fayl nomidan aniqlash va komplekt to'liqligini tekshirish.

KUTILAYOTGAN NOMLASH TARTIBI (masalan NGS-25, fura raqami 565):

  1) Invoys guruhi:
       NGS-25 GALLAKTIKA ZAPIT 565.xlsx   -> XLS   (invoys jadvali)
       NGS25INV.pdf                        -> INV
       NGS25SPETS.pdf                      -> SPETS
  2) Skaner qilingan hujjatlar (odatda albom bo'lib tashlanadi):
       NGS-25 ST 565.jpg                   -> ST
       NGS-25 FITO 565.jpg                 -> FITO   ("FIT" ham qabul qilinadi)
       NGS-25 AKT 565.jpg                  -> AKT
       NGS-25 CMR 565.jpg                  -> CMR
       NGS-25 TIR 565.jpg                  -> TIR
  3) Yakuniy deklaratsiya:
       NGS-25.pdf                          -> hujjatlar pochtaga yuboriladi

Hodimlar ba'zan xato nomlaydi ("NGS 25 TIR.jpg" - fura raqamisiz, yoki
"NGS 25 FIT 999.jpg" - boshqa fura raqami bilan). Bot bunday fayllarni
baribir qabul qiladi, lekin guruhda OGOHLANTIRISH yozadi - hujjat
yo'qolib ketmasin, lekin xato ham sezilmay qolmasin.
"""

import re

# Komplekt to'liq hisoblanishi uchun kerak bo'lgan hujjatlar (ko'rsatish tartibi)
REQUIRED_ORDER = ["INV", "SPETS", "ST", "FITO", "AKT", "CMR", "TIR"]

# Skaner qilinadigan hujjatlar - ular albom bo'lib tashlanadi va nomida
# fura raqami BO'LISHI kerak: "NGS-25 CMR 565.jpg"
SCAN_TYPES = {"ST", "FITO", "AKT", "CMR", "TIR"}

# Invoys guruhi - bular odatda fura raqamisiz nomlanadi ("NGS25INV.pdf"),
# shuning uchun ularda raqam yo'qligi XATO EMAS.
INVOICE_GROUP = {"XLS", "INV", "SPETS"}

# XATGA BIRIKTIRILADIGAN turlar.
# Guruhga chek, pasport nusxasi, haydovchi rasmi kabi begona fayllar ham
# tashlanadi. Turi shu ro'yxatda bo'lmagan fayl MIJOZGA YUBORILMAYDI -
# hatto fayl nomida partiya kodi bo'lsa ham.
#   DEKL   - yakuniy deklaratsiya
#   MANUAL - admin "noaniq fayllar" dan qo'lda biriktirgan fayl
ATTACHABLE = set(REQUIRED_ORDER) | {"XLS", "DEKL", "MANUAL"}


def is_attachable(doc_type) -> bool:
    return doc_type in ATTACHABLE

TITLES = {
    "INV": "INV (invoys)",
    "SPETS": "SPETS (spetsifikatsiya)",
    "ST": "ST (sertifikat)",
    "FITO": "FITO",
    "AKT": "AKT",
    "CMR": "CMR",
    "TIR": "TIR",
    "XLS": "XLS (invoys jadvali)",
    "DEKL": "Deklaratsiya",
}

# Fayl nomidagi TO'LIQ so'z (token) shu ro'yxatga mos kelsagina hisobga olinadi.
# Shu sabab "ST" so'zi "STEP-ORC" ichida uchrasa ham chalkashlik bo'lmaydi.
KEYWORDS = {
    # Invoys
    "INV": "INV", "INVOICE": "INV", "INVOYS": "INV", "INVOIS": "INV",
    "ИНВ": "INV", "ИНВОЙС": "INV",
    # Spetsifikatsiya
    "SPETS": "SPETS", "SPEC": "SPETS", "SPECS": "SPETS", "SPETC": "SPETS",
    "SPETSIFIKATSIYA": "SPETS", "SPECIFIKATSIYA": "SPETS",
    "СПЕЦ": "SPETS", "СПЕЦИФИКАЦИЯ": "SPETS",
    # Sertifikat
    "ST": "ST", "СТ": "ST", "SERT": "ST", "SERTIFIKAT": "ST",
    "CERT": "ST", "CERTIFICATE": "ST",
    # Fitosanitariya
    "FITO": "FITO", "FIT": "FITO", "PHYTO": "FITO", "FITA": "FITO",
    "ФИТО": "FITO", "ФИТ": "FITO",
    # Akt
    "AKT": "AKT", "ACT": "AKT", "АКТ": "AKT",
    # CMR
    "CMR": "CMR", "СМР": "CMR",
    # TIR
    "TIR": "TIR", "ТИР": "TIR",
}

SPREADSHEET_EXTENSIONS = {"xls", "xlsx", "xlsm", "csv"}

_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-zА-Яа-яЎўҚқҒғҲҳ]+")


def _tokens(text: str) -> list:
    return [t for t in _TOKEN_SPLIT.split(text or "") if t]


def detect(remainder: str, extension: str = ""):
    """
    Fayl nomining kod'dan tashqari qismidan hujjat turini va fura raqamini
    aniqlaydi.

    Qaytaradi: (tur yoki None, fura_raqami yoki None)
    """
    doc_type = None
    truck = None

    for token in _tokens(remainder):
        upper = token.upper()
        if upper in KEYWORDS:
            # Birinchi topilgan tur ustun (fayl nomida bittadan ko'p bo'lmaydi)
            if doc_type is None:
                doc_type = KEYWORDS[upper]
        elif token.isdigit():
            # Fura raqami odatda oxirida turadi - oxirgisini olamiz
            truck = token

    if doc_type is None and (extension or "").lower() in SPREADSHEET_EXTENSIONS:
        # "NGS-25 GALLAKTIKA ZAPIT 565.xlsx" - turi yozilmagan, lekin
        # jadval formatidan invoys jadvali ekani ma'lum
        doc_type = "XLS"

    return doc_type, truck


def title(doc_type: str) -> str:
    return TITLES.get(doc_type, doc_type or "noma'lum")


# Xabarda fayllar shu guruhlar bo'yicha ko'rsatiladi
FILE_GROUPS = [
    ("📋 Invoys guruhi", ["XLS", "INV", "SPETS"], True),
    ("🖼 Skaner hujjatlar", ["ST", "FITO", "AKT", "CMR", "TIR"], True),
    ("📎 Qo'lda qo'shilgan", ["MANUAL"], False),
    ("📕 Deklaratsiya", ["DEKL"], False),
]


def format_files(files: list) -> str:
    """
    Fayllarni guruhlab, o'qish qulay ro'yxat qilib qaytaradi:

        📋 Invoys guruhi
           • XLS — NGS-11 GLASS-GALAKTIKA-ZAPIT 269.xlsx
           • INV — NGS11INV.pdf
        🖼 Skaner hujjatlar
           • ST — NGS 11 ST 269.JPG
           ...
    """
    lines = []
    shown = set()

    for label, types, with_type in FILE_GROUPS:
        chunk = [f for f in files if f.get("doc_type") in types]
        if not chunk:
            continue
        lines.append(label)
        for f in chunk:
            shown.add(id(f))
            name = f.get("filename", "?")
            prefix = f"{f.get('doc_type')} — " if with_type else ""
            lines.append(f"   • {prefix}{name}")

    other = [f for f in files if id(f) not in shown]
    if other:
        lines.append("📄 Boshqa")
        for f in other:
            lines.append(f"   • {f.get('filename', '?')}")

    return "\n".join(lines)


def present_types(files: list) -> set:
    """Partiyadagi fayllardan qaysi turlar mavjudligini qaytaradi."""
    return {f.get("doc_type") for f in files if f.get("doc_type")}


def missing_types(files: list) -> list:
    """Komplektni to'ldirish uchun yetishmayotgan hujjatlar (tartib bilan)."""
    present = present_types(files)
    return [t for t in REQUIRED_ORDER if t not in present]


def progress_line(files: list) -> str:
    """'4/7' ko'rinishidagi qisqa holat."""
    present = present_types(files) & set(REQUIRED_ORDER)
    return f"{len(present)}/{len(REQUIRED_ORDER)}"


def summary(files: list) -> str:
    """
    Guruhga yoziladigan holat xabari:
        ✅ INV, SPETS, CMR
        ⏳ Yetishmayapti: ST, FITO, AKT, TIR
    """
    present = present_types(files)
    have = [title(t) for t in REQUIRED_ORDER if t in present]
    missing = missing_types(files)

    lines = []
    if have:
        lines.append("✅ Bor: " + ", ".join(t.split(" ")[0] for t in have))
    if "XLS" in present:
        lines.append("📊 Invoys jadvali (xlsx) bor")
    if missing:
        lines.append("⏳ Yetishmayapti: " + ", ".join(missing))
    else:
        lines.append("🎉 Komplekt to'liq")
    return "\n".join(lines)
