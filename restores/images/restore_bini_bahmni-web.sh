#!/bin/bash

# Usage: bash restore_bini_bahmni-web.sh

IMAGE="bahmni_bahmni-web:1.1.0-bi-1.0.0"
BACKUP_DIR="$(dirname "$0")/../../backups/bahmni"
FILE="$BACKUP_DIR/images/bahmni_bahmni-web_1.1.0-bi-1.0.0.tar.gz"

echo "=== Image Restore: $IMAGE ==="

if [ ! -f "$FILE" ]; then
  echo "ERROR: File not found: $FILE"; exit 1
fi

echo "Loading image from $FILE..."
docker load -i "$FILE"
echo "Image restored. Exit: $?"
