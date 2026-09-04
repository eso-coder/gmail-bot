"""
Telegram Mini App uchun kichik veb-server.

Bot bilan BIR JARAYONDA ishlaydi, shuning uchun ma'lumotlarga to'g'ridan-to'g'ri
kira oladi - alohida baza yoki API kaliti kerak emas.

XAVFSIZLIK
Telegram Mini App'ni ochganda `initData` degan imzolangan ma'lumot yuboradi.
Uning imzosi bot tokeni bilan tekshiriladi (Telegram hujjatidagi algoritm).
Imzo to'g'ri bo'lsa ham, foydalanuvchi ADMIN_USER_ID bo'lishi shart -
aks holda har qanday odam havolani ochib boshqara olardi.

Server faqat 127.0.0.1 da tinglaydi; tashqariga Caddy (HTTPS) orqali chiqariladi.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web

import batch_store
import config
import customer_store
import doc_types
import session_store
import storage
import unmatched_store

logger = logging.getLogger(__name__)

WEB_DIR = os.path.join(storage.APP_DIR, "webapp")
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8080

# initData shuncha soniyadan eski bo'lsa, qabul qilinmaydi (takroriy hujumdan himoya)
MAX_AUTH_AGE = 24 * 3600


def _check_init_data(init_data: str):
    """
    Telegram imzosini tekshiradi.
    Qaytaradi: user dict yoki None.
    """
    if not init_data or not config.BOT_TOKEN:
        return None

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        return None

    # Eskirgan ma'lumotni qabul qilmaymiz
    try:
        if time.time() - int(pairs.get("auth_date", 0)) > MAX_AUTH_AGE:
            return None
    except ValueError:
        return None

    try:
        return json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None


def _require_admin(payload: dict):
    """Qaytaradi: (user, xato_javobi). Xato bo'lmasa xato_javobi None."""
    user = _check_init_data(payload.get("initData", ""))
    if not user:
        return None, web.json_response({"error": "Imzo tekshiruvidan o'tmadi"}, status=401)
    if config.ADMIN_USER_ID is not None and user.get("id") != config.ADMIN_USER_ID:
        logger.warning("Mini App: ruxsatsiz urinish, user id=%s", user.get("id"))
        return None, web.json_response({"error": "Sizda ruxsat yo'q"}, status=403)
    return user, None


# ---------- Ma'lumotlarni to'plash ----------

def _collect_state() -> dict:
    customers = []
    for name, info in sorted(customer_store.load_customers().items()):
        customers.append({
            "name": name,
            "emails": info.get("emails", []),
            "prefixes": info.get("prefixes", []),
            "aliases": info.get("aliases", []),
        })

    now = time.time()
    batches = []
    for code, b in sorted(batch_store.all_batches().items()):
        files = b.get("files", [])
        batches.append({
            "code": code,
            "display": b.get("display") or code,
            "customer": b.get("customer"),
            "truck": b.get("truck"),
            "file_count": len(files),
            "progress": doc_types.progress_line(files),
            "missing": doc_types.missing_types(files),
            "age_hours": round((now - b.get("created_at", now)) / 3600, 1),
            "files": [{"name": f.get("filename"), "type": f.get("doc_type")} for f in files],
        })

    unmatched = []
    for eid, info in sorted(unmatched_store.all_unmatched().items()):
        unmatched.append({
            "id": eid,
            "filename": info.get("filename"),
            "age_hours": round((now - info.get("created_at", now)) / 3600, 1),
        })

    return {
        "customers": customers,
        "batches": batches,
        "unmatched": unmatched,
        "required": doc_types.REQUIRED_ORDER,
    }


# ---------- Amallar ----------

