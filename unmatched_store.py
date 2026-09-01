"""
Fayl nomidan partiya kodini aniqlab bo'lmasa (yoki kod topilib, lekin mijoz
aniqlanmasa), fayl bu yerga saqlanadi - hech qanday hujjat "yo'qolib"
ketmasligi uchun. Admin keyinchalik /unmatched bilan ko'rib, /batch_attach
bilan kerakli partiyaga qo'lda biriktirishi mumkin.

unmatched.json: { "u1": {"filename": ..., "path": ..., "file_unique_id": ...,
                          "chat_id": ..., "created_at": ...}, ... }
"""

import os
import time

import storage

UNMATCHED_FILE = storage.data_path("unmatched.json")

# Ro'yxat cheksiz o'smasligi uchun eng ko'pi shuncha fayl saqlanadi
MAX_ENTRIES = 200


def _load() -> dict:
    return storage.load_json(UNMATCHED_FILE, {})


def _save(data: dict) -> None:
    storage.save_json(UNMATCHED_FILE, data)


def _next_id(data: dict) -> str:
    n = 1
    while f"u{n}" in data:
        n += 1
    return f"u{n}"


def add(filename: str, local_path: str, file_unique_id: str, chat_id) -> str:
    data = _load()

    # Chegaradan oshsa, eng eskisini olib tashlaymiz
    while len(data) >= MAX_ENTRIES:
        oldest = min(data, key=lambda k: data[k].get("created_at", 0))
        del data[oldest]

    entry_id = _next_id(data)
    data[entry_id] = {
        "filename": filename,
        "path": local_path,
        "file_unique_id": file_unique_id,
        "chat_id": chat_id,
        "created_at": time.time(),
    }
    _save(data)
    return entry_id


def already_received(file_unique_id: str) -> bool:
    if not file_unique_id:
        return False
    return any(v.get("file_unique_id") == file_unique_id for v in _load().values())


def get(entry_id: str):
    return _load().get(entry_id)


def remove(entry_id: str, delete_file: bool = False) -> bool:
    data = _load()
    if entry_id not in data:
        return False
    entry = data.pop(entry_id)
    if delete_file:
        path = entry.get("path")
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    _save(data)
    return True


def count() -> int:
    return len(_load())


def all_unmatched() -> dict:
    return _load()
