"""
Guruhga tashlangan hujjatlarni partiya kodi bo'yicha yig'ib turadi, deklaratsiya
fayli (masalan "N-O-336.pdf") kelgach, BARCHA yig'ilgan hujjatlarni bitta xatga
ilova qilib mijoz emailiga yuboradi.

Boshqaruv botning shaxsiy chatida, /start bosilganda chiqadigan tugmali menyu
orqali amalga oshiriladi (matn buyruqlar ham ishlaydi, lekin shart emas).

Ishga tushirish: python bot.py
To'xtatish: Ctrl+C
"""

import asyncio
import functools
import hashlib
import html
import logging
import os
import re
import time
import traceback
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters,
)

import access_store
import batch_store
import config
import customer_store
import declaration
import doc_types
import gmail_sender
import history_store
import sent_store
import session_store
import storage
import unmatched_store
import webapp

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = storage.data_path("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Deklaratsiyasiz shuncha soat kutgan partiya uchun admin'ga eslatma yuboriladi
STALE_HOURS = 24
# Eslatmalar orasidagi minimal interval (spam bo'lmasligi uchun)
REMINDER_COOLDOWN_HOURS = 24
# Bot har necha soatda eskirgan partiyalarni tekshiradi
CHECK_INTERVAL_HOURS = 6
# Gmail ruxsati hali ishlayaptimi - shuncha soatda bir tekshiriladi
GMAIL_CHECK_INTERVAL_HOURS = 6
# Mini App manzili (HTTPS bo'lishi SHART). Bo'sh bo'lsa menyuda tugma chiqmaydi.
WEBAPP_URL = (os.getenv("WEBAPP_URL") or "").strip()

# Bitta menyuda ko'rsatiladigan maksimal tugma soni (Telegram cheklovi uchun)
MAX_BUTTONS = 40

# DIQQAT: bu yerda "namuna" mijozlar YARATILMAYDI.
#
# Ilgari bo'sh bazada avtomatik SARBON (galaxy@gmail.com) va BMB GROUP
# (bmb23@mail.ru) yaratilardi. Bu XAVFLI edi: yangi serverda baza bo'sh
# bo'lgani uchun shu soxta mijozlar paydo bo'lardi va fayl nomida "SARBON"
# uchrasa, mijozning HUJJATLARI O'SHA SOXTA MANZILGA ketib qolishi mumkin edi.
#
# Endi baza bo'sh bo'lsa, bot ishga tushganda admin'ga ogohlantirish yuboradi
# va mijozlarni /customer_add bilan qo'shishni so'raydi.

# Ayni damda yuborilayotgan partiyalar - bir xil partiya ikki marta
# (masalan deklaratsiya ikki marta tashlansa) yuborilib ketmasligi uchun
_sending_now = set()


def format_code_display(code: str) -> str:
    """Normallashtirilgan kodni ('NG1') o'qish qulay shaklga o'tkazadi ('NG-1')."""
    m = re.match(r"^([A-Za-zА-Яа-я]+)(\d+)$", code)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return code


def format_elapsed(seconds) -> str:
    """Sekundlarni "2 kun 5 soat" ko'rinishiga o'tkazadi."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} кун {hours} соат"
    if hours:
        return f"{hours} соат {minutes} дақиқа"
    return f"{minutes} дақиқа"


def batch_display_code(code: str, batch: dict = None) -> str:
    """Fayl nomida qanday yozilgan bo'lsa, shundayligicha ("N-O-336")."""
    if batch and batch.get("display"):
        return batch["display"]
    return format_code_display(code)


# ---------- Fayl nomini xavfsiz holga keltirish ----------

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(name: str) -> str:
    """
    Telegram'dan kelgan fayl nomini diskka yozish uchun xavfsiz holga keltiradi.
    Aks holda nomida ":" yoki "/" bo'lgan fayl Windows'da xatolik berardi
    (yoki papkadan tashqariga yozib yuborish xavfi bo'lardi).
    """
    name = os.path.basename(str(name or "")).strip()
    name = _INVALID_CHARS.sub("_", name).strip(". ")
    if not name:
        return "hujjat"
    root, ext = os.path.splitext(name)
    if root.upper() in _WINDOWS_RESERVED:
        root = "_" + root
    if len(root) > 90:
        root = root[:90]
    return root + ext


def unique_path(directory: str, filename: str) -> str:
    """Bir xil nomli fayl bir-birining ustiga yozilib ketmasligi uchun."""
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(filename)
    for i in range(2, 1000):
        candidate = os.path.join(directory, f"{root} ({i}){ext}")
        if not os.path.exists(candidate):
            return candidate
    return os.path.join(directory, f"{root} ({int(time.time())}){ext}")


# ---------- Tugma ma'lumotini qisqartirish ----------
# Telegram'da callback_data 64 BAYTDAN oshmasligi kerak. Mijoz nomi uzun
# bo'lsa (ayniqsa kirill harflarida - har bir harf 2 bayt), tugma yaratishda
# xatolik chiqardi. Shuning uchun tugmaga nomning o'zi emas, qisqa "token"
# yoziladi; tugma bosilganda token bo'yicha nom qaytarib topiladi.

def _tok(value) -> str:
    return hashlib.md5(str(value).encode("utf-8")).hexdigest()[:10]


def _resolve(token: str, candidates) -> str:
    for candidate in candidates:
        if _tok(candidate) == token:
            return candidate
    return None


# ---------- Tugmali menyu (inline keyboard) ----------

def kb_main() -> InlineKeyboardMarkup:
    rows = []
    if WEBAPP_URL:
        # Mini App - jadval ko'rinishidagi boshqaruv paneli
        rows.append([InlineKeyboardButton("🖥 Бошқарув панели",
                                          web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(rows + [
        [InlineKeyboardButton("👥 Мижозлар", callback_data="menu:customers")],
        [InlineKeyboardButton("📦 Партиялар", callback_data="menu:batches")],
        [InlineKeyboardButton("❓ Ноаниқ файллар", callback_data="menu:unmatched")],
        [InlineKeyboardButton("🩺 Ҳолат", callback_data="menu:status")],
        [InlineKeyboardButton("ℹ️ Ёрдам", callback_data="menu:help")],
    ])


def kb_customers() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Мижоз қўшиш", callback_data="cust:add_start")],
        [InlineKeyboardButton("📜 Рўйхат", callback_data="cust:list")],
        [InlineKeyboardButton("🗑 Ўчириш", callback_data="cust:remove_pick")],
        [InlineKeyboardButton("🔤 Alias қўшиш", callback_data="cust:alias_pick")],
        [InlineKeyboardButton("🔗 Префикс боғлаш", callback_data="cust:prefix_pick")],
        [InlineKeyboardButton("⬅️ Бош меню", callback_data="menu:main")],
    ])


def kb_batches() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Рўйхат", callback_data="batch:list")],
        [InlineKeyboardButton("👤 Мижоз белгилаш", callback_data="batch:assign_pick")],
        [InlineKeyboardButton("📤 Қўлда юбориш", callback_data="batch:send_pick")],
        [InlineKeyboardButton("❌ Бекор қилиш", callback_data="batch:cancel_pick")],
        [InlineKeyboardButton("⬅️ Бош меню", callback_data="menu:main")],
    ])


def kb_unmatched() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Рўйхат", callback_data="unmatched:list")],
        [InlineKeyboardButton("🔗 Партияга бириктириш", callback_data="unmatched:attach_pick")],
        [InlineKeyboardButton("🗑 Ўчириш", callback_data="unmatched:delete_pick")],
        [InlineKeyboardButton("⬅️ Бош меню", callback_data="menu:main")],
    ])


