#!/bin/sh
# E2 Store installer  -  عدّل REPO ليشير إلى مستودعك على GitHub
REPO="https://raw.githubusercontent.com/major79879/LinuxCommands/refs/heads/main/E2Store"
DIR="/usr/lib/enigma2/python/Plugins/Extensions/E2Store"
mkdir -p "$DIR"
for f in __init__.py lstparser.py plugin.py plugin.png; do
    wget -q --no-check-certificate "$REPO/$f" -O "$DIR/$f" || { echo "Failed: $f"; exit 1; }
done
echo "E2 Store installed. Restarting GUI..."
sleep 2
killall -9 enigma2
