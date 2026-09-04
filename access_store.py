"""
Kim botni boshqara oladi (adminlar) va bot qaysi guruhlardan hujjat qabul
qiladi (guruhlar).

Ilgari ikkalasi ham `.env` faylida qotib qolgan edi - o'zgartirish uchun
serverga kirib, botni qayta ishga tushirish kerak bo'lardi. Endi ular
botning o'zidan boshqariladi.

EGASI (owner) — `.env` dagi ADMIN_USER_ID. U:
  • har doim admin bo'lib qoladi (ro'yxatdan o'chirib bo'lmaydi)
  • boshqa adminlarni qo'shadi va olib tashlaydi

Qo'shilgan adminlar botning barcha amallarini bajara oladi, LEKIN
admin ro'yxatini o'zgartira olmaydi - aks holda bitta admin orqali
boshqalar ham kirib olishi mumkin bo'lardi.

admins.json: {"123456": {"name": "Aziz", "added_at": 1756...}}
groups.json: {"-1001234": {"title": "Export hujjatlar", "added_at": 1756...}}
"""

import time

import config
import storage

ADMINS_FILE = storage.data_path("admins.json")
GROUPS_FILE = storage.data_path("groups.json")


# ---------- Adminlar ----------

def owner_id():
    return config.ADMIN_USER_ID


def is_owner(user_id) -> bool:
    return owner_id() is not None and user_id == owner_id()


def all_admins() -> dict:
    return storage.load_json(ADMINS_FILE, {})


def admin_ids() -> set:
    ids = {int(k) for k in all_admins() if str(k).lstrip("-").isdigit()}
    if owner_id() is not None:
        ids.add(owner_id())
    return ids


def is_admin(user_id) -> bool:
    # ADMIN_USER_ID umuman belgilanmagan bo'lsa - hamma kira oladi
    # (config.validate() bu holatda ogohlantiradi)
    if owner_id() is None and not all_admins():
        return True
    return user_id in admin_ids()


def add_admin(user_id: int, name: str = "") -> bool:
    """Qaytaradi: True - qo'shildi, False - allaqachon bor edi."""
    if is_owner(user_id):
        return False
    data = all_admins()
    key = str(user_id)
    if key in data:
        return False
    data[key] = {"name": name or "", "added_at": time.time()}
    storage.save_json(ADMINS_FILE, data)
    return True


def remove_admin(user_id: int) -> bool:
    data = all_admins()
    key = str(user_id)
    if key not in data:
        return False
    del data[key]
    storage.save_json(ADMINS_FILE, data)
    return True


# ---------- Guruhlar ----------

def all_groups() -> dict:
    data = storage.load_json(GROUPS_FILE, {})
    # Eski sozlamadan ko'chirish: ro'yxat bo'sh bo'lsa-yu, .env da guruh
    # ko'rsatilgan bo'lsa, o'shani birinchi guruh sifatida qabul qilamiz.
    if not data and config.GROUP_CHAT_ID is not None:
        data = {str(config.GROUP_CHAT_ID): {"title": "(.env dan)", "added_at": time.time()}}
        storage.save_json(GROUPS_FILE, data)
    return data


def group_ids() -> set:
    return {int(k) for k in all_groups() if str(k).lstrip("-").isdigit()}


def is_allowed_group(chat_id) -> bool:
    groups = group_ids()
    if not groups:
        # Birorta guruh belgilanmagan - bot qo'shilgan barcha guruhlardan
        # qabul qiladi (eski xatti-harakat)
        return True
    return chat_id in groups


def add_group(chat_id: int, title: str = "") -> bool:
    data = all_groups()
    key = str(chat_id)
    if key in data:
        return False
    data[key] = {"title": title or "", "added_at": time.time()}
    storage.save_json(GROUPS_FILE, data)
    return True


def remove_group(chat_id: int) -> bool:
    data = all_groups()
    key = str(chat_id)
    if key not in data:
        return False
    del data[key]
    storage.save_json(GROUPS_FILE, data)
    return True
