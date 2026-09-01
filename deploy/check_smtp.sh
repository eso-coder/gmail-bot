#!/usr/bin/env bash
#
# VPS SMTP portlarini bloklaganmi - TEKSHIRISH.
# Serverni sotib olgach ENG BIRINCHI shuni ishga tushiring:
#
#     bash <(curl -fsSL https://raw.githubusercontent.com/eso-coder/gmail-bot/main/deploy/check_smtp.sh)
#
# Agar ikkala port ham yopiq bo'lsa - bu VPS bizga yaramaydi,
# pulni qaytarib oling (yoki boshqa provayder tanlang).

echo "Gmail SMTP portlari tekshirilmoqda (smtp.gmail.com)..."
echo

ok=0
for port in 465 587; do
    printf "  port %-4s ... " "$port"
    if timeout 10 bash -c "cat < /dev/null > /dev/tcp/smtp.gmail.com/$port" 2>/dev/null; then
        echo "OCHIQ ✅"
        ok=1
    else
        echo "YOPIQ ❌"
    fi
done

echo
if [ "$ok" = "1" ]; then
    echo "NATIJA: ✅ Bu server BIZGA TO'G'RI KELADI."
    echo "        O'rnatishni davom ettirsak bo'ladi."
else
    echo "NATIJA: ❌ Provayder SMTP'ni bloklagan."
    echo "        Bu serverda bot xat yubora olmaydi."
    echo "        Provayderdan portni ochishni so'rang yoki boshqasini tanlang."
fi
