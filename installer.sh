#!/bin/sh
# E2 Store installer / updater  -  يوضع في جذر المستودع، و REPO يشير إلى مجلد E2Store
# الاستخدام:  sh installer.sh            (يثبّت ثم يعيد تشغيل الواجهة)
#             sh installer.sh norestart  (يثبّت فقط - يستخدمه زر التحديث داخل البانل)
REPO="https://raw.githubusercontent.com/major79879/E2-Store-Panel/refs/heads/main/E2Store"
DIR="/usr/lib/enigma2/python/Plugins/Extensions/E2Store"
TMP="/tmp/e2store_update"

rm -rf "$TMP"
mkdir -p "$TMP"

# 1) حمّل كل الملفات أولاً - لا نلمس النسخة المثبتة إلا بعد نجاح التحميل كاملاً
for f in __init__.py lstparser.py plugin.py plugin.png; do
    echo "Downloading $f ..."
    # __init__.py فارغ بطبيعته، لذلك لا نفحص حجمه
    if ! wget -q --no-check-certificate "$REPO/$f" -O "$TMP/$f" || { [ "$f" != "__init__.py" ] && [ ! -s "$TMP/$f" ]; }; then
        echo "Failed to download: $f"
        echo "Nothing was changed."
        rm -rf "$TMP"
        exit 1
    fi
done

# 2) ثبّت
echo "Installing files ..."
mkdir -p "$DIR/boxes"   # مجلد اختياري لصور الأجهزة مثل sf8008.png
cp -rf "$TMP"/. "$DIR"/ || { echo "Copy failed"; rm -rf "$TMP"; exit 1; }
chmod -R 755 "$DIR"
rm -rf "$TMP"
echo "E2 Store Panel installed successfully."

# 3) إعادة تشغيل الواجهة (إلا عند استدعائه من داخل البانل)
if [ "$1" != "norestart" ]; then
    echo "Restarting GUI..."
    sleep 2
    killall -9 enigma2
fi
exit 0