def kb_back(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Орқага", callback_data=callback_data)]])


def kb_pick_customer(action_prefix: str, back_callback: str) -> InlineKeyboardMarkup:
    data = customer_store.load_customers()
    rows = [[InlineKeyboardButton(name[:60], callback_data=f"{action_prefix}:{_tok(name)}")]
            for name in sorted(data)][:MAX_BUTTONS]
    if not rows:
        rows = [[InlineKeyboardButton("(мижозлар йўқ)", callback_data="noop")]]
    rows.append([InlineKeyboardButton("⬅️ Орқага", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def kb_pick_batch(action_prefix: str, back_callback: str) -> InlineKeyboardMarkup:
    data = batch_store.all_batches()
    rows = []
    for code, b in sorted(data.items()):
        label = f"{batch_display_code(code, b)} ({b.get('customer') or '❓'}, {len(b.get('files', []))} файл)"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"{action_prefix}:{_tok(code)}")])
    rows = rows[:MAX_BUTTONS]
    if not rows:
        rows = [[InlineKeyboardButton("(партиялар йўқ)", callback_data="noop")]]
    rows.append([InlineKeyboardButton("⬅️ Орқага", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def kb_pick_unmatched(action_prefix: str, back_callback: str) -> InlineKeyboardMarkup:
    data = unmatched_store.all_unmatched()
    rows = []
    for entry_id, info in sorted(data.items()):
        label = f"{entry_id}: {info.get('filename', '?')[:40]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{action_prefix}:{entry_id}")])
    rows = rows[:MAX_BUTTONS]
    if not rows:
        rows = [[InlineKeyboardButton("(ноаниқ файллар йўқ)", callback_data="noop")]]
    rows.append([InlineKeyboardButton("⬅️ Орқага", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


# ---------- Ruxsat tekshirish ----------

def is_authorized(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False
    if chat.type != "private":
        return False
    return access_store.is_admin(user.id)


def private_only(func):
    """Bu buyruq faqat botning shaxsiy chatida, va agar ADMIN_USER_ID
    belgilangan bo'lsa, faqat o'sha odam uchun ishlaydi."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if message is None:
            return
        if update.effective_chat.type != "private":
            await message.reply_text(
                "🔒 Бу буйруқ фақат ботнинг шахсий чатида ишлайди.\n"
                "Ботга шахсий хабар ёзинг ва шу ерда қайта юборинг."
            )
            return
        if not access_store.is_admin(update.effective_user.id):
            await message.reply_text("⛔ Сизда бу буйруқдан фойдаланиш ҳуқуқи йўқ.")
            return
        return await func(update, context)
    return wrapper


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Admin'ga xabar yuboradi; yuborilmasa ham bot ishdan chiqmaydi."""
    if not config.ADMIN_USER_ID:
        return
    try:
        await context.bot.send_message(config.ADMIN_USER_ID, text)
    except TelegramError as e:
        logger.warning("Admin'ga xabar yuborilmadi: %s", e)


async def safe_send(context: ContextTypes.DEFAULT_TYPE, chat_id, text: str,
                    reply_markup=None, parse_mode=None) -> None:
    if not chat_id:
        return
    try:
        await context.bot.send_message(chat_id, text, reply_markup=reply_markup,
                                       parse_mode=parse_mode)
    except BadRequest as e:
        # Belgilash (mention) uchun HTML ishlatilganda matnda kutilmagan
        # teg bo'lsa Telegram rad etadi - xabar butunlay yo'qolmasin
        if parse_mode:
            logger.warning("HTML xabar rad etildi (%s), oddiy matn sifatida qayta yuborilmoqda", e)
            await safe_send(context, chat_id, re.sub(r"<[^>]+>", "", text),
                            reply_markup=reply_markup)
            return
        logger.warning("%s chatiga xabar yuborilmadi: %s", chat_id, e)
    except TelegramError as e:
        logger.warning("%s chatiga xabar yuborilmadi: %s", chat_id, e)


# ---------- Hujjatni yuborgan odamni belgilash ----------

def _user_name(user) -> str:
    """Telegram foydalanuvchisidan ko'rsatiladigan nom."""
    if user is None:
        return ""
    return (getattr(user, "full_name", "") or "").strip() or (user.username or "")


def _mention(user_id, name: str) -> str:
    """HTML havola — odam guruhda haqiqiy bildirishnoma oladi."""
    label = html.escape(name or "ходим")
    return f'<a href="tg://user?id={user_id}">{label}</a>' if user_id else label


def _batch_mentions(batch: dict, extra_user=None) -> str:
    """
    Partiyaga fayl tashlagan odamlarni belgilaydi (takrorlanmasdan).
    `extra_user` — deklaratsiyani hozir tashlagan odam; u birinchi turadi.
    """
    parts, seen = [], set()

    def push(uid, name):
        key = uid or (name or "").lower()
        if not key or key in seen:
            return
        seen.add(key)
        parts.append(_mention(uid, name))

    if extra_user is not None:
        push(extra_user.id, _user_name(extra_user))
    for f in (batch or {}).get("files", []):
        push(f.get("user_id"), f.get("user_name"))

    return ", ".join(parts)


async def safe_edit(query, text: str, reply_markup=None) -> None:
    """
    Xabarni tahrirlaydi. Telegram bir xil matnni qayta yozishga ruxsat bermaydi
    ("Message is not modified") - shu sabab bir tugmani ikki marta bosganda
    xatolik chiqardi. Endi bunday holat jimgina e'tiborsiz qoldiriladi.
    """
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        logger.warning("Xabarni tahrirlab bo'lmadi: %s", e)
        try:
            await query.message.reply_text(text, reply_markup=reply_markup)
        except TelegramError:
            pass


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or update.effective_chat.type != "private":
        return
    if not is_authorized(update):
        await message.reply_text(
            f"👋 Салом! Бу бот фақат администратор учун бошқарилади.\n"
            f"Сизнинг Telegram ID: {update.effective_user.id}"
        )
        return

    context.user_data.pop("awaiting", None)
    await message.reply_text(
        "👋 Салом! Мен экспорт ҳужжатлар ботиман.\n\n"
        "📋 Нима қила оламан:\n"
        "📥 Гуруҳга ташланган ҳужжатларни йиғаман (файл номидаги код бўйича)\n"
        "📨 Декларация келганда — барча ҳужжатларни битта хатга илова қилиб, "
        "мижоз emailiga юбораман\n"
        "👥 Мижозларни (ном, email, префикс, alias) бошқариш\n"
        "📦 Кутилаётган партияларни кузатиш ва бошқариш\n"
        "❓ Мижози аниқланмаган файлларни йўқотмасдан сақлаб, кейин бириктириш\n\n"
        "Қуйидаги менюдан керакли бўлимни танланг 👇",
        reply_markup=kb_main(),
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message:
        await message.reply_text(f"Сизнинг Telegram ID: {update.effective_user.id}")


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message:
        await message.reply_text(f"Ушбу чат ID: {update.effective_chat.id}")


# ---------- Holat (diagnostika) ----------

async def status_text() -> str:
    customers = customer_store.load_customers()
    batches = batch_store.all_batches()
    total_files = sum(len(b.get("files", [])) for b in batches.values())

    # Faqat fayl borligini emas, ruxsat HAQIQATAN ishlayotganini tekshiramiz.
    # Tarmoqqa murojaat bo'lgani uchun alohida oqimda - bot muzlab qolmasin.
    gmail_ok, gmail_msg = await asyncio.to_thread(gmail_sender.check_credentials)
    gmail_line = ("✅ " if gmail_ok else "❌ ") + gmail_msg

    groups = access_store.all_groups()
    if groups:
        group_line = "\n" + "\n".join(
            f"   • {gid} — {i.get('title') or '—'}" for gid, i in sorted(groups.items()))
    else:
        group_line = "белгиланмаган (барча гуруҳлардан қабул қилади)"

    admins = access_store.all_admins()
    admin_line = f"{len(access_store.admin_ids())} та · эгаси {access_store.owner_id()}"
    if admins:
        admin_line += "\n" + "\n".join(
            f"   • {uid} — {i.get('name') or '—'}" for uid, i in sorted(admins.items()))

    return (
        "🩺 Бот ҳолати\n\n"
        f"Гуруҳлар: {group_line}\n"
        f"Админлар: {admin_line}\n"
        f"Gmail: {gmail_line}\n\n"
        f"👥 Мижозлар: {len(customers)} ta\n"
        f"📦 Кутилаётган партиялар: {len(batches)} та ({total_files} файл)\n"
        f"❓ Ноаниқ файллар: {unmatched_store.count()} ta\n\n"
        "Агар бот гуруҳдаги файлларни кўрмаётган бўлса:\n"
        "1) Гуруҳда /chatid ёзиб, юқоридаги \"Гуруҳ ID\" билан солиштиринг\n"
        "2) @BotFather → /setprivacy → Disable қилинганини текширинг"
    )


# ---------- Adminlar va guruhlarni boshqarish ----------

def _owner_only(func):
    """Faqat .env dagi ADMIN_USER_ID — admin ro'yxatini u boshqaradi."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if message is None:
            return
        if not access_store.is_owner(update.effective_user.id):
            await message.reply_text(
                "⛔ Админ рўйхатини фақат ботнинг ЭГАСИ ўзгартира олади."
            )
            return
        return await func(update, context)
    return wrapper


def admins_text() -> str:
    lines = [f"👤 Админлар:\n", f"• {access_store.owner_id()} — ЭГАСИ (ўчириб бўлмайди)"]
    for uid, info in sorted(access_store.all_admins().items()):
        name = info.get("name") or "—"
        lines.append(f"• {uid} — {name}")
    lines.append("\nҚўшиш: /admin_add ID [исм]\nЎчириш: /admin_remove ID")
    lines.append("Кимнингдир ID сини билиш учун унга /myid ни юборишни айтинг.")
    return "\n".join(lines)


@private_only
async def admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(admins_text())


@_owner_only
async def admin_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /admin_add 123456789 Aziz"""
    message = update.effective_message
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.reply_text(
            "Формат: /admin_add ID [исм]\nМасалан: /admin_add 123456789 Aziz\n\n"
            "ID ни билиш учун ўша одам ботга /myid ёзсин."
        )
        return
    uid = int(parts[1])
    name = " ".join(parts[2:])
    if access_store.is_owner(uid):
        await message.reply_text("Бу аллақачон ботнинг эгаси.")
        return
    if access_store.add_admin(uid, name):
        await message.reply_text(f"✅ Админ қўшилди: {uid} {name}".strip())
        await safe_send(context, uid,
                        "✅ Сизга экспорт ҳужжатлар ботини бошқариш ҳуқуқи берилди.\n"
                        "Бошлаш учун /start ёзинг.")
    else:
        await message.reply_text("Бу фойдаланувчи аллақачон админ.")


@_owner_only
async def admin_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /admin_remove 123456789"""
    message = update.effective_message
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.reply_text("Формат: /admin_remove ID")
        return
    uid = int(parts[1])
    if access_store.is_owner(uid):
        await message.reply_text("⛔ Бот эгасини рўйхатдан ўчириб бўлмайди.")
        return
    if access_store.remove_admin(uid):
        await message.reply_text(f"🗑 Админ ўчирилди: {uid}")
    else:
        await message.reply_text("Бундай админ топилмади.")


def groups_text() -> str:
    groups = access_store.all_groups()
    if not groups:
        return ("📢 Гуруҳлар рўйхати бўш — бот БАРЧА гуруҳлардан ҳужжат қабул қилади.\n\n"
                "Чеклаш учун керакли гуруҳда /group_add ёзинг.")
    lines = ["📢 Ҳужжат қабул қилинадиган гуруҳлар:\n"]
    for gid, info in sorted(groups.items()):
        lines.append(f"• {gid} — {info.get('title') or '—'}")
    lines.append("\nҚўшиш: керакли гуруҳда /group_add ёзинг")
    lines.append("Ўчириш: /group_remove ID")
    return "\n".join(lines)


@private_only
async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(groups_text())


async def group_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """GURUHDA yoziladi: /group_add — shu guruhni ro'yxatga qo'shadi."""
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat.type not in ("group", "supergroup"):
        await message.reply_text(
            "Бу буйруқ ГУРУҲДА ёзилади — қайси гуруҳни қўшмоқчи бўлсангиз, "
            "ўша гуруҳда /group_add деб ёзинг."
        )
        return
    if not access_store.is_admin(update.effective_user.id):
        await message.reply_text("⛔ Буни фақат бот админи қила олади.")
        return

    if access_store.add_group(chat.id, chat.title or ""):
        await message.reply_text(
            f"✅ Бу гуруҳ рўйхатга қўшилди.\n"
            f"Номи: {chat.title}\nID: {chat.id}\n\n"
            f"Энди бу ерга ташланган ҳужжатлар қабул қилинади."
        )
        await notify_admin(context, f"➕ Янги гуруҳ қўшилди: {chat.title} ({chat.id})")
    else:
        await message.reply_text("Бу гуруҳ аллақачон рўйхатда.")


async def group_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda: /group_remove  ·  Shaxsiy chatda: /group_remove ID"""
    message = update.effective_message
    chat = update.effective_chat
    if message is None or not access_store.is_admin(update.effective_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) > 1 and parts[1].lstrip("-").isdigit():
        gid = int(parts[1])
    elif chat.type in ("group", "supergroup"):
        gid = chat.id
    else:
        await message.reply_text("Формат: /group_remove ID\nЁки керакли гуруҳда /group_remove ёзинг.")
        return

    if access_store.remove_group(gid):
        await message.reply_text(f"🗑 Гуруҳ рўйхатдан олиб ташланди: {gid}")
    else:
        await message.reply_text("Бундай гуруҳ рўйхатда йўқ.")


@private_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(await status_text())


# ---------- Mijozlarni boshqarish (shaxsiy chatda) ----------

def _validate_emails(emails: list):
    """Qaytaradi: (to'g'ri_emaillar, xato_emaillar)"""
    valid, invalid = [], []
    for email in emails:
        (valid if customer_store.is_valid_email(email) else invalid).append(email)
    return valid, invalid


@private_only
async def customer_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /customer_add NOMI | email1, email2"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2 or "|" not in payload[1]:
        await message.reply_text(
            "Формат: /customer_add НОМИ | email1, email2\n\n"
            "Masalan:\n/customer_add SARBON | galaxy@gmail.com, edwdw@mail.ru"
        )
        return

    name_part, emails_part = payload[1].split("|", 1)
    name = name_part.strip()
    emails = [e.strip() for e in emails_part.split(",") if e.strip()]

    if not name or not emails:
        await message.reply_text("Хатолик: компания номи ёки email бўш бўлмаслиги керак.")
        return

    valid, invalid = _validate_emails(emails)
    if invalid:
        await message.reply_text(
            "❌ Бу манзиллар email кўринишида эмас: " + ", ".join(invalid) +
            "\n\nТўғрилаб қайта юборинг."
        )
        return

    customer_store.add_customer(name, valid)
    await message.reply_text(f"✅ Мижоз сақланди: {name.upper()}\nEmaillar: {', '.join(valid)}")


@private_only
async def customer_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /customer_remove NOMI"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await message.reply_text("Формат: /customer_remove НОМИ")
        return
    name = payload[1].strip()
    if customer_store.remove_customer(name):
        session_store.forget_customer(name.strip().upper())
        await message.reply_text(f"🗑 Ўчирилди: {name.upper()}")
    else:
        await message.reply_text(f"\"{name}\" номли мижоз топилмади.")


def customers_text() -> str:
    data = customer_store.load_customers()
    if not data:
        return "Мижозлар рўйхати бўш."
    lines = ["📋 Мижозлар рўйхати:\n"]
    for name, info in sorted(data.items()):
        extras = []
        if info.get("prefixes"):
            extras.append(f"префикс: {', '.join(info['prefixes'])}")
        if info.get("aliases"):
            extras.append(f"alias: {', '.join(info['aliases'])}")
        extra_str = f" [{'; '.join(extras)}]" if extras else ""
        emails = ", ".join(info.get("emails", [])) or "⚠️ email йўқ"
        lines.append(f"• {name} — {emails}{extra_str}")
    return "\n".join(lines)


@private_only
async def customer_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(customers_text())


@private_only
async def customer_alias_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /customer_alias NOMI | ALIAS1, ALIAS2"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2 or "|" not in payload[1]:
        await message.reply_text(
            "Формат: /customer_alias НОМИ | ALIAS1, ALIAS2\n\n"
            "Масалан: /customer_alias VIZOR STEP-ORC | VIZOR STEPORC, VIZOR\n\n"
            "Файл номида НОМИ ёки шу aliaslarдан бири учраса, мижоз автоматик топилади."
        )
        return
    name_part, aliases_part = payload[1].split("|", 1)
    name = name_part.strip()
    aliases = [a.strip() for a in aliases_part.split(",") if a.strip()]

    if not customer_store.exists(name):
        await message.reply_text(f"\"{name}\" номли мижоз топилмади. Аввал /customer_add билан қўшинг.")
        return

    added, skipped = _apply_aliases(name, aliases)
    text = f"✅ {name.upper()} учун aliaslar қўшилди: {', '.join(added)}" if added \
        else "Ҳеч қандай alias қўшилмади."
    if skipped:
        text += (f"\n⚠️ Жуда қисқа (хато мос келиб қолиши мумкин) бўлгани учун "
                 f"қабул қилинмади: {', '.join(skipped)}")
    await message.reply_text(text)


def _apply_aliases(name: str, aliases: list):
    """Qaytaradi: (qo'shilganlar, rad etilganlar)"""
    added, skipped = [], []
    for alias in aliases:
        if len(alias.strip()) < customer_store.MIN_NAME_MATCH_LEN:
            skipped.append(alias)
            continue
        if customer_store.add_alias(alias, name):
            added.append(alias)
        else:
            skipped.append(alias)
    return added, skipped


@private_only
async def prefix_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /prefix_add PREFIKS | NOMI"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2 or "|" not in payload[1]:
        await message.reply_text(
            "Формат: /prefix_add ПРЕФИКС | MIJOZ_NOMI\n\n"
            "Masalan: /prefix_add NG | VIZOR STEP-ORC\n\n"
            "(Мижоз аввал /customer_add билан қўшилган бўлиши керак)"
        )
        return
    prefix_part, name_part = payload[1].split("|", 1)
    prefix = prefix_part.strip()
    name = name_part.strip()

    if customer_store.add_prefix(prefix, name):
        clean = re.sub(r"[^A-Za-zА-Яа-я]", "", prefix).upper()
        await message.reply_text(
            f"✅ Префикс боғланди: {clean}- -> {name.upper()}\n"
            f"Энди шу префикс билан бошланган барча кодлар ({clean}-1, "
            f"{clean}-2 ва ҳ.к.) автоматик шу мижозга юборилади."
        )
    else:
        await message.reply_text(
            f"Боғланмади. \"{name}\" номли мижоз мавжудлигини ва префикс бўш "
            f"эмаслигини текширинг (/customer_list)."
        )


@private_only
async def prefix_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /prefix_remove PREFIKS"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await message.reply_text("Формат: /prefix_remove ПРЕФИКС")
        return
    prefix = payload[1].strip()
    if customer_store.remove_prefix(prefix):
        await message.reply_text(f"🗑 Префикс ўчирилди: {prefix.upper()}")
    else:
        await message.reply_text(f"\"{prefix}\" префикси топилмади.")


# ---------- Partiyalarni boshqarish (shaxsiy chatda) ----------

def batches_text() -> str:
    data = batch_store.all_batches()
    if not data:
        return "Ҳозирча кутилаётган партия йўқ."
    lines = ["📦 Кутилаётган партиялар:\n"]
    now = time.time()
    for code, batch in sorted(data.items()):
        customer = batch.get("customer") or "❓ aniqlanmagan"
        file_count = len(batch.get("files", []))
        elapsed = format_elapsed(now - batch.get("created_at", now))
        lines.append(
            f"• {batch_display_code(code, batch)} [{code}] -> {customer} "
            f"({file_count} та файл, {elapsed} кутмоқда)"
        )
    return "\n".join(lines)


@private_only
async def batches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(batches_text())


def unmatched_text(with_hint: bool = False) -> str:
    data = unmatched_store.all_unmatched()
    if not data:
        return "Мижози аниқланмаган файллар йўқ."
    lines = ["❓ Мижози аниқланмаган файллар:\n"]
    now = time.time()
    for entry_id, info in sorted(data.items()):
        age = format_elapsed(now - info.get("created_at", now))
        lines.append(f"• {entry_id}: {info.get('filename', '?')} ({age} oldin)")
    if with_hint:
        lines.append("\nПартияга бириктириш: /batch_attach КОД | ID\nМасалан: /batch_attach NO336 | u1")
        lines.append("Кераксизини ўчириш: /unmatched_delete ID")
    return "\n".join(lines)


@private_only
async def unmatched_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(unmatched_text(with_hint=True))


@private_only
async def unmatched_delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /unmatched_delete ID"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await message.reply_text("Format: /unmatched_delete ID\nMasalan: /unmatched_delete u1")
        return
    entry_id = payload[1].strip()
    if unmatched_store.remove(entry_id, delete_file=True):
        await message.reply_text(f"🗑 {entry_id} ўчирилди.")
    else:
        await message.reply_text(f"\"{entry_id}\" ID ли файл топилмади.")


def _attach_unmatched(entry_id: str, code: str, force_type: str = None):
    """
    Noaniq faylni partiyaga biriktiradi. Qaytaradi: entry yoki None.

    `force_type` berilsa (Mini App'da yetishmagan hujjat ustiga bosilganda),
    fayl nomiga qaramasdan AYNAN shu tur sifatida yoziladi.
    """
    entry = unmatched_store.get(entry_id)
    if not entry:
        return None

    # Mijozni aniqlash - oddiy oqimdagi kabi UCH usul bilan:
    # nom/alias -> prefiks -> shu kod bo'yicha eslab qolingan mijoz.
    # (Ilgari prefiks tekshirilmasdi, shuning uchun "NGS" prefiksi bo'lgan
    #  fayllar biriktirilsa ham mijozsiz qolib ketardi.)
    customer_name, _ = customer_store.find_by_filename(entry["filename"])
    parsed_code = session_store.parse(entry["filename"])
    if not customer_name and parsed_code and parsed_code.get("prefix"):
        customer_name = customer_store.find_by_prefix(parsed_code["prefix"])
    if not customer_name:
        customer_name = session_store.recall(code)
    if customer_name:
        session_store.remember(code, customer_name)

    # Hujjat turini aniqlaymiz. Aniqlanmasa "MANUAL" deb belgilaymiz -
    # admin bu faylni ATAYLAB biriktirgani uchun u xatga qo'shiladi
    # (avtomatik oqimda turi tanilmagan fayllar qabul qilinmaydi).
    parsed = session_store.parse(entry["filename"])
    doc_type, truck = (None, None)
    if parsed:
        doc_type, truck = doc_types.detect(parsed["remainder"], parsed["extension"])
        if parsed["is_declaration"]:
            doc_type = "DEKL"
    if force_type:
        doc_type = force_type
    elif doc_type is None:
        doc_type = "MANUAL"

    batch_store.add_file(
        code, entry["filename"], entry["path"],
        file_unique_id=entry.get("file_unique_id"), customer=customer_name,
        doc_type=doc_type, truck=truck,
    )
    unmatched_store.remove(entry_id)
    return entry


@private_only
async def batch_attach_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /batch_attach KOD | ID  (masalan /batch_attach NO336 | u1)"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2 or "|" not in payload[1]:
        await message.reply_text(
            "Format: /batch_attach KOD | ID\nMasalan: /batch_attach NO336 | u1\n\n"
            "ID ларни /unmatched орқали кўрасиз."
        )
        return
    code_part, id_part = payload[1].split("|", 1)
    code = re.sub(r"[^A-Za-z0-9А-Яа-я]", "", code_part).upper()
    entry_id = id_part.strip()

    if not code:
        await message.reply_text("Партия коди бўш бўлмаслиги керак.")
        return

    entry = _attach_unmatched(entry_id, code)
    if not entry:
        await message.reply_text(f"\"{entry_id}\" ID ли файл топилмади. /unmatched билан текширинг.")
        return

    await message.reply_text(f"✅ \"{entry['filename']}\" endi {code} партиясига бириктирилди.")


@private_only
async def unmatched_attach_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Format: /unmatched_attach_all
    Barcha noaniq fayllarni fayl nomidagi kod bo'yicha o'z partiyalariga
    biriktiradi. Mijozlar ro'yxati keyinroq to'ldirilganda qo'l keladi:
    o'nlab faylni bitta-bitta biriktirib o'tirishning hojati qolmaydi.
    """
    message = update.effective_message
    data = unmatched_store.all_unmatched()
    if not data:
        await message.reply_text("Ноаниқ файллар йўқ.")
        return

    attached, skipped = {}, []
    for entry_id, info in sorted(data.items()):
        parsed = session_store.parse(info.get("filename", ""))
        if not parsed:
            skipped.append(info.get("filename", entry_id))
            continue
        code = parsed["code"]
        if _attach_unmatched(entry_id, code):
            attached.setdefault(code, 0)
            attached[code] += 1
        else:
            skipped.append(info.get("filename", entry_id))

    if not attached:
        await message.reply_text(
            "Ҳеч қайси файл бириктирилмади (файл номларида код топилмади)."
        )
        return

    lines = ["✅ Бириктирилди:"]
    for code, count in sorted(attached.items()):
        batch = batch_store.get_batch(code)
        customer = (batch or {}).get("customer") or "❓ мижоз аниқланмаган"
        lines.append(f"   • {code} -> {customer}: {count} та файл "
                     f"[{doc_types.progress_line((batch or {}).get('files', []))}]")
    if skipped:
        lines.append(f"\n⚠️ Бириктирилмади: {', '.join(skipped)}")
    lines.append("\nЮбориш учун декларацияни гуруҳга қайта ташланг, "
                 "yoki /batch_send KOD.")
    await message.reply_text("\n".join(lines))


@private_only
async def batch_assign_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /batch_assign KOD | NOMI"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2 or "|" not in payload[1]:
        await message.reply_text(
            "Формат: /batch_assign КОД | MIJOZ_NOMI\nМасалан: /batch_assign NO336 | VIZOR STEP-ORC"
        )
        return
    code_part, name_part = payload[1].split("|", 1)
    code = re.sub(r"[^A-Za-z0-9А-Яа-я]", "", code_part).upper()
    name = name_part.strip().upper()

    if not customer_store.exists(name):
        await message.reply_text(f"\"{name}\" номли мижоз топилмади. Аввал /customer_add билан қўшинг.")
        return
    if batch_store.set_customer(code, name):
        session_store.remember(code, name)
        await message.reply_text(f"✅ {code} партияси энди {name} га боғланди. Юбориш учун: /batch_send {code}")
    else:
        await message.reply_text(f"\"{code}\" кодли партия топилмади. Рўйхат: /batches")


@private_only
async def batch_send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /batch_send KOD - deklaratsiyani kutmasdan qo'lda yuborish"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await message.reply_text("Format: /batch_send KOD")
        return
    code = re.sub(r"[^A-Za-z0-9А-Яа-я]", "", payload[1]).upper()
    await _finalize_and_send(code, context, notify_chat_id=update.effective_chat.id)


@private_only
async def batch_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Format: /batch_cancel KOD - partiyani bekor qilish (yuborilmaydi, fayllar o'chiriladi)"""
    message = update.effective_message
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await message.reply_text("Format: /batch_cancel KOD")
        return
    code = re.sub(r"[^A-Za-z0-9А-Яа-я]", "", payload[1]).upper()
    if batch_store.get_batch(code):
        batch_store.clear_batch(code)
        await message.reply_text(f"🗑 {code} партияси бекор қилинди.")
    else:
        await message.reply_text(f"\"{code}\" кодли партия топилмади.")


HELP_TEXT = (
    "📦 Экспорт ҳужжатлар боти\n\n"
    "КОМПЛЕКТ (7 та ҳужжат): INV, SPETS, ST, FITO, AKT, CMR, TIR\n"
    "Бот ҳаммаси тўпланмагунча почтага ЮБОРМАЙДИ.\n\n"
    "NOMLASH TARTIBI (masalan NGS-25, fura 565):\n"
    "  NGS-25 GALLAKTIKA ZAPIT 565.xlsx\n"
    "  NGS25INV.pdf\n"
    "  NGS25SPETS.pdf\n"
    "  NGS-25 ST 565.jpg     NGS-25 FITO 565.jpg\n"
    "  NGS-25 AKT 565.jpg    NGS-25 CMR 565.jpg\n"
    "  NGS-25 TIR 565.jpg\n"
    "  NGS-25.pdf   ← декларация, шундан кейин почтага кетади\n\n"
    "Бот ҳар бир ҳужжат келганда қайсилари борлигини ва нимаси "
    "етишмаётганини гуруҳда ёзиб боради. Файл номи хато бўлса "
    "(фура рақами бошқа, тури ёзилмаган) огоҳлантиради.\n\n"
    "Бошқарув учун /start босинг — тугмали меню чиқади.\n\n"
    "Матн буйруқлар (агар керак бўлса):\n"
    "/customer_add НОМИ | email1, email2\n"
    "/customer_remove НОМИ\n"
    "/customer_list\n"
    "/customer_alias НОМИ | ALIAS1, ALIAS2\n"
    "/prefix_add ПРЕФИКС | НОМИ\n"
    "/prefix_remove ПРЕФИКС\n"
    "/batches\n"
    "/batch_assign КОД | НОМИ\n"
    "/batch_send KOD\n"
    "/batch_cancel KOD\n"
    "/unmatched\n"
    "/batch_attach KOD | ID\n"
    "/unmatched_attach_all — барча ноаниқ файлларни коди бўйича бириктириш\n"
    "/unmatched_delete ID\n"
    "/admins — админлар рўйхати\n"
    "/admin_add ID [исм] — админ қўшиш (фақат бот эгаси)\n"
    "/admin_remove ID — админни олиб ташлаш (фақат бот эгаси)\n"
    "/groups — гуруҳлар рўйхати\n"
    "/group_add — ШУ гуруҳни қўшиш (гуруҳда ёзилади)\n"
    "/group_remove [ID] — гуруҳни олиб ташлаш\n"
    "/status — бот ва созламалар ҳолати\n"
    "/gmail_check — Gmail рухсати ишлаяптими, текшириш\n"
    "/myid — Telegram ID ингизни кўриш\n"
    "/chatid — гуруҳ чат ID сини кўриш (гуруҳда ёзилади)"
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message:
        await message.reply_text(HELP_TEXT)


# ---------- Tugma bosilganda ishlaydigan router ----------

async def _group_question_router(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 query, data: str):
    """Guruhda berilgan HA/YO'Q savollariga javobni qayta ishlaydi."""
    parts = data.split(":")
    if len(parts) < 3:
        return
    action, answer, token = parts[0], parts[1], parts[2]
    who = update.effective_user.first_name if update.effective_user else "kimdir"

    # ---- Allaqachon yuborilgan hujjatni qayta yuborish ----
    if action == "resend":
        code = _resolve(token, _pending_resend)
        if not code:
            await safe_edit(query, "⌛ Бу саволга аллақачон жавоб берилган.")
            return
        if answer == "no":
            count = _discard_resend(code)
            await safe_edit(query, f"❌ Қайта юборилмади ({count} та файл эътиборсиз қолдирилди).\n"
                                   f"Javob berdi: {who}")
            return

        count, has_declaration, chat_id = await _apply_resend(context, code)
        batch = batch_store.get_batch(code)
        display = batch_display_code(code, batch) if batch else code
        await safe_edit(
            query,
            f"✅ \"{display}\" қайта юборишга қабул қилинди ({count} та файл).\n"
            f"Javob berdi: {who}"
        )
        if has_declaration:
            await _on_declaration(update, context, code)
        elif batch:
            await safe_send(
                context, chat_id or update.effective_chat.id,
                f"📥 \"{display}\" [{doc_types.progress_line(batch['files'])}]\n"
                f"{doc_types.summary(batch['files'])}\n\n"
                f"Юбориш учун декларацияни ({display}.pdf) ташланг."
            )
        return

    # ---- Komplekt to'liq emas, baribir yuborilsinmi ----
    if action == "force":
        code = _resolve(token, batch_store.all_batches())
        if not code:
            await safe_edit(query, "⌛ Бу партия энди мавжуд эмас (юборилган ёки бекор қилинган).")
            return
        batch = batch_store.get_batch(code)
        display = batch_display_code(code, batch)
        if answer == "no":
            await safe_edit(
                query,
                f"⏳ \"{display}\" кутилмоқда. Етишмаган ҳужжатларни ташлаб, "
                f"декларацияни қайта юборинг.\nЖавоб берди: {who}"
            )
            return

        missing = doc_types.missing_types(batch["files"])
        await safe_edit(
            query,
            f"⚠️ \"{display}\" ТЎЛИҚ ЭМАС ҳолда юборилмоқда.\n"
            f"Етишмаяпти: {', '.join(missing) or '—'}\nJavob berdi: {who}"
        )
        await _finalize_and_send(code, context, notify_chat_id=update.effective_chat.id)
        return


def _can_answer_in_group(update: Update) -> bool:
    """
    Guruhda beriladigan savollarga (qayta yuborilsinmi? to'liq emas, baribir
    yuborilsinmi?) guruh a'zolari ham javob bera oladi - bu ularning kundalik
    ishi. Boshqa barcha boshqaruv esa admin'ning shaxsiy chatida qoladi.
    """
    chat = update.effective_chat
    if chat is None:
        return False
    if is_authorized(update):
        return True
    return chat.type in ("group", "supergroup") and access_store.is_allowed_group(chat.id)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    # Guruhdagi savollar - alohida, admin bo'lish shart emas
    if data.startswith(("resend:", "force:")):
        if not _can_answer_in_group(update):
            return
        await _group_question_router(update, context, query, data)
        return

    if not is_authorized(update):
        await safe_edit(query, "⛔ Сизда бу бўлимдан фойдаланиш ҳуқуқи йўқ.")
        return

    if data == "noop":
        return

    # Boshqa tugma bosilishi bilan yarim qolgan matn kiritish bekor bo'ladi
    context.user_data.pop("awaiting", None)

    # ---- Bosh menyular ----
    if data == "menu:main":
        await safe_edit(query, "Керакли бўлимни танланг 👇", kb_main())
        return
    if data == "menu:customers":
        await safe_edit(query, "👥 Мижозлар бўлими:", kb_customers())
        return
    if data == "menu:batches":
        await safe_edit(query, "📦 Партиялар бўлими:", kb_batches())
        return
    if data == "menu:unmatched":
        await safe_edit(query, "❓ Ноаниқ файллар бўлими:", kb_unmatched())
        return
    if data == "menu:status":
        await safe_edit(query, "🩺 Tekshirilmoqda...")
        await safe_edit(query, await status_text(), kb_back("menu:main"))
        return
    if data == "menu:help":
        await safe_edit(query, HELP_TEXT, kb_back("menu:main"))
        return

    # ---- Mijozlar ----
    if data == "cust:list":
        await safe_edit(query, customers_text(), kb_back("menu:customers"))
        return

    if data == "cust:add_start":
        context.user_data["awaiting"] = ("add_customer_name", {})
        await safe_edit(
            query,
            "➕ Янги мижоз қўшиш\n\nКомпания номини ёзиб юборинг (масалан: SARBON):",
            kb_back("menu:customers"),
        )
        return

    if data == "cust:remove_pick":
        await safe_edit(query, "🗑 Қайси мижозни ўчирамиз?",
                        kb_pick_customer("cust:remove", "menu:customers"))
        return
    if data.startswith("cust:remove:"):
        name = _resolve(data.split(":", 2)[2], customer_store.load_customers())
        if not name:
            await safe_edit(query, "Бу мижоз аллақачон ўчирилган.", kb_customers())
            return
        customer_store.remove_customer(name)
        session_store.forget_customer(name)
        await safe_edit(query, f"🗑 Ўчирилди: {name}", kb_customers())
        return

    if data == "cust:alias_pick":
        await safe_edit(query, "🔤 Қайси мижозга alias қўшамиз?",
                        kb_pick_customer("cust:alias_for", "menu:customers"))
        return
    if data.startswith("cust:alias_for:"):
        name = _resolve(data.split(":", 2)[2], customer_store.load_customers())
        if not name:
            await safe_edit(query, "Мижоз топилмади (рўйхат янгиланган).", kb_customers())
            return
        context.user_data["awaiting"] = ("add_alias", {"name": name})
        await safe_edit(
            query,
            f"🔤 {name} учун alias(лар)ни ёзинг (бир нечтаси бўлса вергул билан ажратинг):\n\n"
            f"Masalan: VIZOR STEPORC, VIZOR",
            kb_back("menu:customers"),
        )
        return

    if data == "cust:prefix_pick":
        await safe_edit(query, "🔗 Қайси мижозга префикс боғлаймиз?",
                        kb_pick_customer("cust:prefix_for", "menu:customers"))
        return
    if data.startswith("cust:prefix_for:"):
        name = _resolve(data.split(":", 2)[2], customer_store.load_customers())
        if not name:
            await safe_edit(query, "Мижоз топилмади (рўйхат янгиланган).", kb_customers())
            return
        context.user_data["awaiting"] = ("add_prefix", {"name": name})
        await safe_edit(query, f"🔗 {name} учун префиксни ёзинг (масалан: NG):",
                        kb_back("menu:customers"))
        return

    # ---- Partiyalar ----
    if data == "batch:list":
        await safe_edit(query, batches_text(), kb_back("menu:batches"))
        return

    if data == "batch:send_pick":
        await safe_edit(query, "📤 Қайси партияни юборамиз?",
                        kb_pick_batch("batch:send", "menu:batches"))
        return
    if data.startswith("batch:send:"):
        code = _resolve(data.split(":", 2)[2], batch_store.all_batches())
        if not code:
            await safe_edit(query, "Бу партия энди мавжуд эмас.", kb_batches())
            return
        await safe_edit(query, f"📤 {code} yuborilmoqda...")
        await _finalize_and_send(code, context, notify_chat_id=update.effective_chat.id)
        return

    if data == "batch:cancel_pick":
        await safe_edit(query, "❌ Қайси партияни бекор қиламиз?",
                        kb_pick_batch("batch:cancel_ask", "menu:batches"))
        return
    if data.startswith("batch:cancel_ask:"):
        token = data.split(":", 2)[2]
        code = _resolve(token, batch_store.all_batches())
        if not code:
            await safe_edit(query, "Бу партия энди мавжуд эмас.", kb_batches())
            return
        batch = batch_store.get_batch(code)
        await safe_edit(
            query,
            f"❌ \"{batch_display_code(code, batch)}\" партияси бекор қилинсинми?\n"
            f"{len(batch.get('files', []))} та файл бутунлай ўчирилади ва тиклаб бўлмайди.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Ҳа, бекор қилинсин", callback_data=f"batch:cancel_do:{token}")],
                [InlineKeyboardButton("⬅️ Йўқ, орқага", callback_data="menu:batches")],
            ]),
        )
        return
    if data.startswith("batch:cancel_do:"):
        code = _resolve(data.split(":", 2)[2], batch_store.all_batches())
        if not code:
            await safe_edit(query, "Бу партия энди мавжуд эмас.", kb_batches())
            return
        batch_store.clear_batch(code)
        await safe_edit(query, f"🗑 {code} партияси бекор қилинди.", kb_batches())
        return

    if data == "batch:assign_pick":
        await safe_edit(query, "👤 Қайси партияга мижоз белгилаймиз?",
                        kb_pick_batch("batch:assign_batch", "menu:batches"))
        return
    if data.startswith("batch:assign_batch:"):
        token = data.split(":", 2)[2]
        code = _resolve(token, batch_store.all_batches())
        if not code:
            await safe_edit(query, "Бу партия энди мавжуд эмас.", kb_batches())
            return
        await safe_edit(
            query,
            f"👤 \"{code}\" учун қайси мижозни белгилаймиз?",
            kb_pick_customer(f"batch:assign_customer:{token}", "menu:batches"),
        )
        return
    if data.startswith("batch:assign_customer:"):
        parts = data.split(":")
        if len(parts) < 4:
            await safe_edit(query, "Тугма маълумоти бузилган, қайтадан уриниб кўринг.", kb_batches())
            return
        code = _resolve(parts[2], batch_store.all_batches())
        name = _resolve(parts[3], customer_store.load_customers())
        if not code or not name:
            await safe_edit(query, "Партия ёки мижоз топилмади (рўйхат янгиланган).", kb_batches())
            return
        batch_store.set_customer(code, name)
        session_store.remember(code, name)
        await safe_edit(query, f"✅ {code} партияси энди {name} га боғланди.", kb_batches())
        return

    # ---- Noaniq fayllar ----
    if data == "unmatched:list":
        await safe_edit(query, unmatched_text(), kb_back("menu:unmatched"))
        return

    if data == "unmatched:attach_pick":
        await safe_edit(query, "🔗 Қайси файлни бириктирамиз?",
                        kb_pick_unmatched("unmatched:attach_file", "menu:unmatched"))
        return
    if data.startswith("unmatched:attach_file:"):
        entry_id = data.split(":", 2)[2]
        if not unmatched_store.get(entry_id):
            await safe_edit(query, "Бу файл аллақачон бириктирилган ёки ўчирилган.", kb_unmatched())
            return
        await safe_edit(
            query,
            "🔗 Қайси партияга бириктирамиз?",
            kb_pick_batch(f"unmatched:attach_batch:{entry_id}", "menu:unmatched"),
        )
        return
    if data.startswith("unmatched:attach_batch:"):
        parts = data.split(":")
        if len(parts) < 4:
            await safe_edit(query, "Тугма маълумоти бузилган, қайтадан уриниб кўринг.", kb_unmatched())
            return
        entry_id = parts[2]
        code = _resolve(parts[3], batch_store.all_batches())
        if not code:
            await safe_edit(query, "Бу партия энди мавжуд эмас.", kb_unmatched())
            return
        entry = _attach_unmatched(entry_id, code)
        if not entry:
            await safe_edit(query, "Бу файл аллақачон бириктирилган ёки топилмади.", kb_unmatched())
            return
        await safe_edit(query, f"✅ \"{entry['filename']}\" endi {code} партиясига бириктирилди.",
                        kb_unmatched())
        return

    if data == "unmatched:delete_pick":
        await safe_edit(query, "🗑 Қайси файлни ўчирамиз?",
                        kb_pick_unmatched("unmatched:delete", "menu:unmatched"))
        return
    if data.startswith("unmatched:delete:"):
        entry_id = data.split(":", 2)[2]
        if unmatched_store.remove(entry_id, delete_file=True):
            await safe_edit(query, f"🗑 {entry_id} ўчирилди.", kb_unmatched())
        else:
            await safe_edit(query, "Бу файл аллақачон ўчирилган.", kb_unmatched())
        return

    logger.warning("Noma'lum tugma: %s", data)


# ---------- Bosqichma-bosqich matn kiritish (mijoz qo'shish, alias, prefiks) ----------

async def text_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not is_authorized(update):
        return

    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return  # oddiy matn, hech qanday buyruq kutilmayapti - e'tiborsiz qoldiramiz

    state, payload = awaiting
    text = (message.text or "").strip()
    if not text:
        return

    if state == "add_customer_name":
        context.user_data["awaiting"] = ("add_customer_emails", {"name": text})
        await message.reply_text(
            f"✅ Номи: {text}\n\nЭнди email(лар)ни ёзинг (бир нечтаси бўлса вергул билан):"
        )
        return

    if state == "add_customer_emails":
        name = payload["name"]
        emails = [e.strip() for e in text.split(",") if e.strip()]
        valid, invalid = _validate_emails(emails)
        if invalid:
            await message.reply_text(
                "❌ Бу манзиллар email кўринишида эмас: " + ", ".join(invalid) +
                "\n\nТўғрилаб қайта ёзинг (ёки /start билан бекор қилинг)."
            )
            return  # "awaiting" saqlanib qoladi - qayta urinish mumkin
        if not valid:
            await message.reply_text("Камида битта email киритинг.")
            return
        customer_store.add_customer(name, valid)
        context.user_data.pop("awaiting", None)
        await message.reply_text(
            f"✅ Мижоз сақланди: {name.upper()}\nEmaillar: {', '.join(valid)}",
            reply_markup=kb_customers(),
        )
        return

    if state == "add_alias":
        name = payload["name"]
        aliases = [a.strip() for a in text.split(",") if a.strip()]
        added, skipped = _apply_aliases(name, aliases)
        context.user_data.pop("awaiting", None)
        reply = f"✅ {name} учун aliaslar қўшилди: {', '.join(added)}" if added \
            else "⚠️ Ҳеч қандай alias қўшилмади."
        if skipped:
            reply += (f"\n⚠️ Қабул қилинмади (камида "
                      f"{customer_store.MIN_NAME_MATCH_LEN} та белги бўлиши керак): "
                      f"{', '.join(skipped)}")
        await message.reply_text(reply, reply_markup=kb_customers())
        return

    if state == "add_prefix":
        name = payload["name"]
        clean = re.sub(r"[^A-Za-zА-Яа-я]", "", text).upper()
        if not clean:
            await message.reply_text("Префикс фақат ҳарфлардан иборат бўлиши керак (масалан: NG).")
            return
        context.user_data.pop("awaiting", None)
        if customer_store.add_prefix(clean, name):
            await message.reply_text(f"✅ Префикс боғланди: {clean}- -> {name}",
                                     reply_markup=kb_customers())
        else:
            await message.reply_text(f"❌ \"{name}\" мижози топилмади.", reply_markup=kb_customers())
        return

    # Noma'lum holat - tozalab qo'yamiz, foydalanuvchi tiqilib qolmasin
    context.user_data.pop("awaiting", None)


# ---------- Hujjatni qabul qilish, yig'ish va deklaratsiyada yuborish ----------

async def _finalize_and_send(code: str, context: ContextTypes.DEFAULT_TYPE, notify_chat_id=None):
    batch = batch_store.get_batch(code)
    if not batch or not batch.get("files"):
        await safe_send(context, notify_chat_id, f"\"{code}\" кодли партия топилмади ёки бўш.")
        return

    if code in _sending_now:
        logger.info("%s allaqachon yuborilmoqda, takroriy so'rov e'tiborsiz qoldirildi", code)
        return

    display_code = batch_display_code(code, batch)

    customer_name = batch.get("customer")
    if not customer_name:
        msg = (
            f"⚠️ {display_code} партияси учун мижоз аниқланмади ({len(batch['files'])} та файл кутмоқда).\n"
            f"Белгилаш учун: /batch_assign {code} | MIJOZ_NOMI"
        )
        if notify_chat_id:
            await safe_send(context, notify_chat_id, msg)
        if notify_chat_id != config.ADMIN_USER_ID:
            await notify_admin(context, msg)
        return

    emails = customer_store.get_emails(customer_name)
    if not emails:
        msg = (f"⚠️ {customer_name} мижозининг emaili топилмади. "
               f"{display_code} юборилмади — /customer_add билан email қўшинг.")
        await safe_send(context, notify_chat_id, msg)
        if notify_chat_id != config.ADMIN_USER_ID:
            await notify_admin(context, msg)
        return

    # Diskda yo'q fayl bo'lsa, hech narsa yuborilmasin - yarim komplekt
    # ketib qolgandan ko'ra, admin xabardor bo'lgani yaxshi
    # Fayllarni AYNAN HOZIR Telegram'dan yuklab olamiz - guruhda hujjat
    # tahrirlangan bo'lsa, mijozga oxirgi versiyasi ketsin.
    ok_dl, dl_errors = await _download_batch_files(context, code)
    if not ok_dl:
        msg = (f"❌ {display_code} юборилмади — бу файлларни Telegram'dan "
               f"юклаб бўлмади:\n" + "\n".join(f"   • {e}" for e in dl_errors) +
               f"\n\nФайлларни қайта ташланг ёки /batch_cancel {code}.")
        await safe_send(context, notify_chat_id, msg)
        if notify_chat_id != config.ADMIN_USER_ID:
            await notify_admin(context, msg)
        return

    batch = batch_store.get_batch(code)   # yo'llar yangilandi

    # Fayllar xatga MA'LUM TARTIBDA biriktiriladi: avval invoys guruhi
    # (xlsx, INV, SPETS), keyin skanerlar (ST, FITO, AKT, CMR, TIR),
    # oxirida deklaratsiya - mijoz uchun o'qish qulay bo'lsin.
    #
    # IKKINCHI HIMOYA: turi tanilmagan fayl (chek, pasport nusxasi ва ҳ.к.)
    # mijozga ketib qolmasin. Bunday fayllar odatda qabul qilinmaydi, lekin
    # eski partiyalarda yoki qo'lda biriktirishda uchrab qolishi mumkin.
    all_sorted = batch_store.sorted_files(batch)
    ordered = [f for f in all_sorted if doc_types.is_attachable(f.get("doc_type"))]
    skipped = [f for f in all_sorted if not doc_types.is_attachable(f.get("doc_type"))]

    if not ordered:
        msg = (f"❌ \"{batch_display_code(code, batch)}\" юборилмади: бириктириладиган "
               f"ҳужжат йўқ (барча файлларнинг тури танилмади).")
        await safe_send(context, notify_chat_id, msg)
        if notify_chat_id != config.ADMIN_USER_ID:
            await notify_admin(context, msg)
        return

    file_paths = [f["path"] for f in ordered]
    file_names = [f["filename"] for f in ordered]

    # Xat mavzusini deklaratsiyadan boyitamiz:
    #   "NGS-4  ||  40249PCA/407119BA  ||  DAP - Шымкент"
    # O'qib bo'lmasa - odatdagi mavzu ishlatiladi, xat baribir ketaveradi.
    subject, decl_info = declaration.build_subject(display_code, ordered)
    truck_full = decl_info.get("plates")
    if subject is None:
        subject = doc_types.email_subject(display_code, batch.get("truck"))
        logger.info("%s: deklaratsiyadan mavzu o'qilmadi (%s)", code, decl_info)
        await notify_admin(
            context,
            f"ℹ️ \"{display_code}\" — декларациядан авто рақам / етказиш шарти "
            f"ўқилмади, оддий мавзу ишлатилди.\nХат барибир юборилди."
        )

    _sending_now.add(code)
    try:
        # Gmail API sinxron ishlaydi - alohida oqimda bajaramiz, aks holda
        # katta ilovalar yuborilayotganda bot butunlay "muzlab" qolardi
        results = await asyncio.to_thread(
            gmail_sender.send_batch_to_multiple,
            emails,
            subject,
            doc_types.email_body(display_code, truck_full or batch.get("truck"), ordered),
            file_paths,
        )
    except Exception as e:
        logger.exception("%s yuborishda kutilmagan xatolik", code)
        msg = f"❌ {display_code} юборилмади. Хатолик: {e}"
        await safe_send(context, notify_chat_id, msg)
        if notify_chat_id != config.ADMIN_USER_ID:
            await notify_admin(context, msg)
        return
    finally:
        _sending_now.discard(code)

    ok = [e for e, err in results.items() if err is None]
    failed = {e: err for e, err in results.items() if err is not None}

    # Fayllar ro'yxati - guruhlangan, o'qish qulay ko'rinishda
    file_list = doc_types.format_files(ordered)
    truck_part = f"Fura {batch.get('truck')} · " if batch.get("truck") else ""
    missing_docs = doc_types.missing_types(ordered)

    # Guruhga - email manzillarini oshkor qilmasdan, faqat holat
    if ok:
        group_summary = (
            f"✅ \"{display_code}\" — почтага юборилди\n"
            f"📦 {truck_part}{len(file_names)} та файл · комплект {doc_types.progress_line(ordered)}\n\n"
            f"{file_list}"
        )
        if failed:
            group_summary += f"\n\n⚠️ {len(failed)} та манзилга юборилмади, админ хабардор қилинди."
    else:
        group_summary = (f"❌ \"{display_code}\" почтага ЮБОРИЛМАДИ.\n"
                         f"Файллар сақланиб турибди, админ хабардор қилинди.")

    # Admin'ga shaxsiy - to'liq tafsilot, email manzillari va xatolik sababi bilan
    admin_summary = (
        f"{'✅' if ok else '❌'} \"{display_code}\" -> {customer_name}\n"
        f"📦 {truck_part}{len(file_names)} та файл · комплект {doc_types.progress_line(ordered)}"
        + (f" ⚠️ етишмади: {', '.join(missing_docs)}" if missing_docs else " ✅ тўлиқ") + "\n"
        f"📧 Юборилди: {', '.join(ok) if ok else '—'}\n\n"
        f"{file_list}"
    )
    if skipped:
        admin_summary += ("\n🚫 Хатга қўшилмади (тури танилмади): " +
                          ", ".join(f["filename"] for f in skipped))
    if failed:
        admin_summary += "\n❌ Юборилмади:\n" + "\n".join(f"  • {e}: {err}" for e, err in failed.items())
    if not ok:
        admin_summary += (f"\n\n⚠️ Партия ЎЧИРИЛМАДИ — муаммони ҳал қилиб, "
                          f"/batch_send {code} билан қайта уриниб кўринг.")

    if notify_chat_id == config.ADMIN_USER_ID:
        # Admin o'zi shaxsiy chatdan yuborgan bo'lsa, unga to'liq (email bilan) ko'rsatiladi
        await safe_send(context, notify_chat_id, admin_summary)
    else:
        await safe_send(context, notify_chat_id, group_summary)
        await notify_admin(context, admin_summary)

    # MUHIM: kamida bitta manzilga yetib borgandagina partiya tozalanadi.
    # Ilgari hamma manzilga yuborilmagan holda ham fayllar diskdan o'chib
    # ketardi va hujjatlarni qayta yuborishning iloji qolmasdi.
    if ok:
        # Tarixga yozamiz - shu fayllar qayta tashlansa, bot "bular
        # allaqachon yuborilgan, qayta yuborilsinmi?" deb so'raydi
        sent_store.record(code, display_code, customer_name, ok, ordered)
        history_store.add(
            "batch_sent",
            f"{display_code} → {customer_name} · {len(file_names)} файл"
            + (f" · fura {truck_full}" if truck_full else ""),
        )
        batch_store.clear_batch(code)
    else:
        history_store.add("batch_failed", f"{display_code} → {customer_name}: юборилмади")
    logger.info("%s -> %s: yuborildi=%s, xato=%s", code, customer_name, ok, failed)


def _in_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat
    if chat is None:
        return False
    if chat.type not in ("group", "supergroup"):
        return False
    if not access_store.is_allowed_group(chat.id):
        # Bot "jim" qolib ketmasligi uchun log yozamiz. Guruh supergroup'ga
        # aylantirilganda ID o'zgaradi - eng ko'p uchraydigan sabab.
        logger.info("Hujjat e'tiborsiz qoldirildi: %s (%s) ro'yxatdagi guruhlardan emas",
                    chat.id, chat.type)
        return False
    return True


def _extract_file(message):
    """
    Xabardan fayl ma'lumotlarini ajratib oladi.
    Qaytaradi: (fayl_nomi, file_id, file_unique_id) yoki (None, None, None)
    """
    if message.document is not None:
        d = message.document
        return (d.file_name or "hujjat"), d.file_id, d.file_unique_id
    if message.photo:
        p = message.photo[-1]  # eng katta o'lchamdagi versiya
        caption = (message.caption or "").strip()
        name = f"{caption}.jpg" if caption else f"rasm_{message.message_id}.jpg"
        return name, p.file_id, p.file_unique_id
    return None, None, None


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or message.document is None or not _in_allowed_chat(update):
        return
    name, fid, fuid = _extract_file(message)
    await _process_incoming_file(update, context, name, fid, fuid)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Siqilgan rasm (photo) sifatida yuborilgan fayllarni ham qabul qiladi.
    Bunda fayl nomi bo'lmaydi, shuning uchun kod caption (izoh) dan izlanadi."""
    message = update.effective_message
    if message is None or not message.photo or not _in_allowed_chat(update):
        return
    name, fid, fuid = _extract_file(message)
    await _process_incoming_file(update, context, name, fid, fuid)


async def handle_edited_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Guruhda hujjat TAHRIRLANGANDA ishlaydi.

    Telegram'da yuborilgan hujjatni keyinchalik almashtirish mumkin. Bot
    fayllarni faqat deklaratsiya kelganda yuklab oladi, lekin `file_id`
    eski xabarnikiga ishora qilib qolardi - ya'ni mijozga ESKI versiya
    ketardi. Shuning uchun tahrirlashni ushlab, yozuvni yangilaymiz.
    """
    message = update.edited_message
    if message is None or not _in_allowed_chat(update):
        return

    name, fid, fuid = _extract_file(message)
    if not fid:
        return

    code, old = batch_store.find_by_message(message.message_id)
    if not code:
        # Бу хабар ҳали бирор партияда йўқ. Демак файл аввал нотўғри
        # номланган (ёки тури танилмаган) бўлиб, эътиборсиз қолдирилган.
        # Энди номи тузатилган бўлиши мумкин — оддий йўл билан қайта кўрамиз.
        await _process_incoming_file(update, context, name, fid, fuid)
        return

    parsed = session_store.parse(name)
    doc_type, truck = (None, None)
    if parsed:
        doc_type, truck = doc_types.detect(parsed["remainder"], parsed["extension"])
        if parsed["is_declaration"]:
            doc_type = "DEKL"

    batch_store.replace_file(code, message.message_id, safe_filename(name),
                             fid, fuid, doc_type=doc_type, truck=truck)

    old_name = old.get("filename", "?")
    logger.info("Tahrirlangan hujjat yangilandi: %s -> %s (%s)", old_name, name, code)
    history_store.add("doc_edited", f"{code}: {old_name} янгиланди")

    batch = batch_store.get_batch(code)
    new_name = safe_filename(name)
    text = f"✏️ Таҳрирланган ҳужжат олинди: {old_name}"
    if new_name != old_name:
        text += f" → {new_name}"
    text += (f"\nМижозга айнан шу — охирги версия кетади. "
             f"[{doc_types.progress_line(batch['files'])}]")
    await safe_send(context, update.effective_chat.id, text)


DOWNLOAD_ATTEMPTS = 3


async def _download(bot, file_id: str, local_dir: str, filename: str) -> str:
    """
    Faylni Telegram'dan `file_id` bo'yicha yuklab oladi.

    Internet beqaror bo'lsa bitta urinish yetmasligi mumkin - bunday holda
    hujjat YO'QOLIB ketardi (hodim uni qayta tashlashi kerak bo'lardi).
    Shuning uchun bir necha marta qayta urinamiz.
    """
    os.makedirs(local_dir, exist_ok=True)
    local_path = unique_path(local_dir, safe_filename(filename))

    last_error = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            tg_file = await bot.get_file(file_id)
            await tg_file.download_to_drive(local_path)
            return local_path
        except (NetworkError, TimedOut, OSError) as e:
            last_error = e
            logger.warning("\"%s\" yuklanmadi (%d/%d urinish): %s",
                           filename, attempt, DOWNLOAD_ATTEMPTS, e)
            # Yarim yozilgan faylni tozalaymiz
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
            except OSError:
                pass
            if attempt < DOWNLOAD_ATTEMPTS:
                await asyncio.sleep(2 * attempt)   # 2, 4 soniya

    raise last_error


# Albom bo'lib kelgan fayllar uchun ogohlantirishlarni birlashtirish vaqti.
# (Oddiy "qabul qilindi" xabari yozilmaydi - bot hujjatlarni JIMGINA yig'ib
# boradi va faqat deklaratsiya kelganda gapiradi.)
ACK_DELAY_SECONDS = 5


# Turi tanilmagan fayllar (chek, pasport nusxasi, haydovchi rasmi ва ҳ.к.)
# JIMGINA e'tiborsiz qoldiriladi - guruhga hech narsa yozilmaydi.
# Ilgari har bir bunday fayl uchun ogohlantirish chiqarilardi va bu guruhni
# keraksiz xabarlarga to'ldirib yuborardi. Bot faqat kalit hujjat turlarini
# (INV, SPETS, ST, FITO, AKT, CMR, TIR) oladi, qolganiga umuman tegmaydi.


def _naming_warnings(existing_batch, parsed, doc_type, truck, filename) -> list:
    """
    Fayl nomidagi ehtimoliy xatoliklar haqida ogohlantirishlar.
    Fayl baribir qabul qilinadi - faqat guruhda ogohlantirish yoziladi,
    toki xato sezilmay qolmasin.
    """
    warnings = []
    display = parsed["display"]
    ext = parsed["extension"] or "jpg"
    expected_truck = (existing_batch or {}).get("truck")

    if expected_truck and truck and truck != expected_truck:
        warnings.append(
            f"⚠️ \"{filename}\" — фура рақами инвойсдагидан ФАРҚ ҚИЛАДИ.\n"
            f"Invoysda: {expected_truck}, бу файлда: {truck}.\n"
            f"Номини текширинг — ҳужжат нотўғри партияга тушмасин."
        )
    elif expected_truck and not truck and doc_type in doc_types.SCAN_TYPES:
        # Faqat SKANER hujjatlari uchun ogohlantiramiz. INV/SPETS/xlsx odatda
        # fura raqamisiz nomlanadi ("NGS25INV.pdf") - bu xato emas.
        warnings.append(
            f"⚠️ \"{filename}\" — фура рақами ёзилмаган (инвойсда: {expected_truck}).\n"
            f"Тўғри кўриниш: {display} {doc_type} {expected_truck}.{ext}\n"
            f"Файл қабул қилинди, кейинги сафар тўлиқ ёзинг."
        )

    # Bir turdagi hujjat bir nechta bo'lishi NORMAL holat:
    # - invoys ham PDF ("NGS11INV.pdf"), ham skaner ("NGS 11 INV 269.JPG") bo'ladi
    # - ko'p sahifali CMR/ST alohida fayllar bo'lib skanerlanadi
    # Shuning uchun takrorlangan tur uchun ogohlantirish yozilmaydi.

    return warnings


async def _process_incoming_file(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 filename: str, file_id: str, file_unique_id: str):
    chat_id = update.effective_chat.id

    parsed = session_store.parse(filename)
    if not parsed:
        # Kod umuman topilmadi (oddiy suhbat, skrinshot, pasport nusxasi ва ҳ.к.)
        # - bunga botning aloqasi yo'q, butunlay e'tiborsiz qoldiramiz.
        return

    code = parsed["code"]
    display = parsed["display"]
    is_declaration = parsed["is_declaration"]
    doc_type, truck = doc_types.detect(parsed["remainder"], parsed["extension"])
    if is_declaration:
        doc_type = "DEKL"

    # ---- 0. Bu bizning hujjatimizmi? ----
    # Guruhga chek, pasport nusxasi, haydovchi rasmi kabi begona fayllar ham
    # tashlanadi. Hujjat TURI tanilmasa - fayl bizga tegishli emas: yuklab
    # ham olinmaydi, guruhga xabar ham yozilmaydi. Faqat logga tushadi.
    if doc_type is None:
        logger.info("Turi tanilmagan fayl e'tiborsiz qoldirildi: %s (%s)", filename, code)
        return

    # ---- 1. Bu fayl ilgari pochtaga yuborilganmi? ----
    # Yuborilgan partiya batches.json dan o'chiriladi, shuning uchun uni
    # oddiy dublikat sifatida tanib bo'lmaydi - alohida tarixga qaraymiz.
    sent_code, sent_entry = sent_store.find_by_file(file_unique_id)
    if sent_code and not batch_store.get_batch(code):
        await _ask_resend(update, context, code, display, filename,
                          file_id, file_unique_id, sent_code, sent_entry)
        return

    # ---- 2. Mijozni aniqlash ----
    customer_name, _ = customer_store.find_by_filename(filename)
    if not customer_name and parsed["prefix"]:
        customer_name = customer_store.find_by_prefix(parsed["prefix"])
    if not customer_name:
        customer_name = session_store.recall(code)
    if customer_name:
        session_store.remember(code, customer_name)

    if not customer_name:
        # Kod bor, lekin qaysi mijozga tegishli ekani noma'lum - fayl
        # yo'qolmasin, "noaniq fayllar" ro'yxatiga saqlaymiz.
        await _store_unmatched(update, context, filename, file_id, file_unique_id, code)
        return

    # ---- 3. Dublikat ----
    if batch_store.is_duplicate(code, file_unique_id):
        logger.info("Dublikat e'tiborsiz qoldirildi: %s (%s)", filename, code)
        # MUHIM: qayta tashlangan fayl DEKLARATSIYA bo'lsa, uni shunchaki
        # e'tiborsiz qoldirib bo'lmaydi. Deklaratsiyani qayta tashlash -
        # "endi yuboring" degani. Aks holda (masalan birinchi urinishda
        # pochta ishlamay qolgan bo'lsa) partiya abadiy osilib qolardi:
        # hujjatlarni qayta tashlaysiz, bot esa "dublikat" deb jim turadi.
        if is_declaration and batch_store.get_batch(code):
            await _on_declaration(update, context, code)
        return

    # ---- 4. Partiyaga qo'shish (YUKLAB OLMASDAN) ----
    #
    # Fayl hozir yuklab olinmaydi - faqat `file_id` eslab qolinadi.
    # Sabab: Telegram'da hujjatni keyinchalik tahrirlash mumkin. Agar hozir
    # yuklab olsak, mijozga eski versiya ketib qolardi. Barcha fayllar
    # yakuniy deklaratsiya kelganda, bir yo'la yuklab olinadi.
    warnings = _naming_warnings(batch_store.get_batch(code), parsed, doc_type, truck, filename)

    sender = update.effective_user
    batch_store.add_file(code, safe_filename(filename),
                         file_unique_id=file_unique_id, customer=customer_name,
                         display=display, doc_type=doc_type, truck=truck,
                         file_id=file_id, message_id=update.effective_message.message_id,
                         user_id=getattr(sender, "id", None), user_name=_user_name(sender))

    for warning in warnings:
        await safe_send(context, chat_id, warning)

    if is_declaration:
        await _on_declaration(update, context, code)
    # Oddiy hujjatlar uchun guruhga hech narsa yozilmaydi - bot ularni
    # JIMGINA yig'ib boradi. Xabar faqat deklaratsiya kelganda chiqadi.


# ---------- Deklaratsiya kelganda: komplektni tekshirish va yuborish ----------

async def _on_declaration(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    """
    Yakuniy deklaratsiya kelgach chaqiriladi.
    Komplekt to'liq bo'lsa - yuboradi. To'liq bo'lmasa - YUBORMAYDI va
    qaysi hujjat yetishmayotganini guruhda aytadi.
    """
    chat_id = update.effective_chat.id
    batch = batch_store.get_batch(code)
    if not batch or not batch.get("files"):
        return

    display = batch_display_code(code, batch)
    missing = doc_types.missing_types(batch["files"])

    if missing:
        # Ҳужжатларни ташлаган одам(лар)ни белгилаймиз — шунда у бевосита
        # билдиришнома олади ва нима йетишмаётганини кўради.
        who = _batch_mentions(batch, update.effective_user)
        head = f"{who}, " if who else ""
        esc_display = html.escape(display)

        await safe_send(
            context, chat_id,
            f"🛑 {head}<b>{esc_display}</b> — "
            f"{', '.join(html.escape(t) for t in missing)} ҳужжат"
            f"{'и' if len(missing) == 1 else 'лари'} йетишмаяпти "
            f"[{doc_types.progress_line(batch['files'])}]\n\n"
            f"❌ Йетишмаётганлар:\n" +
            "\n".join(f"   • {html.escape(doc_types.title(t))}" for t in missing) +
            f"\n\nЙетишмаган ҳужжатларни ташланг, сўнг декларацияни "
            f"({esc_display}.pdf) қайта юборинг.\n"
            f"Ёки қуйидаги тугма билан шу ҳолатда юборишингиз мумкин.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚠️ Барибир юборилсин", callback_data=f"force:yes:{_tok(code)}"),
                InlineKeyboardButton("⏳ Кутамиз", callback_data=f"force:no:{_tok(code)}"),
            ]]),
            parse_mode="HTML",
        )
        await notify_admin(
            context,
            f"🛑 \"{display}\" комплекти тўлиқ эмас, юборилмади.\n"
            f"Йетишмаяпти: {', '.join(missing)}\n"
            f"Мажбуран юбориш: /batch_send {code}"
        )
        return

    # Komplekt to'liq - ortiqcha xabar yozmaymiz, to'g'ridan-to'g'ri
    # yuboramiz. Guruh faqat yakuniy "yuborildi" xabarini ko'radi.
    await _finalize_and_send(code, context, notify_chat_id=chat_id)


async def _download_batch_files(context: ContextTypes.DEFAULT_TYPE, code: str):
    """
    Partiyaning barcha fayllarini AYNAN SHU PAYTDA Telegram'dan yuklab oladi.

    Fayllar guruhga tashlanganda saqlanmaydi - chunki hujjatni keyinchalik
    tahrirlash mumkin. Yuklash faqat shu yerda, deklaratsiya kelganda
    bajariladi. Shu tufayli mijozga har doim hujjatlarning OXIRGI
    versiyasi ketadi.

    Qaytaradi: (muvaffaqiyatlimi, xato_matnlari)
    """
    batch = batch_store.get_batch(code)
    if not batch:
        return False, ["Partiya topilmadi"]

    local_dir = os.path.join(DOWNLOAD_DIR, code)
    paths, errors = {}, []

    for f in batch.get("files", []):
        uid = f.get("file_unique_id")
        existing = f.get("path")
        # Allaqachon yuklab olingan bo'lsa (masalan qayta yuborishda) - qoldiramiz
        if existing and os.path.exists(existing):
            paths[uid] = existing
            continue

        file_id = f.get("file_id")
        if not file_id:
            errors.append(f"{f.get('filename', '?')}: file_id йўқ (эски ёзув)")
            continue

        try:
            paths[uid] = await _download(context.bot, file_id, local_dir, f.get("filename", "hujjat"))
        except Exception as e:
            logger.exception("Yuklab bo'lmadi: %s", f.get("filename"))
            errors.append(f"{f.get('filename', '?')}: {e}")

    batch_store.set_paths(code, paths)
    return (len(errors) == 0), errors


# ---------- Allaqachon yuborilgan faylni qayta tashlaganda ----------

# code -> {"chat_id", "files": [...], "sent_code", "sent_at"}
_pending_resend = {}

RESEND_ASK_DELAY = 4


async def _ask_resend(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str,
                      display: str, filename: str, file_id: str, file_unique_id: str,
                      sent_code: str, sent_entry: dict):
    """
    Bu fayl allaqachon pochtaga yuborilgan. Darhol qabul qilib qo'ymaymiz -
    guruhda so'raymiz. Fayl vaqtincha chetga yuklab qo'yiladi; "HA" desangiz
    partiyaga qo'shiladi, "YO'Q" desangiz o'chiriladi.
    """
    chat_id = update.effective_chat.id
    parsed = session_store.parse(filename)
    doc_type, truck = doc_types.detect(parsed["remainder"], parsed["extension"]) if parsed else (None, None)

    try:
        local_path = await _download(
            context.bot, file_id, os.path.join(DOWNLOAD_DIR, "_resend", code), filename
        )
    except Exception:
        logger.exception("Qayta yuborish uchun faylni yuklab bo'lmadi: %s", filename)
        return

    entry = _pending_resend.setdefault(code, {
        "chat_id": chat_id, "files": [],
        # Tarixdagi ko'rinish aniqroq ("NGS-25"), chunki u to'liq nomdan olingan
        "display": sent_entry.get("display") or display,
        "sent_code": sent_code, "sent_at": sent_entry.get("sent_at"),
    })
    if any(f["file_unique_id"] == file_unique_id for f in entry["files"]):
        try:
            os.remove(local_path)
        except OSError:
            pass
        return

    entry["files"].append({
        "filename": safe_filename(filename), "path": local_path,
        "file_unique_id": file_unique_id, "doc_type": doc_type, "truck": truck,
        "display": display, "is_declaration": parsed["is_declaration"] if parsed else False,
    })

    # Albom bo'lib kelgan bo'lsa, hammasi tushib bo'lguncha kutamiz va
    # bitta savol beramiz (har bir faylga alohida savol bermaymiz)
    if context.job_queue is None:
        await _send_resend_question(context, code)
        return
    name = f"resend:{code}"
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    context.job_queue.run_once(_resend_question_job, RESEND_ASK_DELAY, name=name,
                               data={"code": code})


async def _resend_question_job(context: ContextTypes.DEFAULT_TYPE):
    await _send_resend_question(context, context.job.data["code"])


async def _send_resend_question(context: ContextTypes.DEFAULT_TYPE, code: str):
    entry = _pending_resend.get(code)
    if not entry or not entry["files"]:
        return

    when = "—"
    if entry.get("sent_at"):
        when = datetime.fromtimestamp(entry["sent_at"]).strftime("%d.%m.%Y %H:%M")

    names = "\n".join(f"   • {f['filename']}" for f in entry["files"][:12])
    more = f"\n   ... va yana {len(entry['files']) - 12} ta" if len(entry["files"]) > 12 else ""

    await safe_send(
        context, entry["chat_id"],
        f"♻️ \"{entry['display']}\" — бу ҳужжат(лар) АЛЛАҚАЧОН почтага юборилган "
        f"({when}).\n\n"
        f"Қайта ташланган файллар ({len(entry['files'])}):\n{names}{more}\n\n"
        f"Яна қайта юборилсинми?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ ҲА, қайта юборилсин", callback_data=f"resend:yes:{_tok(code)}"),
            InlineKeyboardButton("❌ ЙЎҚ", callback_data=f"resend:no:{_tok(code)}"),
        ]]),
    )


async def _apply_resend(context: ContextTypes.DEFAULT_TYPE, code: str):
    """
    HA javobi: chetda turgan fayllarni partiyaga ko'chiradi.
    Qaytaradi: (fayllar_soni, deklaratsiya_bormi, chat_id)
    """
    entry = _pending_resend.pop(code, None)
    if not entry:
        return 0, False, None

    customer = session_store.recall(code)
    if not customer:
        sent = sent_store.get(entry.get("sent_code") or code)
        customer = (sent or {}).get("customer")

    target_dir = os.path.join(DOWNLOAD_DIR, code)
    os.makedirs(target_dir, exist_ok=True)

    declaration_seen = False
    for f in entry["files"]:
        new_path = unique_path(target_dir, f["filename"])
        try:
            os.replace(f["path"], new_path)
        except OSError:
            new_path = f["path"]
        batch_store.add_file(code, f["filename"], new_path,
                             file_unique_id=f["file_unique_id"], customer=customer,
                             display=f["display"], doc_type=f["doc_type"], truck=f["truck"])
        if f["is_declaration"]:
            declaration_seen = True

    _cleanup_dir(os.path.join(DOWNLOAD_DIR, "_resend", code))
    return len(entry["files"]), declaration_seen, entry["chat_id"]


def _discard_resend(code: str) -> int:
    entry = _pending_resend.pop(code, None)
    if not entry:
        return 0
    for f in entry["files"]:
        try:
            if os.path.exists(f["path"]):
                os.remove(f["path"])
        except OSError:
            pass
    _cleanup_dir(os.path.join(DOWNLOAD_DIR, "_resend", code))
    return len(entry["files"])


def _cleanup_dir(path: str):
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


async def _store_unmatched(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           filename: str, file_id: str, file_unique_id: str, code: str):
    if unmatched_store.already_received(file_unique_id):
        return
    try:
        local_path = await _download(context.bot, file_id,
                                     os.path.join(DOWNLOAD_DIR, "_unmatched"), filename)
    except Exception:
        logger.exception("Noaniq faylni yuklab bo'lmadi: %s", filename)
        return

    entry_id = unmatched_store.add(safe_filename(filename), local_path, file_unique_id,
                                   update.effective_chat.id)
    logger.info("Mijozi aniqlanmagan fayl saqlandi: %s (%s) -> %s", filename, code, entry_id)
    await notify_admin(
        context,
        f"❓ Мижози аниқланмаган файл сақланди.\n"
        f"Файл: {filename}\nKod: {code}\nID: {entry_id}\n\n"
        f"Бириктириш: /batch_attach {code} | {entry_id}\n"
        f"Ўчириш: /unmatched_delete {entry_id}",
    )


# ---------- Eskirgan partiyalarni avtomatik eslatish ----------

async def check_stale_batches(context: ContextTypes.DEFAULT_TYPE):
    if not config.ADMIN_USER_ID:
        return

    data = batch_store.all_batches()
    now = time.time()

    for code, batch in data.items():
        try:
            age_hours = (now - batch.get("created_at", now)) / 3600
            if age_hours < STALE_HOURS:
                continue

            last_reminded = batch.get("last_reminded")
            if last_reminded and (now - last_reminded) / 3600 < REMINDER_COOLDOWN_HOURS:
                continue

            customer = batch.get("customer") or "❓ aniqlanmagan"
            file_count = len(batch.get("files", []))
            elapsed = format_elapsed(now - batch.get("created_at", now))

            await notify_admin(
                context,
                f"⏰ Eslatma: \"{batch_display_code(code, batch)}\" партияси {elapsed} dan beri "
                f"декларациясиз кутмоқда.\n"
                f"Мижоз: {customer}, {file_count} та файл.\n"
                f"Қўлда юбориш: /batch_send {code}\n"
                f"Бекор қилиш: /batch_cancel {code}"
            )
            batch_store.mark_reminded(code)
        except Exception:
            logger.exception("%s partiyasini tekshirishda xatolik", code)


# ---------- Gmail ruxsatini muntazam tekshirish ----------

# Oxirgi holat va oxirgi ogohlantirish vaqti (spam bo'lmasligi uchun)
_gmail_state = {"ok": None, "last_alert": 0.0}


async def check_gmail_health(context: ContextTypes.DEFAULT_TYPE, force_report: bool = False):
    """
    Gmail ruxsati o'lib qolganini hujjatlar to'planib bo'lgandan KEYIN emas,
    OLDINDAN bilish uchun. Google "Testing" rejimida ruxsat har 7 kunda
    bekor bo'ladi - bot buni o'zi sezib, admin'ga aytadi.
    """
    ok, msg = await asyncio.to_thread(gmail_sender.check_credentials)
    was_ok = _gmail_state["ok"]
    now = time.time()

    if ok:
        if was_ok is False:
            await notify_admin(context, f"✅ Gmail рухсати тикланди — {msg}")
        elif force_report:
            await notify_admin(context, f"✅ Gmail: {msg}")
        _gmail_state["ok"] = True
        return True

    # Buzuq: birinchi marta yoki 24 soatda bir marta ogohlantiramiz
    should_alert = was_ok is not False or (now - _gmail_state["last_alert"]) > 24 * 3600
    if should_alert or force_report:
        pending = batch_store.all_batches()
        extra = ""
        if pending:
            extra = (f"\n\n⏳ Ҳозир {len(pending)} та партия кутмоқда — муаммо "
                     f"ҳал бўлгач улар юборилади.")
        await notify_admin(
            context,
            f"❌ GMAIL РУХСАТИ ИШЛАМАЯПТИ — бот ҳозир хат юбора олмайди.\n\n{msg}{extra}"
        )
        _gmail_state["last_alert"] = now

    _gmail_state["ok"] = False
    return False


async def gmail_health_job(context: ContextTypes.DEFAULT_TYPE):
    await check_gmail_health(context)


@private_only
async def gmail_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, msg = await asyncio.to_thread(gmail_sender.check_credentials)
    await update.effective_message.reply_text(("✅ " if ok else "❌ ") + msg)


# ---------- Umumiy xatoliklarni ushlash ----------

# Tarmoq uzilishlarini hisoblash (admin'ni bekorga bezovta qilmaslik uchun)
_network_errors = {"count": 0, "first": 0.0, "last_alert": 0.0}

# Shuncha vaqt ichida shuncha marta uzilsa - demak muammo jiddiy
NETWORK_ALERT_THRESHOLD = 10
NETWORK_ALERT_WINDOW = 300      # 5 daqiqa
NETWORK_ALERT_COOLDOWN = 3600   # ogohlantirishlar orasidagi minimal vaqt


def _handle_network_error(error) -> bool:
    """
    Tarmoq uzilishi - Telegram bilan aloqa bir lahzaga uzilgan (internet,
    Wi-Fi, provayder). Bot bunday holatda o'zi qayta ulanadi va ishlashda
    davom etadi, shuning uchun HAR BIR uzilish uchun admin'ga xabar
    yozish - keraksiz shovqin.

    Faqat uzilishlar KETMA-KET takrorlansa (5 daqiqada 10 martadan ko'p)
    ogohlantiramiz - demak internetda haqiqiy muammo bor.

    Qaytaradi: True - ogohlantirish yuborilsin, False - jim o'tkazilsin.
    """
    now = time.time()

    # Oxirgi uzilishdan ancha vaqt o'tgan bo'lsa, hisobni noldan boshlaymiz
    if now - _network_errors["first"] > NETWORK_ALERT_WINDOW:
        _network_errors["first"] = now
        _network_errors["count"] = 0

    _network_errors["count"] += 1
    logger.warning("Telegram bilan aloqa uzildi (%d-marta): %s",
                   _network_errors["count"], error)

    if _network_errors["count"] < NETWORK_ALERT_THRESHOLD:
        return False
    if now - _network_errors["last_alert"] < NETWORK_ALERT_COOLDOWN:
        return False

    _network_errors["last_alert"] = now
    return True


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Ilgari handler ichidagi har qanday xatolik jimgina logga tushib ketardi -
    bot "javob bermay qo'ygandek" ko'rinardi. Endi admin xabardor qilinadi.
    """
    if isinstance(context.error, Forbidden):
        logger.warning("Telegram ruxsat bermadi: %s", context.error)
        return

    # Tarmoq uzilishi - bot o'zi qayta ulanadi, bezovta qilmaymiz
    if isinstance(context.error, (NetworkError, TimedOut)):
        if not _handle_network_error(context.error):
            return
        await notify_admin(
            context,
            f"📡 Интернет алоқаси беқарор — сўнгги 5 дақиқада "
            f"{_network_errors['count']} marta uzildi.\n\n"
            f"Бот ўзи қайта уланмоқда, ҳужжатлар йўқолмайди. Лекин узоқ "
            f"давом этса, интернетни текширинг.\n\n"
            f"Охирги хатолик: {str(context.error)[:200]}"
        )
        return

    logger.error("Handler xatoligi", exc_info=context.error)

    if not config.ADMIN_USER_ID:
        return
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    text = f"⚠️ Ботда хатолик юз берди:\n{str(context.error)[:400]}\n\n...{tb[-800:]}"
    try:
        await context.bot.send_message(config.ADMIN_USER_ID, text)
    except TelegramError:
        pass


async def _post_init(app: Application):
    await _start_webapp(app)

    problems = config.validate()
    for p in problems:
        logger.warning("SOZLAMA: %s", p)
    if not config.ADMIN_USER_ID:
        return

    note = "♻️ Бот қайта ишга тушди."
    if problems:
        note += "\n\n⚠️ Созламаларда муаммо:\n" + "\n".join(f"• {p}" for p in problems)

    # Baza bo'sh bo'lsa (masalan yangi serverda) - hujjatlar hech kimga
    # yuborilmaydi, hammasi "noaniq fayllar" ga tushib ketaveradi.
    # Buni oldindan aytamiz.
    if not customer_store.load_customers():
        note += (
            "\n\n❗ МИЖОЗЛАР РЎЙХАТИ БЎШ.\n"
            "Бот ҳужжатларни ҳеч кимга юбора олмайди — ҳаммаси \"ноаниқ "
            "файллар\" га тушади.\n\n"
            "Мижозларни қўшинг, масалан:\n"
            "/customer_add GALLAKTIKA | pochta@example.com\n"
            "/prefix_add NGS | GALLAKTIKA"
        )
    try:
        await app.bot.send_message(config.ADMIN_USER_ID, note)
    except TelegramError as e:
        logger.warning("Admin'ga ishga tushish xabari yuborilmadi: %s", e)

    # Ishga tushishi bilan Gmail ruxsatini tekshiramiz - muammo bo'lsa,
    # hujjatlar to'planishidan oldin bilib olamiz
    class _Ctx:
        bot = app.bot
    await check_gmail_health(_Ctx())


async def _start_webapp(app: Application):
    """Mini App serverini bot bilan bir jarayonda ishga tushiradi."""

    async def send_batch(code: str):
        class _Ctx:
            bot = app.bot
            job_queue = app.job_queue
        await _finalize_and_send(code, _Ctx(), notify_chat_id=config.ADMIN_USER_ID)

    app.bot_data["webapp_runner"] = await webapp.start({
        "send_batch": send_batch,
        "attach_unmatched": _attach_unmatched,
    })


def main():
    problems = config.validate()
    if not config.BOT_TOKEN or ":" not in config.BOT_TOKEN:
        raise SystemExit(
            "ХАТОЛИК: BOT_TOKEN белгиланмаган ёки нотўғри.\n"
            "  • Компьютерда ишлатсангиз  -> .env файлини текширинг\n"
            "  • Серверда (Railway) бўлса -> Variables бўлимини текширинг\n"
            "Token @BotFather берган, ичида ':' бўлган қатор бўлиши керак."
        )
    for p in problems:
        logger.warning("SOZLAMA: %s", p)

    # Python 3.14+ da asyncio.get_event_loop() avtomatik loop yaratmaydi,
    # shu sabab ba'zi kutubxonalar (jumladan python-telegram-bot) xato beradi.
    # DIQQAT: bu yerda get_event_loop() ni CHAQIRMAYMIZ - Python 3.12/3.13 da
    # u "DeprecationWarning: There is no current event loop" ogohlantirishini
    # loglarga chiqarib, xatolikdek ko'rinardi. get_running_loop() esa
    # hech qanday ogohlantirish bermaydi.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Tarmoq beqaror bo'lganda "httpx.ReadError" chiqib turmasligi uchun
    # kutish vaqtlari uzaytirilgan. Standart qiymatlar (5 soniya) sekin yoki
    # uzilib turadigan internet uchun juda qisqa - ayniqsa 10 MB li
    # hujjatlarni yuklab olayotganda.
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)        # katta fayllarni yuklashga vaqt kerak
        .media_write_timeout(180.0)
        .pool_timeout(30.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(40.0)   # long polling
        .get_updates_write_timeout(30.0)
        .get_updates_pool_timeout(30.0)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("chatid", chatid_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("gmail_check", gmail_check_command))
    app.add_handler(CommandHandler("admins", admins_command))
    app.add_handler(CommandHandler("admin_add", admin_add_command))
    app.add_handler(CommandHandler("admin_remove", admin_remove_command))
    app.add_handler(CommandHandler("groups", groups_command))
    app.add_handler(CommandHandler("group_add", group_add_command))
    app.add_handler(CommandHandler("group_remove", group_remove_command))
    app.add_handler(CommandHandler("customer_add", customer_add_command))
    app.add_handler(CommandHandler("customer_remove", customer_remove_command))
    app.add_handler(CommandHandler("customer_list", customer_list_command))
    app.add_handler(CommandHandler("customer_alias", customer_alias_command))
    app.add_handler(CommandHandler("prefix_add", prefix_add_command))
    app.add_handler(CommandHandler("prefix_remove", prefix_remove_command))
    app.add_handler(CommandHandler("batches", batches_command))
    app.add_handler(CommandHandler("batch_assign", batch_assign_command))
    app.add_handler(CommandHandler("batch_send", batch_send_command))
    app.add_handler(CommandHandler("batch_cancel", batch_cancel_command))
    app.add_handler(CommandHandler("unmatched", unmatched_command))
    app.add_handler(CommandHandler("unmatched_delete", unmatched_delete_command))
    app.add_handler(CommandHandler("unmatched_attach_all", unmatched_attach_all_command))
    app.add_handler(CommandHandler("batch_attach", batch_attach_command))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
        text_input_router,
    ))
    # filters.UpdateType.MESSAGE muhim: usiz bot tahrirlangan xabarlarni ham
    # ushlab, update.message = None bo'lgani uchun xatolik berardi.
    app.add_handler(MessageHandler(filters.Document.ALL & filters.UpdateType.MESSAGE, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO & filters.UpdateType.MESSAGE, handle_photo))
    # Guruhda hujjat TAHRIRLANGANDA - yozuvni yangilaymiz, aks holda
    # mijozga hujjatning eski versiyasi ketib qolardi.
    app.add_handler(MessageHandler(
        (filters.Document.ALL | filters.PHOTO) & filters.UpdateType.EDITED_MESSAGE,
        handle_edited_file,
    ))

    app.add_error_handler(error_handler)

    if app.job_queue is not None:
        app.job_queue.run_repeating(
            check_stale_batches,
            interval=timedelta(hours=CHECK_INTERVAL_HOURS),
            first=timedelta(minutes=2),
        )
        app.job_queue.run_repeating(
            gmail_health_job,
            interval=timedelta(hours=GMAIL_CHECK_INTERVAL_HOURS),
            first=timedelta(hours=GMAIL_CHECK_INTERVAL_HOURS),
        )
    else:
        logger.warning(
            "Жобқуеуе мавжуд эмас - эскирган партиялар ҳақида автоматик эслатма ишламайди. "
            "'pip install \"python-telegram-bot[job-queue]\"' bilan o'rnating."
        )

    logger.info("Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
