#!/bin/bash

ZIP_URL="https://github.com/Telekatz/gui-v2/releases/latest/download/venus-webassembly.zip"
TARGET_DIR="/var/www/venus/gui-v2"
BACKUP_DIR="/var/www/venus/gui-v2-backup"

if [ ! -L "$BACKUP_DIR" ]; then
    mv "$TARGET_DIR" "$BACKUP_DIR"
fi

wget -O /tmp/venus-webassembly.zip "$ZIP_URL"

unzip -o /tmp/venus-webassembly.zip "wasm/*" -d /tmp
rm -R -f /var/www/venus/gui-v2

mv /tmp/wasm "$TARGET_DIR"

rm /tmp/venus-webassembly.zip
