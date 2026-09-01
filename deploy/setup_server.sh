#!/usr/bin/env bash
#
# Export hujjatlar botini Ubuntu serverga o'rnatish (bir marta ishga tushiriladi).
#
# Ishlatish (server terminalida, root sifatida):
#   curl -fsSL https://raw.githubusercontent.com/eso-coder/gmail-bot/main/deploy/setup_server.sh | bash
#
# Yoki qo'lda:
#   wget https://raw.githubusercontent.com/eso-coder/gmail-bot/main/deploy/setup_server.sh
#   bash setup_server.sh
#
# Skript nima qiladi:
#   1. Python va git o'rnatadi
#   2. Kodni /opt/gmail-bot ga yuklaydi
#   3. Ma'lumotlar uchun /var/lib/gmail-bot papkasini yaratadi
#      (kod yangilanganda ma'lumotlar tegilmaydi)
#   4. Botni systemd xizmati qilib ro'yxatga oladi:
#      server qayta yuklansa ham, bot qulasa ham - o'zi ishga tushadi
#   5. .env faylini yaratadi (maxfiy qiymatlarni siz to'ldirasiz)

set -euo pipefail

REPO="https://github.com/eso-coder/gmail-bot.git"
APP_DIR="/opt/gmail-bot"
DATA_DIR="/var/lib/gmail-bot"
SERVICE="gmail-bot"
RUN_USER="gmailbot"

echo "==> 1/6  Tizim paketlari"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates tzdata

echo "==> 2/6  Vaqt zonasi: Asia/Tashkent"
timedatectl set-timezone Asia/Tashkent || true

echo "==> 3/6  Foydalanuvchi va papkalar"
id -u "$RUN_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"
mkdir -p "$DATA_DIR"
chown -R "$RUN_USER:$RUN_USER" "$DATA_DIR"

echo "==> 4/6  Kodni yuklash"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --quiet origin
    git -C "$APP_DIR" reset --hard --quiet origin/main
else
    rm -rf "$APP_DIR"
    git clone --quiet "$REPO" "$APP_DIR"
fi

echo "==> 5/6  Python muhiti"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"

# .env faylini yaratamiz (bor bo'lsa tegmaymiz)
if [ ! -f "$DATA_DIR/.env" ]; then
    cat > "$DATA_DIR/.env" <<'ENVEOF'
# Maxfiy sozlamalar. Qiymatlarni to'ldiring va botni qayta ishga tushiring:
#   systemctl restart gmail-bot
BOT_TOKEN=
GROUP_CHAT_ID=
ADMIN_USER_ID=
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=
ENVEOF
fi
chown "$RUN_USER:$RUN_USER" "$DATA_DIR/.env"
chmod 600 "$DATA_DIR/.env"
ln -sf "$DATA_DIR/.env" "$APP_DIR/.env"

echo "==> 6/6  systemd xizmati"
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=Export hujjatlar Telegram boti
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
Environment=DATA_DIR=${DATA_DIR}
Environment=TZ=Asia/Tashkent
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/bot.py

# Bot qulasa yoki server qayta yuklansa - avtomatik tiklanadi
Restart=always
RestartSec=10

# Xavfsizlik
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${DATA_DIR}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --quiet "$SERVICE"

echo
echo "======================================================"
echo " O'RNATILDI"
echo "======================================================"
echo
echo " Endi maxfiy sozlamalarni to'ldiring:"
echo "     nano $DATA_DIR/.env"
echo
echo " So'ng botni ishga tushiring:"
echo "     systemctl restart $SERVICE"
echo
echo " Holatini ko'rish:"
echo "     systemctl status $SERVICE"
echo "     journalctl -u $SERVICE -f"
echo
echo " Keyinchalik yangilash:"
echo "     bash $APP_DIR/deploy/update.sh"
echo
