#!/bin/bash

ZIP_URL="https://github.com/Telekatz/gui-v2/releases/latest/download/venus-webassembly.zip"
TARGET_DIR="/var/www/venus/gui-v2-mod"
SYMLINK="/var/www/venus/gui-v2"
BACKUP_SYMLINK="/var/www/venus/gui-v2-backup"

wget -O /tmp/venus-webassembly.zip "$ZIP_URL"

mkdir -p "$TARGET_DIR"

unzip -o /tmp/venus-webassembly.zip "wasm/*" -d /tmp
rm -R -f /var/www/venus/gui-v2-mod

mv /tmp/wasm "$TARGET_DIR"

if [ ! -L "$BACKUP_SYMLINK" ]; then
    cp -P "$SYMLINK" "$BACKUP_SYMLINK"
fi

ln -sfn "$TARGET_DIR" "$SYMLINK"

rm /tmp/venus-webassembly.zip
