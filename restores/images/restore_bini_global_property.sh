#!/bin/bash

# Usage: bash restore_bini_global_property.sh

IMAGE="bahmni_global_property:bi-1.0.2"
BACKUP_DIR="$(dirname "$0")/../../backups/bahmni"
FILE="$BACKUP_DIR/images/bahmni_global_property_bi-1.0.2.tar.gz"

echo "=== Image Restore: $IMAGE ==="

if [ ! -f "$FILE" ]; then
  echo "ERROR: File not found: $FILE"; exit 1
fi

echo "Loading image from $FILE..."
docker load -i "$FILE"
echo "Image restored. Exit: $?"
