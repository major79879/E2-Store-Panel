#!/bin/sh
# Major Enigma Panel installer / updater  -  يوضع في جذر المستودع، و REPO يشير إلى مجلد MajorPanel
# الاستخدام:  sh installer.sh            (يثبّت ثم يعيد تشغيل الواجهة بعد 5 ثوانٍ)
#             sh installer.sh norestart  (يثبّت فقط - يستخدمه زر التحديث داخل البانل)
# لتغيير المستودع عدّل BASE فقط (ونفس العنوان GITHUB_RAW في أول plugin.py)

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

BASE="https://raw.githubusercontent.com/major79879/Major-Enigma-Panel/refs/heads/main"
REPO="$BASE/MajorPanel"
DIR="/usr/lib/enigma2/python/Plugins/Extensions/MajorPanel"
TMP="/tmp/majorpanel_update"

C0='\033[0m'; CB='\033[0;34m'; CC='\033[0;36m'; CG='\033[0;32m'; CY='\033[1;33m'; CR='\033[1;31m'
say() { printf '%b%s%b\n' "$1" "$2" "$C0"; }

rm -rf "$TMP"
mkdir -p "$TMP"

say "$CC" "=========================================================="
say "$CY" "===              Major Enigma Panel                    ==="
say "$CC" "=========================================================="
echo ""

# 1) حمّل كل الملفات أولاً - لا نلمس النسخة المثبتة إلا بعد نجاح التحميل كاملاً
for f in __init__.py lstparser.py plugin.py assets.py plugin.png; do
    say "$CB" "> Downloading $f ..."
    # __init__.py فارغ بطبيعته، لذلك لا نفحص حجمه
    if ! wget -q --no-check-certificate "$REPO/$f" -O "$TMP/$f" || { [ "$f" != "__init__.py" ] && [ ! -s "$TMP/$f" ]; }; then
        say "$CR" "> Failed to download: $f"
        say "$CR" "> Nothing was changed."
        rm -rf "$TMP"
        exit 1
    fi
done

# 2) ثبّت
say "$CB" "> Installing files ..."
mkdir -p "$DIR/boxes"   # مجلد اختياري لصور الأجهزة مثل sf8008.png
cp -rf "$TMP"/. "$DIR"/ || { say "$CR" "> Copy failed"; rm -rf "$TMP"; exit 1; }
say "$CB" "> Setting file permissions ..."
chmod -R 755 "$DIR"
say "$CB" "> Cleaning temporary files ..."
rm -rf "$TMP"

echo ""
say "$CC" "=========================================================="
say "$CG" "===              Installation Successful!              ==="
say "$CY" "===              Major Enigma Panel                    ==="
say "$CB" "===              By John Kamel                         ==="
say "$CC" "=========================================================="
echo ""

# 3) إعادة تشغيل الواجهة (إلا عند استدعائه من داخل البانل)
if [ "$1" != "norestart" ]; then
    say "$CY" "Enigma2 will restart automatically after 5 seconds..."
    i=5
    while [ "$i" -gt 0 ]; do
        say "$CY" "Restarting in $i seconds..."
        sleep 1
        i=$((i - 1))
    done
    say "$CG" "> Restarting Enigma2..."
    killall -9 enigma2
fi
exit 0
