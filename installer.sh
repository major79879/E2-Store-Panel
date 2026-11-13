#!/bin/sh
# Major Enigma Panel - installer
# يُشغَّل من جذر مستودع GitHub. يتأكد من وجود openssl (يلزم لفك تشفير الحزمة)،
# ثم يُنزّل حزمة MajorEnigmaPanel المشفّرة (.ipk) ويثبّتها عبر opkg.
# فكّ التشفير يتم مرة واحدة فقط داخل postinst أثناء التثبيت، ولا يترك أي أثر مشفّر على الجهاز بعدها.

printf '%s\n' '==============================================='
printf '%s\n' '   __  __    ___         _     ___     ____    '
printf '%s\n' '  |  \/  |  / _ \       | |   / _ \   |  _ \   '
printf '%s\n' '  | |\/| | | |_| |      | |  | | | |  | |_) |  '
printf '%s\n' '  | |  | | |  _  |   _ _| |  | |_| |  |  _ <   '
printf '%s\n' '  |_|  |_| |_| |_|   \___/    \___/   |_| \_\  '
printf '%s\n' '   ____      ___     _   _    _____    _       '
printf '%s\n' '  |  _ \    / _ \   | \ | |  | ____|  | |      '
printf '%s\n' '  | |_) |  | |_| |  |  \| |  |  _|    | |      '
printf '%s\n' '  |  __/   |  _  |  | |\  |  | |___   | |___   '
printf '%s\n' '  |_|      |_| |_|  |_| \_|  |_____|  |_____|  '
printf '%s\n' '==============================================='
printf '%s\n' '           MAJOR ENIGMA PANEL UPDATER          '
printf '%s\n' '            Developed by: John Kamel           '
printf '%s\n' '==============================================='

REPO="https://raw.githubusercontent.com/major79879/Major-Enigma-Panel/refs/heads/main"
PKG="MajorEnigmaPanel_1.0-1_all.ipk"
TMP="/tmp/$PKG"

if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl غير موجود على الجهاز - جارٍ تثبيته ..."
    opkg update >/dev/null 2>&1
    opkg install openssl
    if ! command -v openssl >/dev/null 2>&1; then
        echo "تعذّر تثبيت openssl تلقائياً. ثبّته يدوياً من قائمة الإضافات (Softcam/Tools) ثم أعد تشغيل هذا السكربت."
        exit 1
    fi
    echo "تم تثبيت openssl بنجاح."
fi

echo "Downloading $PKG ..."
wget -q "$REPO/$PKG" -O "$TMP" || { echo "Download failed"; exit 1; }

echo "Installing ..."
opkg install --force-reinstall --force-overwrite "$TMP"
RC=$?

rm -f "$TMP"
exit $RC
