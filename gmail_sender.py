"""
Gmail SMTP orqali fayl(lar) biriktirilgan xat yuborish.

NEGA OAuth EMAS?
Avval bu modul Gmail API + OAuth (token.json) orqali ishlardi. Google
"Testing" holatidagi ilovalarga refresh token'ni atigi 7 KUNGA beradi -
shu sabab bot har hafta "invalid_grant" xatoligi bilan to'xtab qolardi.
Doimiy ishlaydigan bot uchun bu yaramaydi.

SMTP + "App Password" da esa token umuman yo'q: parol siz uni o'zingiz
bekor qilmaguningizcha amal qiladi. Google Cloud loyihasi, token.json,
credentials.json - hech biri kerak emas.

SOZLASH (bir marta):
1. Google hisobingizda 2 bosqichli tasdiqlashni yoqing:
   https://myaccount.google.com/signinoptions/twosv
2. "App password" (Ilova paroli) yarating:
   https://myaccount.google.com/apppasswords
   Nom sifatida masalan "export bot" deb yozing. Google 16 belgili parol
   beradi (masalan "abcd efgh ijkl mnop").
3. Shu parolni va Gmail manzilingizni config.py ga (yoki muhit
   o'zgaruvchilariga) qo'ying:
       GMAIL_ADDRESS      = "sizning.pochta@gmail.com"
       GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
   Probellar bilan yozsangiz ham bo'ladi - kod ularni o'zi olib tashlaydi.
4. Botga /gmail_check yozib tekshiring.
"""

import copy
import logging
import mimetypes
import os
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage

import config

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465          # SSL
SMTP_TIMEOUT = 60        # soniya

# Gmail'ning xat hajmi chegarasi 25 MB. Xavfsizlik uchun biroz pastroq.
MAX_TOTAL_BYTES = 23 * 1024 * 1024


class GmailError(Exception):
    """Xat yuborishda yuzaga kelgan, foydalanuvchiga ko'rsatsa bo'ladigan xatolik."""


SETUP_HINT = (
    "Sozlash:\n"
    "1) 2 bosqichli tasdiqlashni yoqing: myaccount.google.com/signinoptions/twosv\n"
    "2) Ilova paroli oling: myaccount.google.com/apppasswords\n"
    "3) config.py dagi GMAIL_ADDRESS va GMAIL_APP_PASSWORD ga yozing"
)

AUTH_HINT = (
    "Gmail login yoki parolni qabul qilmadi.\n\n"
    "Tekshiring:\n"
    "• GMAIL_APP_PASSWORD — bu oddiy Gmail parolingiz EMAS, "
    "myaccount.google.com/apppasswords dan olingan 16 belgili maxsus parol\n"
    "• Google hisobingizda 2 bosqichli tasdiqlash yoqilganmi "
    "(usiz ilova paroli yaratib bo'lmaydi)\n"
    "• GMAIL_ADDRESS parol olingan hisobning manziliga mos keladimi"
)


def _get_password() -> str:
    """
    Ilova parolidan barcha bo'sh belgilarni olib tashlaydi.

    Google parolni "abcd efgh ijkl mnop" ko'rinishida ko'rsatadi va nusxa
    olganda ODDIY PROBEL emas, UZILMAS PROBEL (NBSP, U+00A0) qo'yib yuboradi.
    Ilgari faqat oddiy probel olib tashlangani uchun parol 16 emas, 19 belgi
    bo'lib qolardi va Gmail uni qabul qilmasdi.
    Shuning uchun \\s (barcha bo'sh belgi turlari) bo'yicha tozalaymiz.
    """
    return re.sub(r"\s+", "", config.GMAIL_APP_PASSWORD or "")


def _get_address() -> str:
    return (config.GMAIL_ADDRESS or "").strip()


def _connect() -> smtplib.SMTP_SSL:
    """Gmail SMTP ga ulanib, kiradi. Muammo bo'lsa GmailError ko'taradi."""
    address = _get_address()
    password = _get_password()

    if not address or not password:
        raise GmailError(f"Gmail manzili yoki ilova paroli belgilanmagan.\n\n{SETUP_HINT}")
    if "@" not in address:
        raise GmailError(f"GMAIL_ADDRESS noto'g'ri: {address!r}\n\n{SETUP_HINT}")
    if len(password) != 16:
        logger.warning("Ilova paroli 16 belgi emas (%d ta) - xato bo'lishi mumkin", len(password))

    try:
        server = smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=SMTP_TIMEOUT
        )
    except (socket.gaierror, socket.timeout, TimeoutError) as e:
        raise GmailError(f"Gmail serveriga ulanib bo'lmadi (internet yo'qmi?): {e}") from e
    except OSError as e:
        raise GmailError(f"Gmail serveriga ulanib bo'lmadi: {e}") from e

    try:
        server.login(address, password)
    except smtplib.SMTPAuthenticationError as e:
        server.close()
        raise GmailError(f"{AUTH_HINT}\n\nGoogle javobi: {e.smtp_code} {e.smtp_error}") from e
    except smtplib.SMTPException as e:
        server.close()
        raise GmailError(f"Gmail ga kirishda xatolik: {e}") from e

    return server