async def _do_action(action: str, data: dict, ctx) -> dict:
    """Qaytaradi: {"ok": True, "message": ...} yoki {"error": ...}"""

    if action == "customer_add":
        name = (data.get("name") or "").strip()
        emails = [e.strip() for e in (data.get("emails") or "").split(",") if e.strip()]
        if not name:
            return {"error": "Mijoz nomi bo'sh"}
        bad = [e for e in emails if not customer_store.is_valid_email(e)]
        if bad:
            return {"error": "Email noto'g'ri: " + ", ".join(bad)}
        if not emails:
            return {"error": "Kamida bitta email kiriting"}
        customer_store.add_customer(name, emails)
        return {"ok": True, "message": f"{name.upper()} saqlandi"}

    if action == "customer_remove":
        name = data.get("name") or ""
        if customer_store.remove_customer(name):
            session_store.forget_customer(name.strip().upper())
            return {"ok": True, "message": f"{name} o'chirildi"}
        return {"error": "Mijoz topilmadi"}

    if action == "prefix_add":
        if customer_store.add_prefix(data.get("prefix", ""), data.get("name", "")):
            return {"ok": True, "message": "Prefiks bog'landi"}
        return {"error": "Bog'lanmadi — mijoz yoki prefiks noto'g'ri"}

    if action == "prefix_remove":
        if customer_store.remove_prefix(data.get("prefix", "")):
            return {"ok": True, "message": "Prefiks o'chirildi"}
        return {"error": "Prefiks topilmadi"}

    if action == "alias_add":
        alias = (data.get("alias") or "").strip()
        if len(alias) < customer_store.MIN_NAME_MATCH_LEN:
            return {"error": f"Alias kamida {customer_store.MIN_NAME_MATCH_LEN} belgi bo'lishi kerak"}
        if customer_store.add_alias(alias, data.get("name", "")):
            return {"ok": True, "message": "Alias qo'shildi"}
        return {"error": "Qo'shilmadi — mijoz topilmadi"}

    if action == "batch_assign":
        code, name = data.get("code", ""), (data.get("name") or "").strip().upper()
        if not customer_store.exists(name):
            return {"error": "Mijoz topilmadi"}
        if batch_store.set_customer(code, name):
            session_store.remember(code, name)
            return {"ok": True, "message": f"{code} → {name}"}
        return {"error": "Partiya topilmadi"}

    if action == "batch_cancel":
        code = data.get("code", "")
        if not batch_store.get_batch(code):
            return {"error": "Partiya topilmadi"}
        batch_store.clear_batch(code)
        return {"ok": True, "message": f"{code} bekor qilindi"}

    if action == "batch_send":
        code = data.get("code", "")
        if not batch_store.get_batch(code):
            return {"error": "Partiya topilmadi"}
        await ctx["send_batch"](code)
        return {"ok": True, "message": f"{code} yuborish boshlandi — natijani chatda ko'ring"}

    if action == "unmatched_attach":
        entry = ctx["attach_unmatched"](data.get("id", ""), (data.get("code") or "").upper())
        if not entry:
            return {"error": "Fayl topilmadi"}
        return {"ok": True, "message": f"{entry['filename']} biriktirildi"}

    if action == "unmatched_delete":
        if unmatched_store.remove(data.get("id", ""), delete_file=True):
            return {"ok": True, "message": "O'chirildi"}
        return {"error": "Fayl topilmadi"}

    return {"error": f"Noma'lum amal: {action}"}


# ---------- HTTP yo'llari ----------

def create_app(ctx) -> web.Application:
    """
    ctx - bot funksiyalari:
        send_batch(code)          - async, partiyani yuboradi
        attach_unmatched(id, code)- sync, noaniq faylni biriktiradi
    """
    app = web.Application()

    async def index(request):
        path = os.path.join(WEB_DIR, "index.html")
        if not os.path.exists(path):
            return web.Response(text="index.html topilmadi", status=404)
        return web.FileResponse(path)

    async def api_state(request):
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Noto'g'ri so'rov"}, status=400)
        user, err = _require_admin(payload)
        if err:
            return err
        return web.json_response({"ok": True, "user": user.get("first_name"), **_collect_state()})

    async def api_action(request):
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Noto'g'ri so'rov"}, status=400)
        user, err = _require_admin(payload)
        if err:
            return err

        action = payload.get("action", "")
        try:
            result = await _do_action(action, payload.get("data") or {}, ctx)
        except Exception as e:
            logger.exception("Mini App amali xato: %s", action)
            result = {"error": f"Xatolik: {e}"}

        if "error" in result:
            return web.json_response(result, status=400)
        result.update(_collect_state())
        return web.json_response(result)

    app.router.add_get("/", index)
    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/action", api_action)
    app.router.add_static("/static/", WEB_DIR)
    return app


async def start(ctx):
    """Veb-serverni ishga tushiradi. Muvaffaqiyatsiz bo'lsa bot ishlashda davom etadi."""
    try:
        runner = web.AppRunner(create_app(ctx), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, LISTEN_HOST, LISTEN_PORT)
        await site.start()
        logger.info("Mini App serveri ishga tushdi: http://%s:%s", LISTEN_HOST, LISTEN_PORT)
        return runner
    except Exception:
        logger.exception("Mini App serverini ishga tushirib bo'lmadi")
        return None
