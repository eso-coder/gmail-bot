"""
Yuborilgan partiyalar bo'yicha HISOBOT.

Manba - sent.json (sent_store): qaysi partiya, qaysi mijozga, qaysi
pochtalarga, qachon va qanday hujjatlar bilan yuborilgani.

Bu yerda faqat o'qish va shakllantirish bor - hech narsa yozilmaydi.
"""

import csv
import io
import time

import doc_types
import sent_store
import session_store


def _typed_files(files: list) -> list:
    """
    Fayllarni turi bilan qaytaradi.

    Eski yozuvlarda hujjat turi saqlanmagan (u keyinroq qo'shilgan), shuning
    uchun turi yo'q bo'lsa fayl NOMIDAN qayta aniqlaymiz - aks holda butun
    eski tarix hisobotda "?" bo'lib, komplekt to'liq emasdek ko'rinardi.
    """
    result = []
    for f in files:
        doc_type = f.get("doc_type")
        name = f.get("filename") or ""
        if not doc_type:
            parsed = session_store.parse(name)
            if parsed:
                if parsed["is_declaration"]:
                    doc_type = "DEKL"
                else:
                    doc_type = doc_types.detect(parsed["remainder"],
                                                parsed["extension"])[0]
        result.append({"name": name, "type": doc_type})
    return result

# Mini App'dagi davr tugmalari
PERIODS = {
    "today": "Бугун",
    "7": "7 кун",
    "30": "30 кун",
    "all": "Ҳаммаси",
}


def _period_start(period: str):
    """Qaytaradi: boshlanish vaqti (epoch) yoki None (cheklovsiz)."""
    if period == "today":
        t = time.localtime()
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    if period in ("7", "30"):
        return time.time() - int(period) * 86400
    return None


def collect(period: str = "30", customer: str = "") -> dict:
    """
    Hisobot ma'lumotlari.

    Qaytaradi:
      {"entries": [...], "totals": {...}, "customers": [...]}
    entries - eng yangisi birinchi.
    """
    start = _period_start(period)
    wanted = (customer or "").strip().upper()

    entries = []
    for code, e in sent_store.all_sent().items():
        sent_at = e.get("sent_at", 0)
        if start is not None and sent_at < start:
            continue
        name = e.get("customer") or ""
        if wanted and name.upper() != wanted:
            continue

        files = _typed_files(e.get("files", []))
        entries.append({
            "code": code,
            "display": e.get("display") or code,
            "customer": name,
            "truck": e.get("truck") or "",
            "subject": e.get("subject") or "",
            "emails": e.get("emails", []),
            "sent_at": sent_at,
            "file_count": len(files),
            "files": files,
            # Qaysi kalit hujjatlar bo'lgani - komplekt to'liq ketganmi
            "missing": doc_types.missing_types(
                [{"doc_type": f["type"]} for f in files]),
        })

    entries.sort(key=lambda x: x["sent_at"], reverse=True)

    # Mijozlar ro'yxati - FILTRDAN QAT'I NAZAR butun tarixdan olinadi,
    # aks holda bitta mijozni tanlagandan keyin boshqasiga o'tib bo'lmasdi.
    all_customers = sorted({(e.get("customer") or "") for e in sent_store.all_sent().values()} - {""})

    return {
        "entries": entries,
        "customers": all_customers,
        "period": period,
        "customer": wanted,
        "totals": {
            "batches": len(entries),
            "files": sum(e["file_count"] for e in entries),
            "customers": len({e["customer"] for e in entries if e["customer"]}),
            "emails": len({addr for e in entries for addr in e["emails"]}),
        },
    }


def to_csv(entries: list) -> bytes:
    """
    Excel'da ochish uchun CSV.

    Nuqta-vergul ajratgichi va BOM bilan - aks holda Excel kirill
    harflarini buzib ko'rsatadi va hammasini bitta ustunga tiqadi.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Сана", "Вақт", "Партия", "Мижоз", "Фура",
                     "Почта", "Файллар", "Ҳужжатлар", "Йетишмаган", "Мавзу"])

    for e in entries:
        stamp = time.localtime(e["sent_at"])
        writer.writerow([
            time.strftime("%d.%m.%Y", stamp),
            time.strftime("%H:%M", stamp),
            e["display"],
            e["customer"],
            e["truck"],
            ", ".join(e["emails"]),
            e["file_count"],
            ", ".join(f["type"] or "?" for f in e["files"]),
            ", ".join(e["missing"]),
            e["subject"],
        ])

    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def text_summary(data: dict, limit: int = 15) -> str:
    """Telegram chatida ko'rsatish uchun qisqa hisobot."""
    t = data["totals"]
    title = PERIODS.get(data["period"], data["period"])
    if data.get("customer"):
        title += f" · {data['customer']}"

    lines = [
        f"📊 Ҳисобот — {title}",
        f"📨 {t['batches']} партия · 📎 {t['files']} файл · "
        f"👥 {t['customers']} мижоз · ✉️ {t['emails']} манзил",
        "",
    ]
    if not data["entries"]:
        lines.append("Бу давр учун юборилган партия йўқ.")
        return "\n".join(lines)

    for e in data["entries"][:limit]:
        stamp = time.strftime("%d.%m %H:%M", time.localtime(e["sent_at"]))
        lines.append(f"• {stamp} — {e['display']} → {e['customer'] or '—'}")
        detail = f"    {e['file_count']} файл"
        if e["truck"]:
            detail += f" · фура {e['truck']}"
        if e["missing"]:
            detail += f" · ⚠️ {', '.join(e['missing'])} йўқ эди"
        lines.append(detail)
        lines.append(f"    ✉️ {', '.join(e['emails']) or '—'}")

    if len(data["entries"]) > limit:
        lines.append("")
        lines.append(f"…ва яна {len(data['entries']) - limit} та. "
                     f"Тўлиқ рўйхат — CSV файлда.")
    return "\n".join(lines)
