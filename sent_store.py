"""
Pochtaga YUBORILGAN partiyalar tarixi.

Nima uchun kerak: partiya yuborilgach, u batches.json dan o'chiriladi.
Shundan keyin o'sha fayl guruhga qayta tashlansa, bot uni "yangi hujjat"
deb qabul qilib, yana yuborib yuborishi mumkin edi. Endi bot avval shu
tarixga qaraydi va guruhda so'raydi: "bu allaqachon yuborilgan, qayta
yuborilsinmi? HA / YO'Q".

sent.json: {
  "NGS25": {
      "display": "NGS-25",
      "customer": "GALLAKTIKA",
      "sent_at": 1756...,
      "emails": ["..."],
      "files": [{"filename": "...", "file_unique_id": "..."}]
  }
}
"""

import time

import storage

SENT_FILE = storage.data_path("sent.json")

# Tarix cheksiz o'smasligi uchun: shuncha kundan eski yozuvlar tozalanadi
KEEP_DAYS = 180


def _load() -> dict:
    return storage.load_json(SENT_FILE, {})


def _save(data: dict) -> None:
    storage.save_json(SENT_FILE, data)


def record(code: str, display: str, customer: str, emails: list, files: list) -> None:
    """Muvaffaqiyatli yuborilgan partiyani tarixga yozadi."""
    data = _load()
    entry = data.get(code) or {}
    known = {f.get("file_unique_id") for f in entry.get("files", [])}

    merged = list(entry.get("files", []))
    for f in files:
        uid = f.get("file_unique_id")
        if uid and uid in known:
            continue
        merged.append({"filename": f.get("filename"), "file_unique_id": uid})
        known.add(uid)

    data[code] = {
        "display": display,
        "customer": customer,
        "sent_at": time.time(),
        "emails": list(emails or []),
        "files": merged,
    }
    _prune(data)
    _save(data)


def _prune(data: dict) -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for code in [c for c, e in data.items() if e.get("sent_at", 0) < cutoff]:
        del data[code]


def find_by_file(file_unique_id: str):
    """
    Shu fayl ilgari yuborilganmi?
    Qaytaradi: (kod, yozuv) yoki (None, None)
    """
    if not file_unique_id:
        return None, None
    for code, entry in _load().items():
        for f in entry.get("files", []):
            if f.get("file_unique_id") == file_unique_id:
                return code, entry
    return None, None


def get(code: str):
    return _load().get(code)


def forget(code: str) -> bool:
    """Partiyani tarixdan olib tashlaydi (qayta yuborishga ruxsat berilganda)."""
    data = _load()
    if code in data:
        del data[code]
        _save(data)
        return True
    return False


def all_sent() -> dict:
    return _load()


def clear() -> int:
    count = len(_load())
    _save({})
    return count
