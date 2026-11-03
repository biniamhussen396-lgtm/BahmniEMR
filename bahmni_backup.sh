#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/backups/bahmni"
VOL_BASE="/var/lib/docker/volumes"
DATE=$(date +%Y%m%d_%H%M%S)
LOG="$BACKUP_DIR/backup_$DATE.log"

mkdir -p "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR/volumes"
mkdir -p "$BACKUP_DIR/images"

# ── Progress bar ──────────────────────────────────────────────────────────────

TOTAL_STEPS=40
CURRENT_STEP=0

progress() {
  local pct=$((CURRENT_STEP * 100 / TOTAL_STEPS))
  local filled=$((pct / 5))
  local empty=$((20 - filled))
  local bar=""
  for ((i=0; i<filled; i++)); do bar="${bar}█"; done
  for ((i=0; i<empty; i++)); do bar="${bar}░"; done
  printf "\r  [%s] %3d%% — %s" "$bar" "$pct" "$1"
  if [ "$2" = "done" ]; then
    echo "" | tee -a "$LOG"
  fi
}

echo "=== Bahmni Backup Started: $DATE ===" | tee -a "$LOG"
echo "Free disk space before backup:" | tee -a "$LOG"
df -h "$BACKUP_DIR" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Databases ─────────────────────────────────────────────────────────────────

CURRENT_STEP=1
progress "Backing up OpenMRS..."
docker exec bahmni-standard-openmrsdb-1 mysqldump -uroot -p'adminAdmin!123' openmrs \
  2>/dev/null | gzip > "$BACKUP_DIR/openmrs_$DATE.sql.gz"
echo "" | tee -a "$LOG"
echo "  ✓ OpenMRS — $(du -sh $BACKUP_DIR/openmrs_$DATE.sql.gz | cut -f1)" | tee -a "$LOG"

CURRENT_STEP=5
progress "Backing up Odoo..."
docker exec bahmni-standard-odoodb-1 pg_dump -U odoo -d odoo \
  2>/dev/null | gzip > "$BACKUP_DIR/odoo_$DATE.pgsql.gz"
echo "" | tee -a "$LOG"
echo "  ✓ Odoo — $(du -sh $BACKUP_DIR/odoo_$DATE.pgsql.gz | cut -f1)" | tee -a "$LOG"

CURRENT_STEP=9
progress "Backing up OpenELIS..."
docker exec bahmni-standard-openelisdb-1 pg_dump -U clinlims -d clinlims \
  2>/dev/null | gzip > "$BACKUP_DIR/clinlims_$DATE.pgsql.gz"
echo "" | tee -a "$LOG"
echo "  ✓ OpenELIS — $(du -sh $BACKUP_DIR/clinlims_$DATE.pgsql.gz | cut -f1)" | tee -a "$LOG"

CURRENT_STEP=13
progress "Backing up Bahmni Reports..."
docker exec bahmni-standard-reportsdb-1 mysqldump -uroot -p'adminAdmin!123' bahmni_reports \
  2>/dev/null | gzip > "$BACKUP_DIR/bahmni_reports_$DATE.sql.gz"
echo "" | tee -a "$LOG"
echo "  ✓ Reports — $(du -sh $BACKUP_DIR/bahmni_reports_$DATE.sql.gz | cut -f1)" | tee -a "$LOG"

CURRENT_STEP=17
progress "Backing up PACS DB..."
docker exec bahmni-standard-pacsdb-1 pg_dump -U postgres -d pacs_db \
  2>/dev/null | gzip > "$BACKUP_DIR/pacsdb_$DATE.pgsql.gz"
echo "" | tee -a "$LOG"
echo "  ✓ PACS — $(du -sh $BACKUP_DIR/pacsdb_$DATE.pgsql.gz | cut -f1)" | tee -a "$LOG"

# ── File Volumes ──────────────────────────────────────────────────────────────

echo "" | tee -a "$LOG"
echo "--- VOLUME BACKUPS ---" | tee -a "$LOG"

