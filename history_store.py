"""
Amallar tarixi — kim, qachon, nima qilgani.

Nima uchun kerak: partiya yuborilgach u batches.json dan o'chiriladi va
"kecha nima bo'lgani" haqida hech qanday iz qolmasdi. Endi muhim amallar
shu yerda saqlanadi — Mini App'dagi "Tarix" bo'limida ko'rinadi.

history.json: [{"at": 1756..., "kind": "batch_sent", "text": "...", "who": "Aley"}, ...]
Eng yangisi ro'yxatning boshida turadi.
"""

import logging
import time

import storage

logger = logging.getLogger(__name__)

HISTORY_FILE = storage.data_path("history.json")

# Ro'yxat cheksiz o'smasligi uchun eng ko'pi shuncha yozuv saqlanadi
MAX_ENTRIES = 300

# Har bir amal turi uchun belgi (Mini App'da ko'rsatiladi)
ICONS = {
    "batch_sent": "📨",
    "batch_failed": "❌",
    "batch_cancel": "🗑",
    "batch_assign": "👤",
    "customer_add": "➕",
    "customer_remove": "🗑",
    "prefix_add": "🔗",
    "prefix_remove": "🔗",
    "alias_add": "🔤",
    "unmatched_attach": "📎",
    "unmatched_delete": "🗑",
    "admin_add": "👑",
    "admin_remove": "👑",
    "group_add": "📢",
    "group_remove": "📢",
    "doc_edited": "✏️",
}


def _load() -> list:
    return storage.load_json(HISTORY_FILE, [])


def add(kind: str, text: str, who: str = "") -> None:
    """Tarixga yozuv qo'shadi. Xatolik bo'lsa ham botni to'xtatmaydi."""
    try:
        data = _load()
        data.insert(0, {
            "at": time.time(),
            "kind": kind,
            "text": text,
            "who": who or "",
        })
        del data[MAX_ENTRIES:]
        storage.save_json(HISTORY_FILE, data)
    except Exception:
        logger.exception("Tarixga yozib bo'lmadi: %s", kind)


def recent(limit: int = 60) -> list:
    entries = _load()[:limit]
    for e in entries:
        e["icon"] = ICONS.get(e.get("kind"), "•")
    return entries


def clear() -> int:
    count = len(_load())
    storage.save_json(HISTORY_FILE, [])
    return count
