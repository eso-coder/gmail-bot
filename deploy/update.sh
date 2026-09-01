#!/usr/bin/env bash
#
# Botni GitHub'dagi so'nggi versiyaga yangilash.
# Ishlatish (server terminalida, root sifatida):
#     bash /opt/gmail-bot/deploy/update.sh
#
# Ma'lumotlar (/var/lib/gmail-bot) tegilmaydi - mijozlar, partiyalar,
# yig'ilgan hujjatlar joyida qoladi.

set -euo pipefail

APP_DIR="/opt/gmail-bot"
SERVICE="gmail-bot"
RUN_USER="gmailbot"

echo "==> Kod yangilanmoqda"
git -C "$APP_DIR" fetch --quiet origin
git -C "$APP_DIR" reset --hard --quiet origin/main

echo "==> Kutubxonalar"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade -r "$APP_DIR/requirements.txt"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"

echo "==> Qayta ishga tushirish"
systemctl restart "$SERVICE"
sleep 3
systemctl --no-pager status "$SERVICE" | head -20

echo
echo "Tayyor. Loglar:  journalctl -u $SERVICE -f"
