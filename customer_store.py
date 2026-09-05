"""
Mijozlar bazasi: qo'shish, o'chirish, ro'yxat, fayl nomidan yoki kod-prefiksidan
mijozni topish.

Har bir mijoz: {"emails": [...], "prefixes": [...], "aliases": [...]}
  - emails: xat yuboriladigan manzillar
  - prefixes: kod-prefikslari (masalan "NG", "GJ") - agar partiya kodi shu
    prefiks bilan boshlansa, mijoz nomi orqali qidirmasdan to'g'ridan-to'g'ri
    shu mijozga yuboriladi.
  - aliases: muqobil nomlar (fayl nomida shular uchrasa ham mijoz topiladi)

Ma'lumotlar customers.json faylida saqlanadi.
"""

import os
import re

import storage

CUSTOMERS_FILE = storage.data_path("customers.json")

# Juda qisqa alias ("A", "NG") deyarli har qanday fayl nomiga tasodifan mos
# kelib, hujjatni noto'g'ri mijozga yuborib yuborishi mumkin. Shuning uchun
# fayl nomi bo'yicha qidirishda faqat shu uzunlikdan katta nomlar ishlatiladi.
MIN_NAME_MATCH_LEN = 3

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.match(email.strip()))


def _clean_emails(emails) -> list:
    """Bo'sh joylarni olib tashlaydi va takrorlanganlarini bittaga tushiradi."""
    result = []
    seen = set()
    for email in emails or []:
        email = str(email).strip()
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(email)
    return result


def _normalize_record(info) -> dict:
    """Bazadagi yozuv buzuq bo'lsa ham, kutilgan shaklga keltiradi."""
    if not isinstance(info, dict):
        return {"emails": [], "prefixes": [], "aliases": []}
    return {
        "emails": [e for e in info.get("emails", []) if isinstance(e, str)],
        "prefixes": [p for p in info.get("prefixes", []) if isinstance(p, str)],
        "aliases": [a for a in info.get("aliases", []) if isinstance(a, str)],
    }


def load_customers() -> dict:
    raw = storage.load_json(CUSTOMERS_FILE, {})
    return {name: _normalize_record(info) for name, info in raw.items()}


def save_customers(data: dict) -> None:
    storage.save_json(CUSTOMERS_FILE, data)


def add_customer(name: str, emails: list) -> None:
    data = load_customers()
    name = name.strip().upper()
    existing = data.get(name, {"emails": [], "prefixes": [], "aliases": []})
    existing["emails"] = _clean_emails(emails)
    existing.setdefault("prefixes", [])
    existing.setdefault("aliases", [])
    data[name] = existing
    save_customers(data)


def remove_customer(name: str) -> bool:
    data = load_customers()
    name = name.strip().upper()
    if name in data:
        del data[name]
        save_customers(data)
        return True
    return False


def exists(name: str) -> bool:
    return name.strip().upper() in load_customers()


def get_emails(name: str):
    """Mijozning email ro'yxatini qaytaradi. Mijoz topilmasa None."""
    if not name:
        return None
    customer = load_customers().get(name.strip().upper())
    if customer is None:
        return None
    return customer.get("emails", [])


def find_by_filename(filename: str):
    """
    Fayl nomida mijoz nomi YOKI uning alias(lar)idan biri borligini tekshiradi.
    Bir nechta mos kelsa, eng uzun (aniqroq) matnni tanlaydi.
    Qaytaradi: (kompaniya_nomi, [emaillar]) yoki (None, None)
    """
    data = load_customers()
    fname_lower = filename.lower()
    best_match = None
    best_customer = None
    for name, info in data.items():
        for candidate in [name] + info.get("aliases", []):
            if len(candidate.strip()) < MIN_NAME_MATCH_LEN:
                continue
            if candidate.lower() in fname_lower:
                if best_match is None or len(candidate) > len(best_match):
                    best_match = candidate
                    best_customer = name
    if best_customer:
        return best_customer, data[best_customer].get("emails", [])
    return None, None


def add_alias(alias: str, name: str) -> bool:
    """Alias (muqobil nom) ni mijozga bog'laydi. Mijoz topilmasa False qaytaradi."""
    data = load_customers()
    name = name.strip().upper()
    alias = alias.strip()

    # Juda qisqa alias har qanday faylga mos kelib, hujjatni noto'g'ri
    # mijozga yuborib yuborishi mumkin - shuning uchun qabul qilinmaydi
    if name not in data or len(alias) < MIN_NAME_MATCH_LEN:
        return False

    data[name].setdefault("aliases", [])
    if alias.lower() not in [a.lower() for a in data[name]["aliases"]]:
        data[name]["aliases"].append(alias)

    save_customers(data)
    return True


def remove_alias(alias: str, name: str = "") -> bool:
    """Aliasni olib tashlaydi. `name` berilmasa, barcha mijozlardan izlaydi."""
    data = load_customers()
    alias = alias.strip().lower()
    if not alias:
        return False

    targets = [name.strip().upper()] if name.strip() else list(data)
    for key in targets:
        info = data.get(key)
        if not info:
            continue
        kept = [a for a in info.get("aliases", []) if a.strip().lower() != alias]
        if len(kept) != len(info.get("aliases", [])):
            info["aliases"] = kept
            save_customers(data)
            return True
    return False


def set_emails(name: str, emails: list) -> bool:
    """Mijozning email ro'yxatini butunlay almashtiradi."""
    data = load_customers()
    name = name.strip().upper()
    if name not in data:
        return False
    data[name]["emails"] = _clean_emails(emails)
    save_customers(data)
    return True


def rename_customer(old: str, new: str) -> bool:
    """
    Mijoz nomini o'zgartiradi; prefiks va aliaslar saqlanib qoladi.
    Yangi nom allaqachon band bo'lsa yoki eski nom topilmasa - False.
    """
    data = load_customers()
    old = old.strip().upper()
    new = new.strip().upper()
    if not new or old not in data:
        return False
    if new != old and new in data:
        return False

    # Tartibni saqlab qolish uchun lug'atni qayta yig'amiz
    data = {(new if k == old else k): v for k, v in data.items()}
    save_customers(data)
    return True


def add_prefix(prefix: str, name: str) -> bool:
    """Prefiksni mijozga bog'laydi. Agar mijoz mavjud bo'lmasa False qaytaradi."""
    data = load_customers()
    name = name.strip().upper()
    prefix = re.sub(r"[^A-Za-zА-Яа-я]", "", prefix).upper()

    if name not in data or not prefix:
        return False

    # Boshqa mijozdagi shu prefiksni tozalab, ziddiyat bo'lmasin
    for other in data.values():
        if prefix in other.get("prefixes", []):
            other["prefixes"].remove(prefix)

    data[name].setdefault("prefixes", [])
    if prefix not in data[name]["prefixes"]:
        data[name]["prefixes"].append(prefix)

    save_customers(data)
    return True


def remove_prefix(prefix: str) -> bool:
    data = load_customers()
    prefix = re.sub(r"[^A-Za-zА-Яа-я]", "", prefix).upper()
    for customer in data.values():
        if prefix in customer.get("prefixes", []):
            customer["prefixes"].remove(prefix)
            save_customers(data)
            return True
    return False


def find_by_prefix(prefix: str):
    """Qaytaradi: kompaniya_nomi yoki None"""
    if not prefix:
        return None
    data = load_customers()
    prefix = prefix.upper()
    for name, customer in data.items():
        if prefix in customer.get("prefixes", []):
            return name
    return None


def bootstrap_if_empty(defaults: dict) -> None:
    if not os.path.exists(CUSTOMERS_FILE):
        save_customers(defaults)
