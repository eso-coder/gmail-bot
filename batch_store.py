"""
Bitta partiya (masalan "NO336") uchun kelgan barcha fayllarni yig'ib turadi.
Deklaratsiya fayli kelgunicha hech narsa yuborilmaydi - shu yerda saqlanib turadi.

batches.json: { "NO336": {"customer": "VIZOR STEP-ORC", "display": "N-O-336",
                          "files": [...], "created_at": ...} }
"""

import os
import time

import storage

BATCHES_FILE = storage.data_path("batches.json")


def _load() -> dict:
    return storage.load_json(BATCHES_FILE, {})


def _save(data: dict) -> None:
    storage.save_json(BATCHES_FILE, data)


def get_batch(code: str):
    return _load().get(code)


def add_file(code: str, filename: str, local_path: str, file_unique_id: str = None,
             customer: str = None, display: str = None, doc_type: str = None,
             truck: str = None) -> dict:
    data = _load()
    batch = data.get(code) or {"customer": None, "files": [], "created_at": time.time()}
    batch.setdefault("files", [])

    if customer and not batch.get("customer"):
        batch["customer"] = customer
    if display and not batch.get("display"):
        batch["display"] = display
    # Fura raqami - birinchi kelgan hujjatdan olinadi va keyingilari
    # shu bilan solishtiriladi (nomlashdagi xatolikni topish uchun)
    if truck and not batch.get("truck"):
        batch["truck"] = truck

    batch["files"].append({
        "filename": filename,
        "path": local_path,
        "file_unique_id": file_unique_id,
        "doc_type": doc_type,
        "truck": truck,
    })
    batch["updated_at"] = time.time()

    data[code] = batch
    _save(data)
    return batch


def has_doc_type(code: str, doc_type: str) -> bool:
    batch = _load().get(code)
    if not batch or not doc_type:
        return False
    return any(f.get("doc_type") == doc_type for f in batch.get("files", []))


def sorted_files(batch: dict) -> list:
    """
    Fayllarni xatga biriktirish tartibida qaytaradi:
    avval invoys guruhi (XLS, INV, SPETS), keyin skanerlar (ST, FITO, AKT,
    CMR, TIR), oxirida deklaratsiya va turi aniqlanmagan fayllar.
    """
    order = ["XLS", "INV", "SPETS", "ST", "FITO", "AKT", "CMR", "TIR", "MANUAL", "DEKL"]
    def key(f):
        t = f.get("doc_type")
        return (order.index(t) if t in order else len(order), f.get("filename", ""))
    return sorted(batch.get("files", []), key=key)


def is_duplicate(code: str, file_unique_id: str) -> bool:
    """Xuddi shu fayl (Telegram file_unique_id bo'yicha) bu partiyaga allaqachon qo'shilganmi."""
    if not file_unique_id:
        return False
    batch = _load().get(code)
    if not batch:
        return False
    return any(f.get("file_unique_id") == file_unique_id for f in batch.get("files", []))


def set_customer(code: str, customer: str) -> bool:
    data = _load()
    if code in data:
        data[code]["customer"] = customer
        _save(data)
        return True
    return False


def _delete_files(batch: dict) -> None:
    dirs = set()
    for f in batch.get("files", []):
        path = f.get("path")
        if not path:
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
            dirs.add(os.path.dirname(path))
        except OSError:
            pass
    # Bo'shab qolgan partiya papkasini ham olib tashlaymiz
    for d in dirs:
        try:
            if d and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass


def clear_batch(code: str, delete_files: bool = True) -> None:
    data = _load()
    if code in data:
        if delete_files:
            # Fayllarni diskdan ham tozalaymiz (allaqachon emailga yuborilgan)
            _delete_files(data[code])
        del data[code]
        _save(data)


def mark_reminded(code: str) -> None:
    data = _load()
    if code in data:
        data[code]["last_reminded"] = time.time()
        _save(data)


def missing_files(code: str) -> list:
    """Bazada bor, lekin diskda yo'q fayllar ro'yxati."""
    batch = _load().get(code)
    if not batch:
        return []
    return [f.get("filename", "?") for f in batch.get("files", [])
            if not f.get("path") or not os.path.exists(f["path"])]


def all_batches() -> dict:
    return _load()
