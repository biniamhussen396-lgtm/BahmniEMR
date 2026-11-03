#!/bin/bash

# Usage: bash restore_bini_odoo-16.sh

IMAGE="bahmni_odoo-16:1.0.0-bi-1.0.3"
BACKUP_DIR="$(dirname "$0")/../../backups/bahmni"
FILE="$BACKUP_DIR/images/bahmni_odoo-16_1.0.0-bi-1.0.3.tar.gz"

echo "=== Image Restore: $IMAGE ==="

if [ ! -f "$FILE" ]; then
  echo "ERROR: File not found: $FILE"; exit 1
fi

echo "Loading image from $FILE..."
docker load -i "$FILE"
echo "Image restored. Exit: $?"