VOLUME_LIST=(
  "bahmni-standard_bahmni-document-images"
  "bahmni-standard_bahmni-patient-images"
  "bahmni-standard_bahmni-clinical-forms"
  "bahmni-standard_bahmni-lab-results"
  "bahmni-standard_bahmni-uploaded-files"
  "bahmni-standard_bahmni-queued-reports"
  "bahmni-standard_dcm4chee-archive"
  "bahmni-standard_dcm4chee-config"
  "bahmni-standard_odoofilestore"
  "bahmni-standard_odooappdata"
  "bahmni-standard_odooconfig"
  "bahmni-standard_sms-token"
)
VOL_COUNT=${#VOLUME_LIST[@]}
VOL_START=20
VOL_END=33

backup_volume() {
  local NAME=$1
  local IDX=$2
  local VOL_PCT=$((VOL_START + (IDX * (VOL_END - VOL_START) / VOL_COUNT)))
  CURRENT_STEP=$VOL_PCT
  progress "Backing up volume: $NAME"

  local SRC="$VOL_BASE/$NAME/_data"
  local DEST="$BACKUP_DIR/volumes/${NAME}_$DATE.tar.gz"

  if [ ! -d "$SRC" ]; then
    echo "" | tee -a "$LOG"
    echo "  SKIP: Volume not found: $NAME" | tee -a "$LOG"
    return
  fi

  tar -czf "$DEST" -C "$SRC" . 2>>"$LOG"
  echo "" | tee -a "$LOG"
  echo "  ✓ $NAME — $(du -sh $DEST | cut -f1)" | tee -a "$LOG"
}

for i in "${!VOLUME_LIST[@]}"; do
  backup_volume "${VOLUME_LIST[$i]}" "$i"
done

# ── Docker Images ─────────────────────────────────────────────────────────────

echo "" | tee -a "$LOG"
echo "--- DOCKER IMAGE BACKUPS ---" | tee -a "$LOG"

IMAGE_LIST=(
  "bahmni/openmrs:1.1.1-bi-1.0.2"
  "bahmni/odoo-16:1.0.0-bi-1.0.3"
  "bahmni/openelis:1.0.0-bi-1.0.0"
  "bahmni/bahmni-web:1.1.0-bi-1.0.0"
  "bahmni/lab-result-sync:1.0.2-remove-validation"
  "bahmni/global_property:bi-1.0.2"
  "bahmni/patient-documents:1.1.1"
  "bahmni/implementer-interface:1.1.1"
  "bahmni/reports:1.1.0"
  "bahmni/odoo-connect:1.0.0"
  "bahmni/proxy:1.1.0"
  "bahmni/dcm4chee:1.0.0"
  "bahmni/pacs-integration:1.0.0"
  "bahmni/microfrontend-ipd:1.0.0"
  "bahmni/appointments:1.1.1"
  "bahmni/atomfeed-console:1.0.0"
  "bahmni/openmrs-db:1.0.0-standard"
  "bahmni/odoo-16-db:1.0.0-standard"
  "bahmni/openelis-db:1.0.0-standard"
  "postgres:9.6"
  "mysql:8.0"
)
IMG_COUNT=${#IMAGE_LIST[@]}
IMG_START=34
IMG_END=39

for i in "${!IMAGE_LIST[@]}"; do
  local IMG_PCT=$((IMG_START + (i * (IMG_END - IMG_START) / IMG_COUNT)))
  CURRENT_STEP=$IMG_PCT
  local IMAGE="${IMAGE_LIST[$i]}"
  local SAFE_NAME=$(echo "$IMAGE" | tr '/:' '__')

  if [ -f "$BACKUP_DIR/images/${SAFE_NAME}.tar.gz" ]; then
    progress "Image (cached): $IMAGE"
    echo "" | tee -a "$LOG"
    echo "  ✓ $IMAGE (already exists)" | tee -a "$LOG"
    continue
  fi

  progress "Saving image: $IMAGE"
  docker save "$IMAGE" 2>/dev/null | gzip > "$BACKUP_DIR/images/${SAFE_NAME}.tar.gz"
  echo "" | tee -a "$LOG"
  echo "  ✓ $IMAGE — $(du -sh $BACKUP_DIR/images/${SAFE_NAME}.tar.gz | cut -f1)" | tee -a "$LOG"
done

# ── Cleanup ───────────────────────────────────────────────────────────────────

CURRENT_STEP=39
progress "Cleaning old backups (>7 days)..."
find "$BACKUP_DIR"         -maxdepth 1 -name "*.sql.gz"   -mtime +7 -delete 2>/dev/null
find "$BACKUP_DIR"         -maxdepth 1 -name "*.pgsql.gz" -mtime +7 -delete 2>/dev/null
find "$BACKUP_DIR"         -maxdepth 1 -name "*.log"      -mtime +7 -delete 2>/dev/null
find "$BACKUP_DIR/volumes" -maxdepth 1 -name "*.tar.gz"   -mtime +7 -delete 2>/dev/null
echo "" | tee -a "$LOG"

# ── Final ─────────────────────────────────────────────────────────────────────

CURRENT_STEP=$TOTAL_STEPS
progress "Complete!" "done"

echo "" | tee -a "$LOG"
echo "=== Backup Complete: $(date) ===" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "--- Database backups ---" | tee -a "$LOG"
ls -lh "$BACKUP_DIR"/*.gz 2>/dev/null | tee -a "$LOG"
echo "--- Volume backups ---" | tee -a "$LOG"
ls -lh "$BACKUP_DIR/volumes/" 2>/dev/null | tee -a "$LOG"
echo "--- Total backup size ---" | tee -a "$LOG"
du -sh "$BACKUP_DIR" | tee -a "$LOG"
echo "--- Free disk space after backup ---" | tee -a "$LOG"
df -h "$BACKUP_DIR" | tee -a "$LOG"