def check_credentials():
    """
    Gmail ruxsati hozir ishlayaptimi - tekshiradi (xat yubormasdan).
    Qaytaradi: (yaxshimi: bool, izoh: str)
    """
    try:
        server = _connect()
    except GmailError as e:
        return False, str(e)
    except Exception as e:
        logger.exception("Gmail tekshiruvida kutilmagan xatolik")
        return False, f"Tekshirib bo'lmadi: {e}"

    try:
        server.quit()
    except smtplib.SMTPException:
        server.close()
    return True, f"ruxsat ishlayapti ({_get_address()})"


def check_attachments(file_paths: list):
    """
    Yuborishdan OLDIN fayllarni tekshiradi.
    Qaytaradi: (yo'q_bo'lgan_fayllar, umumiy_hajm_baytda)
    """
    missing = []
    total = 0
    for path in file_paths:
        if not path or not os.path.exists(path):
            missing.append(os.path.basename(path or "?"))
            continue
        try:
            total += os.path.getsize(path)
        except OSError:
            missing.append(os.path.basename(path))
    return missing, total


def _attach_file(message: EmailMessage, file_path: str) -> None:
    ctype, encoding = mimetypes.guess_type(file_path)
    if ctype is None or encoding is not None:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)

    with open(file_path, "rb") as f:
        file_data = f.read()

    filename = os.path.basename(file_path)
    message.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=filename)


def _build_message(subject: str, body_text: str, file_paths: list) -> EmailMessage:
    message = EmailMessage()
    message["From"] = _get_address()
    message["Subject"] = subject
    message.set_content(body_text)
    for file_path in file_paths:
        _attach_file(message, file_path)
    return message


def send_email_with_attachments(to_email: str, subject: str, body_text: str, file_paths: list) -> None:
    """Bitta email manziliga, bir nechta fayl biriktirilgan bitta xat yuboradi."""
    result = send_batch_to_multiple([to_email], subject, body_text, file_paths)
    error = result.get(to_email)
    if error:
        raise GmailError(error)


def send_batch_to_multiple(emails: list, subject: str, body_text: str, file_paths: list) -> dict:
    """
    Bir nechta email manziliga ALOHIDA-ALOHIDA, har biriga BARCHA fayllar
    biriktirilgan holda xat yuboradi (mijozlar bir-birining manzilini ko'rmaydi).

    Qaytaradi: {"email@example.com": None (muvaffaqiyatli) yoki "xatolik matni", ...}

    Fayllar bir marta o'qiladi va SMTP ulanishi bir marta ochiladi - barcha
    manzillarga shu bitta ulanish orqali yuboriladi.
    """
    if not emails:
        return {}

    # Ulanish yoki fayllarni tayyorlashdagi xatolik - hamma manzilga tegishli
    try:
        if not file_paths:
            raise GmailError("Biror fayl biriktirilmagan.")
        missing, total = check_attachments(file_paths)
        if missing:
            raise GmailError("Bu fayllar diskda topilmadi: " + ", ".join(missing))
        if total > MAX_TOTAL_BYTES:
            raise GmailError(
                f"Fayllar hajmi juda katta ({total / 1024 / 1024:.1f} MB). "
                f"Gmail chegarasi ~{MAX_TOTAL_BYTES // 1024 // 1024} MB."
            )
        base_message = _build_message(subject, body_text, file_paths)
        server = _connect()
    except GmailError as e:
        return {email: str(e) for email in emails}
    except Exception as e:
        logger.exception("Xat tayyorlashda kutilmagan xatolik")
        return {email: f"Kutilmagan xatolik: {e}" for email in emails}

    results = {}
    try:
        for email in emails:
            try:
                message = copy.deepcopy(base_message)
                del message["To"]
                message["To"] = email
                server.send_message(message)
                results[email] = None
            except smtplib.SMTPServerDisconnected as e:
                # Ulanish uzilib qolgan - qayta ulanib, shu manzilga yana urinamiz
                logger.warning("SMTP ulanishi uzildi, qayta ulanmoqda: %s", e)
                try:
                    server = _connect()
                    message = copy.deepcopy(base_message)
                    del message["To"]
                    message["To"] = email
                    server.send_message(message)
                    results[email] = None
                except Exception as e2:
                    logger.exception("%s manziliga xat yuborilmadi", email)
                    results[email] = str(e2)[:200]
            except Exception as e:
                logger.exception("%s manziliga xat yuborilmadi", email)
                results[email] = str(e)[:200]
    finally:
        try:
            server.quit()
        except Exception:
            try:
                server.close()
            except Exception:
                pass

    return results
