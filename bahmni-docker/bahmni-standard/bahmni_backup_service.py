#!/usr/bin/env python3
"""
Bahmni Unified Backup and Restore Service & CLI.
Supports:
  - Full System Backup (Databases, Modules/Images, Docker Volumes, Patches & Configs)
  - Database-Only Backup (OpenMRS, OpenELIS clinlims, Odoo, Reports, PACS)
  - Restore (Databases, Volumes, Web UI Patches, Service Cycling)
  - Built-in HTTP API daemon for web UI integration
"""

import argparse
import base64
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tarfile
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BACKUP_DIR = os.environ.get("BACKUP_DIR") or (
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backups"))
    if os.name == "nt" or not os.path.exists("/opt/emr/backups")
    else "/opt/emr/backups"
)
CONFIG_DIR = os.environ.get("CONFIG_DIR") or (
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config"))
    if os.name == "nt" or not os.path.exists("/opt/emr/config")
    else "/opt/emr/config"
)
APP_DIR = os.environ.get("APP_DIR") or (
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "apps", "ui", "app"))
    if os.name == "nt" or not os.path.exists("/opt/emr/app")
    else "/opt/emr/app"
)
VOL_BASE = os.environ.get("VOL_BASE", "/var/lib/docker/volumes")
RETENTION_LIMIT = int(os.environ.get("RETENTION_LIMIT", 10))
PORT = int(os.environ.get("BACKUP_PORT", 5055))

MYSQL_PASS = os.environ.get("MYSQL_ROOT_PASSWORD", "adminAdmin!123")

# Thread-safe operation lock and state
op_lock = threading.Lock()
current_op = {
    "status": "idle",       # "idle", "running", "completed", "error"
    "type": None,           # "full_backup", "db_backup", "restore"
    "message": "System ready",
    "started_at": None,
    "completed_at": None,
    "progress": 0,
    "logs": []
}

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    print(entry, flush=True)
    current_op["logs"].append(entry)
    if len(current_op["logs"]) > 200:
        current_op["logs"].pop(0)

def run_cmd(cmd, check=True):
    log(f"CMD: {cmd}")
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if res.stdout.strip():
        for line in res.stdout.strip().splitlines()[:10]:
            log(f"  {line}")
    if res.returncode != 0:
        err_msg = res.stderr.strip() or "Command failed with code " + str(res.returncode)
        log(f"ERROR: {err_msg}")
        if check:
            raise RuntimeError(err_msg)
    return res.stdout.strip()

def run_cmd_pipe_in(cmd, in_file_path, check=True):
    log(f"CMD (PIPE): {cmd} < {os.path.basename(in_file_path)}")
    try:
        with open(in_file_path, "rb") as f:
            res = subprocess.run(cmd, shell=True, stdin=f, capture_output=True)
        if res.returncode != 0:
            err_msg = res.stderr.decode("utf-8", errors="replace").strip() or f"Command failed with code {res.returncode}"
            log(f"ERROR: {err_msg}")
            if check:
                raise RuntimeError(err_msg)
        return res.stdout.decode("utf-8", errors="replace").strip()
    except Exception as e:
        log(f"PIPE ERROR: {e}")
        if check:
            raise
        return ""

def enforce_retention():
    try:
        archives = sorted(glob.glob(os.path.join(BACKUP_DIR, "bahmni_*.tar.gz")), key=os.path.getmtime, reverse=True)
        if len(archives) > RETENTION_LIMIT:
            log(f"Pruning archives exceeding limit of {RETENTION_LIMIT}...")
            for old in archives[RETENTION_LIMIT:]:
                try:
                    os.remove(old)
                    log(f"Removed old backup: {os.path.basename(old)}")
                except OSError:
                    pass
    except Exception as e:
        log(f"Retention check warning: {e}")

def get_container(name_hint):
    try:
        res = subprocess.run(f'docker ps --filter "name={name_hint}" --format "{{{{.Names}}}}"', shell=True, capture_output=True, text=True)
        names = [n.strip() for n in res.stdout.strip().splitlines() if n.strip()]
        for n in names:
            if n == f"bahmni-standard-{name_hint}-1" or n == name_hint:
                return n
        if names:
            return names[0]
    except Exception:
        pass
    return f"bahmni-standard-{name_hint}-1"

def dump_databases(target_dir):
    log("Dumping OpenMRS MySQL Database...")
    omrs = get_container("openmrsdb")
    run_cmd(f'docker exec {omrs} mysqldump -uroot -p"{MYSQL_PASS}" --single-transaction --routines --triggers openmrs > "{target_dir}/openmrs.sql"')

    log("Dumping OpenELIS ClinLIMS Database...")
    oelis = get_container("openelisdb")
    run_cmd(f'docker exec {oelis} pg_dump -U clinlims clinlims > "{target_dir}/clinlims.sql"', check=False)

    log("Dumping Odoo PostgreSQL Database...")
    odoo = get_container("odoodb")
    run_cmd(f'docker exec {odoo} pg_dump -U odoo odoo > "{target_dir}/odoo.sql"', check=False)

    log("Dumping Bahmni Reports Database...")
    reports = get_container("reportsdb")
    run_cmd(f'docker exec {reports} mysqldump -uroot -p"{MYSQL_PASS}" --single-transaction bahmni_reports > "{target_dir}/bahmni_reports.sql"', check=False)

    log("Dumping PACS Databases...")
    pacs = get_container("pacsdb")
    run_cmd(f'docker exec {pacs} pg_dump -U postgres pacs_db > "{target_dir}/pacs_db.sql"', check=False)
    run_cmd(f'docker exec {pacs} pg_dump -U postgres pacs_integration_db > "{target_dir}/pacs_integration_db.sql"', check=False)
    run_cmd(f'docker exec {pacs} pg_dump -U postgres bahmni_pacs > "{target_dir}/bahmni_pacs.sql"', check=False)

def dump_volumes(target_dir):
    volumes_dir = os.path.join(target_dir, "volumes")
    os.makedirs(volumes_dir, exist_ok=True)
    volume_list = [
        "bahmni-standard_bahmni-document-images",
        "bahmni-standard_bahmni-patient-images",
        "bahmni-standard_bahmni-clinical-forms",
        "bahmni-standard_bahmni-lab-results",
        "bahmni-standard_bahmni-uploaded-files",
        "bahmni-standard_bahmni-queued-reports",
        "bahmni-standard_dcm4chee-archive",
        "bahmni-standard_dcm4chee-config",
        "bahmni-standard_odoofilestore",
        "bahmni-standard_odooappdata",
        "bahmni-standard_odooconfig",
        "bahmni-standard_sms-token",
    ]
    for vol in volume_list:
        src = f"{VOL_BASE}/{vol}/_data"
        dest = f"{volumes_dir}/{vol}.tar.gz"
        if os.path.isdir(src):
            log(f"Archiving volume from host path: {vol}")
            run_cmd(f'tar -czf "{dest}" -C "{src}" . 2>/dev/null', check=False)
        else:
            log(f"Archiving volume via docker: {vol}")
            try:
                run_cmd(f'docker run --rm -v "{vol}:/voldata:ro" alpine tar -czf - -C /voldata . > "{dest}"', check=False)
            except Exception as e:
                log(f"Volume archive warning for {vol}: {e}")

def dump_modules(target_dir):
    modules_dir = os.path.join(target_dir, "modules")
    os.makedirs(modules_dir, exist_ok=True)
    images = [
        "selamsew/openmrs:1.1.1-uog-1.0.2",
        "selamsew/odoo-16:1.0.0-uog-1.0.3",
        "selamsew/openelis:1.0.0-uog-1.0.5",
        "selamsew/bahmni-web:1.1.0-uog-1.0.0",
        "selamsew/lab-result-sync:1.0.2-remove-validation",
        "selamsew/global_property:uog-1.0.2",
        "bahmni/patient-documents:1.1.1",
        "bahmni/implementer-interface:1.1.1",
        "bahmni/reports:1.1.0",
        "bahmni/odoo-connect:1.0.0",
        "bahmni/proxy:1.1.0",
        "bahmni/dcm4chee:1.0.0",
        "bahmni/pacs-integration:1.0.0",
        "bahmni/microfrontend-ipd:1.0.0",
        "bahmni/appointments:1.1.1",
        "bahmni/atomfeed-console:1.0.0",
        "bahmni/openmrs-db:1.0.0-standard",
        "bahmni/odoo-16-db:1.0.0-standard",
        "bahmni/openelis-db:1.0.0-standard",
        "postgres:9.6",
        "mysql:8.0",
    ]
    # Record metadata list of images
    with open(os.path.join(modules_dir, "manifest.json"), "w") as f:
        json.dump({"images": images, "created_at": datetime.datetime.now().isoformat()}, f, indent=2)
    log(f"Saved module and image manifests ({len(images)} container images)")

def dump_patches_and_config(target_dir):
    # Lab sync state
    run_cmd(f'docker cp lab-result-sync:/last_result.json "{target_dir}/lab_last_result.json"', check=False)
    # EMR app config
    if os.path.isdir(CONFIG_DIR):
        log("Archiving EMR Configs...")
        run_cmd(f'tar -czf "{target_dir}/emr_config.tar.gz" -C "{CONFIG_DIR}" .', check=False)
    # Web UI Patches
    web_dir = os.path.join(target_dir, "bahmni_web_patches")
    os.makedirs(web_dir, exist_ok=True)
    run_cmd(f'docker cp bahmni-standard-bahmni-web-1:/usr/local/apache2/htdocs/bahmni/registration/controllers/searchPatientController.js "{web_dir}/searchPatientController.js"', check=False)
    run_cmd(f'docker cp bahmni-standard-bahmni-web-1:/usr/local/apache2/htdocs/bahmni/registration/controllers/createCRTriagePatientController.js "{web_dir}/createCRTriagePatientController.js"', check=False)
    run_cmd(f'docker cp bahmni-standard-bahmni-web-1:/usr/local/apache2/htdocs/bahmni/common/logicAndConditionProcessors/skipLogicProcessor.js "{web_dir}/skipLogicProcessor.js"', check=False)
    run_cmd(f'docker cp bahmni-standard-bahmni-web-1:/usr/local/apache2/htdocs/bahmni/common/patient-search/controllers/patientsListController.js "{web_dir}/patientsListController.js"', check=False)
    run_cmd(f'docker cp bahmni-standard-bahmni-web-1:/usr/local/apache2/htdocs/bahmni/document-upload/index.html "{web_dir}/document_upload_index.html"', check=False)

def execute_full_backup():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"bahmni_full_backup_{ts}"
    staging = os.path.join(BACKUP_DIR, folder_name)
    archive_path = f"{staging}.tar.gz"

    os.makedirs(staging, exist_ok=True)
    metadata = {
        "type": "Full Backup",
        "description": "Entire system backup (Databases, Modules, Volumes, Config)",
        "timestamp": ts,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(os.path.join(staging, "backup_meta.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    current_op["progress"] = 10
    current_op["message"] = "Dumping databases..."
    dump_databases(staging)

    current_op["progress"] = 40
    current_op["message"] = "Archiving Docker data volumes..."
    dump_volumes(staging)

    current_op["progress"] = 70
    current_op["message"] = "Recording system modules and configs..."
    dump_modules(staging)
    dump_patches_and_config(staging)

    current_op["progress"] = 85
    current_op["message"] = f"Compressing into {os.path.basename(archive_path)}..."
    log(f"Compressing into {archive_path}...")
    try:
        run_cmd(f'tar -czf "{archive_path}" -C "{BACKUP_DIR}" "{folder_name}"')
    except Exception as e:
        log(f"tar command fallback to python tarfile: {e}")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(staging, arcname=folder_name)
    shutil.rmtree(staging, ignore_errors=True)

    enforce_retention()
    post_backup_sync(archive_path)
    current_op["progress"] = 100
    size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    current_op["message"] = f"Full backup completed successfully: {os.path.basename(archive_path)} ({size_mb:.1f} MB)"
    log(current_op["message"])
    return archive_path

def execute_db_backup():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"bahmni_db_backup_{ts}"
    staging = os.path.join(BACKUP_DIR, folder_name)
    archive_path = f"{staging}.tar.gz"

    os.makedirs(staging, exist_ok=True)
    metadata = {
        "type": "Database Backup",
        "description": "Database-only backup (OpenMRS, OpenELIS, Odoo, Reports, PACS)",
        "timestamp": ts,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(os.path.join(staging, "backup_meta.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    current_op["progress"] = 20
    current_op["message"] = "Dumping all databases..."
    dump_databases(staging)

    current_op["progress"] = 70
    current_op["message"] = "Backing up sync tracker..."
    run_cmd(f'docker cp lab-result-sync:/last_result.json "{staging}/lab_last_result.json"', check=False)

    current_op["progress"] = 85
    current_op["message"] = f"Compressing into {os.path.basename(archive_path)}..."
    try:
        run_cmd(f'tar -czf "{archive_path}" -C "{BACKUP_DIR}" "{folder_name}"')
    except Exception as e:
        log(f"tar command fallback to python tarfile: {e}")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(staging, arcname=folder_name)
    shutil.rmtree(staging, ignore_errors=True)

    enforce_retention()
    post_backup_sync(archive_path)
    current_op["progress"] = 100
    size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    current_op["message"] = f"Database backup completed successfully: {os.path.basename(archive_path)} ({size_mb:.1f} MB)"
    log(current_op["message"])
    return archive_path

def ensure_restore_privilege():
    try:
        omrs = get_container("openmrsdb")
        sql = (
            "INSERT IGNORE INTO privilege (privilege, description, uuid) VALUES "
            "('app:admin:restore', 'Bahmni Admin: Privilege to restore system backups and access restore operations', UUID()), "
            "('app:admin:deleteBackup', 'Bahmni Admin: Privilege to delete backup archives', UUID()); "
            "INSERT IGNORE INTO role_privilege (role, privilege) VALUES "
            "('SuperAdmin', 'app:admin:restore'), "
            "('SuperAdmin', 'app:admin:deleteBackup'), "
            "('System Developer', 'app:admin:restore'), "
            "('System Developer', 'app:admin:deleteBackup'), "
            "('Privilege Level: Full', 'app:admin:restore'), "
            "('Privilege Level: Full', 'app:admin:deleteBackup');"
        )
        res = subprocess.run(
            f'docker exec -i {omrs} mysql -uroot -p"{MYSQL_PASS}" openmrs -e "{sql}"',
            shell=True, capture_output=True, text=True
        )
        if res.returncode == 0:
            log("Verified OpenMRS 'app:admin:restore' and 'app:admin:deleteBackup' privileges.")
    except Exception as e:
        log(f"Warning verifying OpenMRS privileges: {e}")

def apply_frontend_patches():
    log("Applying routing, patient search, and null-safety patches to Bahmni-Web...")
    bweb = get_container("bahmni-web")
    # Safe UUID formatting
    run_cmd(
        f'docker exec -i {bweb} sed -i '
        r'\'s#\$location\.url("/patient/" + \$scope\.selectedPatient\.uuid + "/crTriageVisit");#'
        r'var cleanUuid = ($scope.selectedPatient.uuid || "").replace(/^\/+/g, ""); '
        r'\$location.url("/patient/" + cleanUuid + "/crTriageVisit");#g\' '
        '/usr/local/apache2/htdocs/bahmni/registration/controllers/searchPatientController.js',
        check=False
    )
    run_cmd(
        f'docker exec -i {bweb} sed -i '
        r'\'s#\$location\.url("/patient/" + \$scope\.selectedPatient\.uuid + "/prescription");#'
        r'var cleanUuid = ($scope.selectedPatient.uuid || "").replace(/^\/+/g, ""); '
        r'\$location.url("/patient/" + cleanUuid + "/prescription");#g\' '
        '/usr/local/apache2/htdocs/bahmni/registration/controllers/searchPatientController.js',
        check=False
    )
    # Safe patient search disposition injection
    run_cmd(
        f'docker exec -i {bweb} sed -i '
        '\'s#if(patient.activeVisitUuid){#if(patient.activeVisitUuid && dispositionService){#g\' '
        '/usr/local/apache2/htdocs/bahmni/common/patient-search/controllers/patientsListController.js',
        check=False
    )
    # Document upload dispositionService inclusion
    run_cmd(
        f'docker exec -i {bweb} grep -q "dispositionService.js" /usr/local/apache2/htdocs/bahmni/document-upload/index.html || '
        f'docker exec -i {bweb} sed -i \'/observationsService\\.js/a \\        <script src="../common/domain/services/dispositionService.js"></script>\' '
        '/usr/local/apache2/htdocs/bahmni/document-upload/index.html',
        check=False
    )

def execute_restore(archive_path):
    if not os.path.exists(archive_path):
        # Try finding in BACKUP_DIR
        alt_path = os.path.join(BACKUP_DIR, archive_path)
        if os.path.exists(alt_path):
            archive_path = alt_path
        else:
            raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    temp_dir = os.path.join(tempfile.gettempdir(), "bahmni_restore_unpack")
    shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)
    log(f"Extracting archive {os.path.basename(archive_path)}...")
    current_op["progress"] = 15
    current_op["message"] = "Extracting backup archive..."
    try:
        run_cmd(f'tar -xzf "{archive_path}" -C "{temp_dir}"')
    except Exception:
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(temp_dir, filter="data")
        except TypeError:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(temp_dir)

    # Locate source directory containing database dumps
    source_dir = temp_dir
    for root, dirs, files in os.walk(temp_dir):
        if "openmrs.sql" in files or "clinlims.sql" in files or "odoo.sql" in files or "backup_meta.json" in files:
            source_dir = root
            break

    # 1. OpenMRS
    openmrs_sql = os.path.join(source_dir, "openmrs.sql")
    if os.path.exists(openmrs_sql):
        current_op["progress"] = 30
        current_op["message"] = "Restoring OpenMRS database..."
        log("Restoring OpenMRS database...")
        omrs = get_container("openmrsdb")
        run_cmd(f'docker exec -i {omrs} mysql -uroot -p"{MYSQL_PASS}" -e "DROP DATABASE IF EXISTS openmrs; CREATE DATABASE openmrs CHARACTER SET utf8;"')
        run_cmd_pipe_in(f'docker exec -i {omrs} mysql -uroot -p"{MYSQL_PASS}" --default-character-set=utf8 openmrs', openmrs_sql)

    # 2. ClinLIMS / OpenELIS
    clinlims_sql = os.path.join(source_dir, "clinlims.sql")
    if os.path.exists(clinlims_sql):
        current_op["progress"] = 45
        current_op["message"] = "Restoring OpenELIS ClinLIMS database..."
        log("Restoring OpenELIS ClinLIMS database...")
        oelis = get_container("openelisdb")
        run_cmd(
            f'docker exec -i {oelis} psql -U clinlims -d postgres -c '
            '"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = \'clinlims\' AND pid <> pg_backend_pid();"',
            check=False
        )
        run_cmd(f"docker exec -i {oelis} dropdb -U clinlims --if-exists clinlims", check=False)
        run_cmd(f"docker exec -i {oelis} createdb -U clinlims clinlims", check=False)
        run_cmd_pipe_in(f'docker exec -i {oelis} psql -U clinlims -d clinlims', clinlims_sql, check=False)

    # 3. Odoo
    odoo_sql = os.path.join(source_dir, "odoo.sql")
    if os.path.exists(odoo_sql):
        current_op["progress"] = 60
        current_op["message"] = "Restoring Odoo ERP database..."
        log("Restoring Odoo ERP database...")
        odoo = get_container("odoodb")
        run_cmd(
            f'docker exec -i {odoo} psql -U odoo -d postgres -c '
            '"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = \'odoo\' AND pid <> pg_backend_pid();"',
            check=False
        )
        run_cmd(f"docker exec -i {odoo} dropdb -U odoo --if-exists odoo", check=False)
        run_cmd(f"docker exec -i {odoo} createdb -U odoo odoo", check=True)
        run_cmd_pipe_in(f'docker exec -i {odoo} psql -U odoo -d odoo', odoo_sql, check=False)

    # 4. Reports
    reports_sql = os.path.join(source_dir, "bahmni_reports.sql")
    if os.path.exists(reports_sql) and os.path.getsize(reports_sql) > 0:
        current_op["progress"] = 70
        current_op["message"] = "Restoring Bahmni Reports database..."
        log("Restoring Bahmni Reports database...")
        reports = get_container("reportsdb")
        run_cmd(f'docker exec -i {reports} mysql -uroot -p"{MYSQL_PASS}" -e "DROP DATABASE IF EXISTS bahmni_reports; CREATE DATABASE bahmni_reports CHARACTER SET utf8;"', check=False)
        run_cmd_pipe_in(f'docker exec -i {reports} mysql -uroot -p"{MYSQL_PASS}" --default-character-set=utf8 bahmni_reports', reports_sql, check=False)

    # 5. PACS
    pacs = get_container("pacsdb")
    pacs_sql = os.path.join(source_dir, "pacs_db.sql")
    if os.path.exists(pacs_sql):
        log("Restoring PACS databases...")
        run_cmd_pipe_in(f'docker exec -i {pacs} psql -U postgres -d pacs_db', pacs_sql, check=False)
    pacs_int_sql = os.path.join(source_dir, "pacs_integration_db.sql")
    if os.path.exists(pacs_int_sql):
        run_cmd_pipe_in(f'docker exec -i {pacs} psql -U postgres -d pacs_integration_db', pacs_int_sql, check=False)
    bahmni_pacs_sql = os.path.join(source_dir, "bahmni_pacs.sql")
    if os.path.exists(bahmni_pacs_sql):
        run_cmd_pipe_in(f'docker exec -i {pacs} psql -U postgres -d bahmni_pacs', bahmni_pacs_sql, check=False)

    # 6. Volumes (if present in archive)
    volumes_dir = os.path.join(source_dir, "volumes")
    if os.path.isdir(volumes_dir):
        current_op["progress"] = 80
        current_op["message"] = "Restoring Docker volumes..."
        log("Restoring Docker data volumes...")
        for vol_tar in glob.glob(f"{volumes_dir}/*.tar.gz"):
            vol_name = os.path.basename(vol_tar).replace(".tar.gz", "")
            vol_dest = f"{VOL_BASE}/{vol_name}/_data"
            if os.path.isdir(vol_dest):
                log(f"Extracting volume from host path: {vol_name}...")
                run_cmd(f'tar -xzf "{vol_tar}" -C "{vol_dest}"', check=False)
            else:
                log(f"Restoring volume via docker stdin: {vol_name}")
                run_cmd_pipe_in(f'docker run --rm -i -v "{vol_name}:/voldata" alpine tar -xzf - -C /voldata', vol_tar, check=False)

    # 7. Lab sync state
    lab_json = os.path.join(source_dir, "lab_last_result.json")
    if os.path.exists(lab_json):
        sync_c = get_container("lab-result-sync")
        run_cmd_pipe_in(f'docker exec -i {sync_c} sh -c "cat > /last_result.json"', lab_json, check=False)

    # Clean unpack
    shutil.rmtree(temp_dir, ignore_errors=True)

    # 8. Apply frontend patches & ensure restore privilege in OpenMRS
    current_op["progress"] = 90
    current_op["message"] = "Applying Web UI patches & verifying privileges..."
    apply_frontend_patches()
    ensure_restore_privilege()

    # 9. Cycling services
    current_op["progress"] = 95
    current_op["message"] = "Restarting application containers..."
    log("Restarting application containers...")
    c_list = [get_container(x) for x in ["odoo-connect", "atomfeed-console", "openmrs", "openelis", "odoo"]]
    run_cmd(f"docker restart {' '.join(c_list)}", check=False)

    current_op["progress"] = 100
    current_op["message"] = f"Restore completed successfully from {os.path.basename(archive_path)}"
    log(current_op["message"])

def list_backups():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    archives = glob.glob(os.path.join(BACKUP_DIR, "bahmni_*.tar.gz"))
    archives.sort(key=os.path.getmtime, reverse=True)
    items = []
    for arc in archives:
        stat = os.stat(arc)
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_mb = round(stat.st_size / (1024 * 1024), 2)
        base = os.path.basename(arc)
        if "full" in base:
            b_type = "Full Backup (DB + Volumes + Modules)"
        elif "db" in base:
            b_type = "Database Only Backup"
        else:
            b_type = "Standard Backup"
        items.append({
            "name": base,
            "path": arc,
            "size_mb": size_mb,
            "modified": mtime,
            "type": b_type,
            "download_url": f"/backup-api/download/{base}"
        })
    return items

def delete_backup(archive_name):
    safe_name = os.path.basename(archive_name.strip())
    if not safe_name or not (safe_name.endswith(".tar.gz") or safe_name.endswith(".tgz")):
        raise ValueError("Invalid backup filename")

    file_path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Backup file not found: {safe_name}")

    os.remove(file_path)
    log(f"Deleted backup archive: {safe_name}")
    return safe_name

# ── Auto Backup, External Storage & Remote PC Configuration ─────────────────

AUTO_CONFIG_FILE = os.path.join(BACKUP_DIR, "auto_backup_config.json")

DEFAULT_CONFIG = {
    "auto_backup": {
        "enabled": False,
        "frequency": "daily",         # "hourly", "every_6h", "every_12h", "daily", "weekly"
        "time_of_day": "02:00",
        "day_of_week": "Sunday",
        "backup_type": "full",        # "full" or "db"
        "retention_count": 7,
        "last_run": None,
        "last_status": None,
        "next_run": None
    },
    "external_drive": {
        "enabled": False,
        "path": "/media/usb",         # Mount path or external directory
        "retention_count": 7,
        "last_sync": None,
        "last_status": None
    },
    "remote_pc": {
        "enabled": False,
        "host": "",
        "port": 22,
        "username": "",
        "auth_type": "password",      # "password" or "key"
        "password": "",
        "key_path": "",
        "remote_dir": "/var/backups/bahmni",
        "retention_count": 7,
        "last_sync": None,
        "last_status": None
    }
}

def calculate_next_run(auto_cfg):
    if not auto_cfg.get("enabled"):
        return None
    now = datetime.datetime.now()
    freq = auto_cfg.get("frequency", "daily")
    time_str = auto_cfg.get("time_of_day", "02:00")
    try:
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
    except Exception:
        hour, minute = 2, 0

    if freq == "hourly":
        next_dt = now.replace(minute=minute, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += datetime.timedelta(hours=1)
    elif freq == "every_6h":
        cur_hour = now.hour
        next_hour = ((cur_hour // 6) + 1) * 6
        if next_hour >= 24:
            next_dt = (now + datetime.timedelta(days=1)).replace(hour=next_hour % 24, minute=0, second=0, microsecond=0)
        else:
            next_dt = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
    elif freq == "every_12h":
        cur_hour = now.hour
        next_hour = 12 if cur_hour < 12 else 24
        if next_hour >= 24:
            next_dt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            next_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
    elif freq == "weekly":
        day_name = auto_cfg.get("day_of_week", "Sunday").capitalize()
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        target_day = days.index(day_name) if day_name in days else 6
        current_day = now.weekday()
        days_ahead = (target_day - current_day) % 7
        next_dt = (now + datetime.timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += datetime.timedelta(days=7)
    else: # daily
        next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += datetime.timedelta(days=1)

    return next_dt.strftime("%Y-%m-%d %H:%M:%S")

def load_auto_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(AUTO_CONFIG_FILE):
        try:
            with open(AUTO_CONFIG_FILE, "r") as f:
                data = json.load(f)
                for section in ["auto_backup", "external_drive", "remote_pc"]:
                    if section in data and isinstance(data[section], dict):
                        cfg[section].update(data[section])
        except Exception as e:
            log(f"Warning reading auto backup config {AUTO_CONFIG_FILE}: {e}")
    cfg["auto_backup"]["next_run"] = calculate_next_run(cfg["auto_backup"])
    return cfg

def save_auto_config(new_config):
    cfg = load_auto_config()
    for section in ["auto_backup", "external_drive", "remote_pc"]:
        if section in new_config and isinstance(new_config[section], dict):
            cfg[section].update(new_config[section])
    cfg["auto_backup"]["next_run"] = calculate_next_run(cfg["auto_backup"])
    os.makedirs(os.path.dirname(AUTO_CONFIG_FILE), exist_ok=True)
    with open(AUTO_CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    log(f"Saved auto backup configuration to {AUTO_CONFIG_FILE}")
    return cfg

def sync_to_external_drive(archive_path, ext_cfg=None):
    if ext_cfg is None:
        cfg = load_auto_config()
        ext_cfg = cfg.get("external_drive", {})
    if not ext_cfg.get("enabled"):
        return False, "External drive sync is disabled."
    
    target_path = ext_cfg.get("path", "").strip()
    if not target_path:
        return False, "External drive path not specified."
    
    filename = os.path.basename(archive_path)
    log(f"Copying backup to External Drive / USB: {target_path}...")
    
    # Try direct filesystem copy
    try:
        os.makedirs(target_path, exist_ok=True)
        dest_file = os.path.join(target_path, filename)
        shutil.copy2(archive_path, dest_file)
        
        # Enforce retention on external drive
        retention = int(ext_cfg.get("retention_count", 7))
        existing = sorted(glob.glob(os.path.join(target_path, "bahmni_*.tar.gz")), key=os.path.getmtime, reverse=True)
        if len(existing) > retention:
            for old in existing[retention:]:
                try:
                    os.remove(old)
                    log(f"Pruned external drive backup: {os.path.basename(old)}")
                except Exception:
                    pass
        
        msg = f"Backup successfully copied to external drive: {dest_file}"
        log(msg)
        return True, msg
    except Exception as e_direct:
        log(f"Direct external copy failed ({e_direct}). Attempting via Docker host mount...")
        try:
            retention = int(ext_cfg.get("retention_count", 7))
            cmd = (
                f'docker run --rm -v "{target_path}:/dest" -v "{BACKUP_DIR}:/src" alpine sh -c '
                f'"cp /src/{filename} /dest/ && '
                f'(ls -t /dest/bahmni_*.tar.gz 2>/dev/null | tail -n +{retention + 1} | xargs -r rm -f)"'
            )
            run_cmd(cmd)
            msg = f"Backup successfully copied to external drive via host mount: {target_path}/{filename}"
            log(msg)
            return True, msg
        except Exception as e_docker:
            err = f"Failed copying to external drive: {e_docker}"
            log(err)
            return False, err

def test_external_path(target_path):
    target_path = (target_path or "").strip()
    if not target_path:
        return {"success": False, "error": "External drive path cannot be empty."}
    
    # Try direct write
    try:
        os.makedirs(target_path, exist_ok=True)
        test_file = os.path.join(target_path, f".bahmni_test_{int(time.time())}.tmp")
        with open(test_file, "w") as f:
            f.write("bahmni_write_test")
        os.remove(test_file)
        
        try:
            usage = shutil.disk_usage(target_path)
            free_gb = round(usage.free / (1024**3), 2)
            total_gb = round(usage.total / (1024**3), 2)
            space_info = f"Free: {free_gb} GB / Total: {total_gb} GB"
        except Exception:
            space_info = "Ready"
            
        return {
            "success": True,
            "message": f"External drive verified. Path is writable. ({space_info})"
        }
    except Exception as e_direct:
        # Fallback via Docker mount
        try:
            test_cmd = (
                f'docker run --rm -v "{target_path}:/dest" alpine sh -c '
                f'"echo bahmni_test > /dest/.bahmni_test.tmp && rm /dest/.bahmni_test.tmp && df -h /dest | tail -n 1"'
            )
            out = run_cmd(test_cmd)
            parts = out.split()
            free_space = parts[3] if len(parts) >= 4 else "Available"
            return {
                "success": True,
                "message": f"External drive verified via host mount. Free space: {free_space}"
            }
        except Exception as e_docker:
            return {
                "success": False,
                "error": f"Cannot write to path '{target_path}': {str(e_docker) or str(e_direct)}"
            }

def test_remote_connection(remote_cfg):
    host = remote_cfg.get("host", "").strip()
    port = int(remote_cfg.get("port", 22) or 22)
    user = remote_cfg.get("username", "").strip()
    auth_type = remote_cfg.get("auth_type", "password")
    password = remote_cfg.get("password", "")
    key_path = remote_cfg.get("key_path", "").strip()
    remote_dir = remote_cfg.get("remote_dir", "/var/backups/bahmni").strip()
    
    if not host or not user:
        return {"success": False, "error": "Remote Host and Username are required."}
    
    ssh_opts = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8"
    
    if auth_type == "key" and key_path:
        ssh_cmd = f"ssh -i '{key_path}' {ssh_opts} -p {port} {user}@{host}"
    else:
        escaped_pw = password.replace('"', '\\"').replace("'", "'\\''")
        ssh_cmd = f"sshpass -p '{escaped_pw}' ssh {ssh_opts} -p {port} {user}@{host}"
    
    remote_check = f"mkdir -p '{remote_dir}' && df -h '{remote_dir}' | tail -n 1"
    full_cmd = f"{ssh_cmd} \"{remote_check}\""
    
    try:
        res = subprocess.run(full_cmd, shell=True, text=True, capture_output=True, timeout=12)
        if res.returncode == 0:
            out = res.stdout.strip()
            parts = out.split()
            free_space = parts[3] if len(parts) >= 4 else "Available"
            return {
                "success": True,
                "message": f"Successfully connected to remote PC ({user}@{host}:{port}). Folder '{remote_dir}' is writable. Free space: {free_space}"
            }
        else:
            err = res.stderr.strip() or f"SSH exited with code {res.returncode}"
            return {"success": False, "error": f"Remote connection failed: {err}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Connection timed out trying to reach {host}:{port}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def sync_to_remote_pc(archive_path, remote_cfg=None):
    if remote_cfg is None:
        cfg = load_auto_config()
        remote_cfg = cfg.get("remote_pc", {})
    if not remote_cfg.get("enabled"):
        return False, "Remote PC backup is disabled."
    
    host = remote_cfg.get("host", "").strip()
    port = int(remote_cfg.get("port", 22) or 22)
    user = remote_cfg.get("username", "").strip()
    auth_type = remote_cfg.get("auth_type", "password")
    password = remote_cfg.get("password", "")
    key_path = remote_cfg.get("key_path", "").strip()
    remote_dir = remote_cfg.get("remote_dir", "/var/backups/bahmni").strip()
    retention = int(remote_cfg.get("retention_count", 7))
    filename = os.path.basename(archive_path)
    
    if not host or not user:
        return False, "Remote Host and Username are required."
    
    log(f"Transferring {filename} to Remote PC ({user}@{host}:{remote_dir})...")
    ssh_opts = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15"
    
    if auth_type == "key" and key_path:
        scp_cmd = f"scp -i '{key_path}' {ssh_opts} -P {port} '{archive_path}' '{user}@{host}:{remote_dir}/'"
        prune_cmd = f"ssh -i '{key_path}' {ssh_opts} -p {port} {user}@{host} \"ls -t '{remote_dir}'/bahmni_*.tar.gz 2>/dev/null | tail -n +{retention + 1} | xargs -r rm -f\""
    else:
        escaped_pw = password.replace('"', '\\"').replace("'", "'\\''")
        scp_cmd = f"sshpass -p '{escaped_pw}' scp {ssh_opts} -P {port} '{archive_path}' '{user}@{host}:{remote_dir}/'"
        prune_cmd = f"sshpass -p '{escaped_pw}' ssh {ssh_opts} -p {port} {user}@{host} \"ls -t '{remote_dir}'/bahmni_*.tar.gz 2>/dev/null | tail -n +{retention + 1} | xargs -r rm -f\""
    
    try:
        run_cmd(scp_cmd)
        log(f"Successfully transferred {filename} to remote PC {host}:{remote_dir}")
        try:
            run_cmd(prune_cmd, check=False)
        except Exception:
            pass
        return True, f"Transferred to {host}:{remote_dir}/{filename}"
    except Exception as e:
        err = f"Failed to transfer backup to remote PC ({host}): {e}"
        log(err)
        return False, err

def post_backup_sync(archive_path):
    cfg = load_auto_config()
    updated = False
    
    # 1. External Drive / USB
    ext_cfg = cfg.get("external_drive", {})
    if ext_cfg.get("enabled"):
        log(f"[SYNC] Triggering copy of backup to External Drive / USB...")
        ok, msg = sync_to_external_drive(archive_path, ext_cfg)
        cfg["external_drive"]["last_sync"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cfg["external_drive"]["last_status"] = "success" if ok else f"error: {msg}"
        updated = True
        
    # 2. Remote PC
    remote_cfg = cfg.get("remote_pc", {})
    if remote_cfg.get("enabled"):
        log(f"[SYNC] Triggering transfer of backup to Remote PC ({remote_cfg.get('host')})...")
        ok, msg = sync_to_remote_pc(archive_path, remote_cfg)
        cfg["remote_pc"]["last_sync"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cfg["remote_pc"]["last_status"] = "success" if ok else f"error: {msg}"
        updated = True
        
    if updated:
        save_auto_config(cfg)

def start_scheduler_loop():
    log("Auto-Backup background scheduler started.")
    while True:
        try:
            time.sleep(30)
            cfg = load_auto_config()
            auto_cfg = cfg.get("auto_backup", {})
            if not auto_cfg.get("enabled"):
                continue

            now = datetime.datetime.now()
            freq = auto_cfg.get("frequency", "daily")
            time_str = auto_cfg.get("time_of_day", "02:00")
            day_str = auto_cfg.get("day_of_week", "Sunday").capitalize()
            last_run = auto_cfg.get("last_run")
            
            should_run = False
            today_str = now.strftime("%Y-%m-%d")
            last_run_date = last_run[:10] if last_run else None
            
            try:
                parts = time_str.split(":")
                hour, minute = int(parts[0]), int(parts[1])
            except Exception:
                hour, minute = 2, 0

            if freq == "daily":
                if now.hour == hour and now.minute == minute and last_run_date != today_str:
                    should_run = True
            elif freq == "weekly":
                days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                if days[now.weekday()] == day_str and now.hour == hour and now.minute == minute and last_run_date != today_str:
                    should_run = True
            elif freq == "every_12h":
                if not last_run:
                    should_run = True
                else:
                    try:
                        last_dt = datetime.datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")
                        if now - last_dt >= datetime.timedelta(hours=12):
                            should_run = True
                    except Exception:
                        should_run = True
            elif freq == "every_6h":
                if not last_run:
                    should_run = True
                else:
                    try:
                        last_dt = datetime.datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")
                        if now - last_dt >= datetime.timedelta(hours=6):
                            should_run = True
                    except Exception:
                        should_run = True
            elif freq == "hourly":
                if not last_run:
                    should_run = True
                else:
                    try:
                        last_dt = datetime.datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")
                        if now - last_dt >= datetime.timedelta(hours=1):
                            should_run = True
                    except Exception:
                        should_run = True

            if should_run:
                with op_lock:
                    is_busy = (current_op["status"] == "running")
                if not is_busy:
                    b_type = auto_cfg.get("backup_type", "full")
                    log(f"[SCHEDULER] Triggering scheduled {b_type} backup at {now.strftime('%Y-%m-%d %H:%M:%S')}...")
                    auto_cfg["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    auto_cfg["last_status"] = "in_progress"
                    save_auto_config(cfg)
                    
                    target_func = execute_full_backup if b_type == "full" else execute_db_backup
                    ok, msg = run_async("auto_backup", target_func)
                    
                    cfg = load_auto_config()
                    cfg["auto_backup"]["last_status"] = "completed" if ok else f"error: {msg}"
                    save_auto_config(cfg)
                else:
                    log("[SCHEDULER] Scheduled backup deferred: Another operation is currently in progress.")
        except Exception as e:
            log(f"[SCHEDULER] Error in scheduler loop: {e}")

def run_async(op_type, func, *args):
    with op_lock:
        if current_op["status"] == "running":
            return False, "An operation is already in progress."
        current_op["status"] = "running"
        current_op["type"] = op_type
        current_op["message"] = f"Starting {op_type}..."
        current_op["started_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_op["completed_at"] = None
        current_op["progress"] = 5
        current_op["logs"] = []

    def worker():
        try:
            func(*args)
            with op_lock:
                current_op["status"] = "completed"
                current_op["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_op["progress"] = 100
        except Exception as e:
            with op_lock:
                current_op["status"] = "error"
                current_op["message"] = f"Failed: {str(e)}"
                current_op["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log(f"FATAL ERROR in {op_type}: {e}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return True, "Operation started successfully."

# ── Branding Customization Service ───────────────────────────────────────────

def write_file_safe(file_path, content, is_binary=False):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        mode = "wb" if is_binary else "w"
        kwargs = {} if is_binary else {"encoding": "utf-8"}
        with open(file_path, mode, **kwargs) as f:
            f.write(content)
        log(f"Wrote file: {file_path}")
        return True
    except Exception as e:
        log(f"Error writing {file_path}: {e}")
        return False

def sync_file_to_bahmni_web(local_source, container_dest):
    try:
        bweb = get_container("bahmni-web")
        dest_dir = os.path.dirname(container_dest).replace("\\", "/")
        subprocess.run(f'docker exec {bweb} mkdir -p "{dest_dir}"', shell=True, capture_output=True)
        res = subprocess.run(f'docker cp "{local_source}" "{bweb}:{container_dest}"', shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            log(f"Synced {os.path.basename(local_source)} -> {bweb}:{container_dest}")
            return True
        elif "read-only" not in (res.stderr or "").lower():
            log(f"Warning syncing to container {bweb}:{container_dest}: {res.stderr}")
    except Exception as e:
        log(f"Exception syncing file to container: {e}")
    return False

def decode_base64_data(data_str):
    if not data_str:
        return None
    try:
        if "," in data_str:
            data_str = data_str.split(",", 1)[1]
        return base64.b64decode(data_str.strip())
    except Exception as e:
        log(f"Error decoding base64 data: {e}")
        return None

def load_branding_config():
    branding_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "branding.json")
    whitelabel_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "home", "whiteLabel.json")
    reg_i18n_file = os.path.join(CONFIG_DIR, "openmrs", "i18n", "registration", "locale_en.json")
    
    data = {
        "facilityName": "Boru Meda General Hospital",
        "browserTitle": "BMH bahmni",
        "tagline": "General Hospital EMR System",
        "welcomeMessage": "WELCOME TO BORU MEDA GENERAL HOSPITAL EMR System",
        "address": "Boru Meda, Dessie, Amhara, Ethiopia",
        "phone": "+251 33 111 2233",
        "email": "info@borumedahospital.gov.et",
        "website": "www.borumedahospital.gov.et",
        "mainLogoUrl": "/bahmni/images/bahmniLogo.png",
        "loginLogoUrl": "/bahmni_config/openmrs/apps/home/logo.png",
        "printLogoUrl": "/bahmni_config/openmrs/apps/registration/registrationCardLayout/images/bahmni-icon.png",
        "faviconUrl": "/bahmni/favicon.ico",
        "footerLogoUrl": "/bahmni/images/cdhiLogo.png",
        "footerText": "powered by CDHi",
        "footerLink": "https://cdhi.uog.edu.et/"
    }

    if os.path.isfile(branding_file):
        try:
            with open(branding_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                data.update(saved)
        except Exception as e:
            log(f"Warning reading branding.json: {e}")
    else:
        if os.path.isfile(whitelabel_file):
            try:
                with open(whitelabel_file, "r", encoding="utf-8") as f:
                    wl = json.load(f)
                    header = wl.get("homePage", {}).get("header_text", "")
                    clean_header = re.sub(r'<[^>]+>', ' ', header).strip()
                    if clean_header:
                        data["welcomeMessage"] = clean_header
                        m = re.search(r'WELCOME\s+TO\s+(.+)', clean_header, re.IGNORECASE)
                        if m:
                            data["facilityName"] = m.group(1).replace("EMR System", "").strip()
                    title = wl.get("homePage", {}).get("title_text", "")
                    if title and title.strip():
                        data["tagline"] = title.strip()
            except Exception:
                pass
        if os.path.isfile(reg_i18n_file):
            try:
                with open(reg_i18n_file, "r", encoding="utf-8") as f:
                    loc = json.load(f)
                    if loc.get("REGISTRATION_INSTITUTE_NAME_TEXT_KEY"):
                        data["facilityName"] = loc["REGISTRATION_INSTITUTE_NAME_TEXT_KEY"]
                    if loc.get("REGISTRATION_INSTITUTE_ADDRESS"):
                        data["address"] = loc["REGISTRATION_INSTITUTE_ADDRESS"]
            except Exception:
                pass

    ts = int(time.time())
    data["mainLogoUrlWithCache"] = f"{data['mainLogoUrl']}?t={ts}"
    data["loginLogoUrlWithCache"] = f"{data['loginLogoUrl']}?t={ts}"
    data["printLogoUrlWithCache"] = f"{data['printLogoUrl']}?t={ts}"
    data["faviconUrlWithCache"] = f"{data['faviconUrl']}?t={ts}"
    data["footerLogoUrlWithCache"] = f"{data.get('footerLogoUrl', '/bahmni/images/cdhiLogo.png')}?t={ts}"
    return data

def save_branding_config(payload):
    facility_name = (payload.get("facilityName") or "Boru Meda General Hospital").strip()
    browser_title = (payload.get("browserTitle") or payload.get("facilityName") or "BMH bahmni").strip()
    tagline = (payload.get("tagline") or "").strip()
    welcome_message = (payload.get("welcomeMessage") or f"WELCOME TO {facility_name.upper()} EMR System").strip()
    address = (payload.get("address") or "").strip()
    phone = (payload.get("phone") or "").strip()
    email = (payload.get("email") or "").strip()
    website = (payload.get("website") or "").strip()
    footer_text = (payload.get("footerText") or "powered by CDHi").strip()
    footer_link = (payload.get("footerLink") or "https://cdhi.uog.edu.et/").strip()
    apply_all = bool(payload.get("applyMainLogoToAll", False))

    log(f"Saving branding: facility='{facility_name}', tagline='{tagline}', apply_all={apply_all}")

    main_b64 = payload.get("mainLogoBase64")
    login_b64 = payload.get("loginLogoBase64")
    print_b64 = payload.get("printLogoBase64")
    fav_b64 = payload.get("faviconBase64")

    if apply_all and main_b64:
        if not login_b64:
            login_b64 = main_b64
        if not print_b64:
            print_b64 = main_b64

    # Save Main Logo
    if main_b64:
        main_bytes = decode_base64_data(main_b64)
        if main_bytes:
            for fname in ("bahmniLogo.png", "bahmniLogoFull.png", "bahmniLogo.jpg"):
                local_f = os.path.join(APP_DIR, "images", fname)
                write_file_safe(local_f, main_bytes, is_binary=True)
                sync_file_to_bahmni_web(local_f, f"/usr/local/apache2/htdocs/bahmni/images/{fname}")

    # Save Login Logo
    if login_b64:
        login_bytes = decode_base64_data(login_b64)
        if login_bytes:
            local_f = os.path.join(CONFIG_DIR, "openmrs", "apps", "home", "logo.png")
            write_file_safe(local_f, login_bytes, is_binary=True)
            sync_file_to_bahmni_web(local_f, "/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/home/logo.png")

    # Save Print Logo
    if print_b64:
        print_bytes = decode_base64_data(print_b64)
        if print_bytes:
            local_f = os.path.join(CONFIG_DIR, "openmrs", "apps", "registration", "registrationCardLayout", "images", "bahmni-icon.png")
            write_file_safe(local_f, print_bytes, is_binary=True)
            sync_file_to_bahmni_web(local_f, "/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/registration/registrationCardLayout/images/bahmni-icon.png")

    # Save Favicon
    if fav_b64:
        fav_bytes = decode_base64_data(fav_b64)
        if fav_bytes:
            local_f = os.path.join(APP_DIR, "favicon.ico")
            write_file_safe(local_f, fav_bytes, is_binary=True)
            sync_file_to_bahmni_web(local_f, "/usr/local/apache2/htdocs/bahmni/favicon.ico")

    # Save Footer Logo
    footer_b64 = payload.get("footerLogoBase64")
    if footer_b64:
        footer_bytes = decode_base64_data(footer_b64)
        if footer_bytes:
            for fname in ("cdhiLogo.png", "cdhilogo.png", "cdhiLogo.png.png"):
                local_f = os.path.join(APP_DIR, "images", fname)
                write_file_safe(local_f, footer_bytes, is_binary=True)
                sync_file_to_bahmni_web(local_f, f"/usr/local/apache2/htdocs/bahmni/images/{fname}")

    # Update Browser Tab Title (<title> tags) in HTML files
    for app_name in ("home", "registration", "clinical", "admin", "reports", "orders", "adt", "bedmanagement", "document-upload"):
        idx_f = os.path.join(APP_DIR, app_name, "index.html")
        if os.path.isfile(idx_f):
            try:
                with open(idx_f, "r", encoding="utf-8") as f:
                    idx_html = f.read()
                new_idx_html = re.sub(r'<title>.*?</title>', f'<title>{browser_title}</title>', idx_html, flags=re.IGNORECASE)
                if new_idx_html != idx_html:
                    write_file_safe(idx_f, new_idx_html)
                    sync_file_to_bahmni_web(idx_f, f"/usr/local/apache2/htdocs/bahmni/{app_name}/index.html")
            except Exception as e:
                log(f"Warning updating title in {idx_f}: {e}")

    # Update whiteLabel.json
    whitelabel_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "home", "whiteLabel.json")
    if os.path.isfile(whitelabel_file):
        try:
            with open(whitelabel_file, "r", encoding="utf-8") as f:
                wl = json.load(f)
            wl.setdefault("homePage", {})
            wl["homePage"]["header_text"] = f"<b>{welcome_message}</b>"
            wl["homePage"]["title_text"] = tagline
            wl["homePage"]["browserTitle"] = browser_title
            wl["homePage"]["logo"] = "/bahmni_config/openmrs/apps/home/logo.png"
            wl.setdefault("loginPage", {})
            wl["loginPage"]["logo"] = "/bahmni_config/openmrs/apps/home/logo.png"
            wl["loginPage"]["footerText"] = footer_text
            wl["loginPage"]["footerLink"] = footer_link
            wl["loginPage"]["footerLogo"] = "/bahmni/images/cdhiLogo.png"
            write_file_safe(whitelabel_file, json.dumps(wl, indent=2))
            sync_file_to_bahmni_web(whitelabel_file, "/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/home/whiteLabel.json")
        except Exception as e:
            log(f"Error updating whiteLabel.json: {e}")

    # Update locale_en.json
    reg_i18n_file = os.path.join(CONFIG_DIR, "openmrs", "i18n", "registration", "locale_en.json")
    if os.path.isfile(reg_i18n_file):
        try:
            with open(reg_i18n_file, "r", encoding="utf-8") as f:
                loc = json.load(f)
            loc["REGISTRATION_INSTITUTE_NAME_TEXT_KEY"] = facility_name
            if address:
                loc["REGISTRATION_INSTITUTE_ADDRESS"] = address
            write_file_safe(reg_i18n_file, json.dumps(loc, indent=2))
            sync_file_to_bahmni_web(reg_i18n_file, "/usr/local/apache2/htdocs/bahmni_config/openmrs/i18n/registration/locale_en.json")
        except Exception as e:
            log(f"Error updating registration locale_en.json: {e}")

    # Update clinical dashboard.json & visit.json
    for json_name in ("dashboard.json", "visit.json"):
        cfg_path = os.path.join(CONFIG_DIR, "openmrs", "apps", "clinical", json_name)
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg_obj = json.load(f)
                def update_printing_titles(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k == "printing" and isinstance(v, dict) and "title" in v:
                                v["title"] = facility_name.upper()
                            else:
                                update_printing_titles(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            update_printing_titles(item)
                update_printing_titles(cfg_obj)
                write_file_safe(cfg_path, json.dumps(cfg_obj, indent=4))
                sync_file_to_bahmni_web(cfg_path, f"/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/clinical/{json_name}")
            except Exception as e:
                log(f"Error updating {json_name} print titles: {e}")

    # Update OpenMRS MySQL database
    try:
        omrs = get_container("openmrsdb")
        sql_name = facility_name.replace("'", "''").replace("\\", "\\\\")
        header_lines = [f"<b>{sql_name}</b>"]
        if address:
            header_lines.append(address.replace("'", "''").replace("\\", "\\\\"))
        phone_esc = phone.replace("'", "''")
        email_esc = email.replace("'", "''")
        web_esc = website.replace("'", "''")
        contacts = []
        if phone:
            contacts.append(f"Tel: {phone_esc}")
        if email:
            contacts.append(f"Email: {email_esc}")
        if website:
            contacts.append(f"Web: {web_esc}")
        if contacts:
            header_lines.append(" | ".join(contacts))
        print_header_html = "<br/>".join(header_lines)

        sql_stmts = (
            f"UPDATE location SET name = '{sql_name}' WHERE location_id IN (2, 253); "
            f"UPDATE global_property SET property_value = '{phone_esc}' WHERE property = 'clinic.helpDeskNumber'; "
            f"SET @clob_uuid = UUID(); "
            f"INSERT INTO clob_datatype_storage (uuid, value) VALUES (@clob_uuid, '{print_header_html}'); "
            f"DELETE FROM location_attribute WHERE location_id = 2 AND attribute_type_id = 1; "
            f"INSERT INTO location_attribute (location_id, attribute_type_id, value_reference, uuid, creator, date_created) "
            f"VALUES (2, 1, @clob_uuid, UUID(), 1, NOW()); "
            f"DELETE FROM location_attribute WHERE location_id = 253 AND attribute_type_id = 1; "
            f"INSERT INTO location_attribute (location_id, attribute_type_id, value_reference, uuid, creator, date_created) "
            f"SELECT 253, 1, @clob_uuid, UUID(), 1, NOW() FROM location WHERE location_id = 253; "
            f"UPDATE global_property SET property_value = 'SELECT lat.name, \\n       COALESCE(cds.value, la.value_reference) as value\\nFROM location_attribute_type lat\\nINNER JOIN (\\n    SELECT attribute_type_id, \\n           MAX(location_attribute_id) AS max_location_attribute_id\\n    FROM location_attribute\\n    WHERE location_id = 2\\n    GROUP BY attribute_type_id\\n) latest_ids ON lat.location_attribute_type_id = latest_ids.attribute_type_id\\nINNER JOIN location_attribute la ON la.location_attribute_id = latest_ids.max_location_attribute_id\\nLEFT JOIN clob_datatype_storage cds ON la.value_reference = cds.uuid\\nORDER BY lat.location_attribute_type_id;' WHERE property = 'emrapi.sqlSearch.facilityInfo'; "
        )
        run_cmd(f'docker exec -i {omrs} mysql -uroot -p"{MYSQL_PASS}" openmrs -e "{sql_stmts}"', check=False)
        log("Successfully updated OpenMRS locations, Print Header clob attribute, and clinic helpdesk number.")
    except Exception as e:
        log(f"Warning updating OpenMRS database: {e}")

    # Save branding.json
    branding_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "branding.json")
    saved_meta = {
        "facilityName": facility_name,
        "browserTitle": browser_title,
        "tagline": tagline,
        "welcomeMessage": welcome_message,
        "address": address,
        "phone": phone,
        "email": email,
        "website": website,
        "mainLogoUrl": "/bahmni/images/bahmniLogo.png",
        "loginLogoUrl": "/bahmni_config/openmrs/apps/home/logo.png",
        "printLogoUrl": "/bahmni_config/openmrs/apps/registration/registrationCardLayout/images/bahmni-icon.png",
        "faviconUrl": "/bahmni/favicon.ico",
        "footerLogoUrl": "/bahmni/images/cdhiLogo.png",
        "footerText": footer_text,
        "footerLink": footer_link,
        "updatedAt": datetime.datetime.now().isoformat()
    }
    write_file_safe(branding_file, json.dumps(saved_meta, indent=2))
    sync_file_to_bahmni_web(branding_file, "/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/branding.json")

    return load_branding_config()

# ── Payment & Odoo Billing Configuration ─────────────────────────────────────

def check_odoo_status():
    """
    Checks whether Odoo ERP billing service is active and responding.
    """
    import urllib.request
    urls_to_try = [
        "http://127.0.0.1:8069/web/login",
        "http://odoo:8069/web/login",
        "http://172.18.0.1:8069/web/login"
    ]
    for url in urls_to_try:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BahmniPaymentCheck/1.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status in (200, 301, 302, 303):
                    return {
                        "online": True,
                        "status_code": resp.status,
                        "message": "Odoo billing service is online and responding",
                        "checked_url": url,
                        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
        except Exception:
            continue

    # Fallback docker container check
    try:
        res = subprocess.run(["docker", "ps", "--filter", "name=odoo", "--format", "{{.Status}}"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and "Up" in res.stdout:
            return {
                "online": True,
                "status_code": 200,
                "message": f"Odoo container is running ({res.stdout.strip()})",
                "checked_url": "docker:odoo",
                "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    except Exception:
        pass

    return {
        "online": False,
        "status_code": 0,
        "message": "Odoo billing service is offline, stopped, or unreachable",
        "checked_url": urls_to_try[0],
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

def load_payment_config():
    reg_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "registration", "app.json")
    orders_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "orders", "app.json")
    clinical_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "clinical", "app.json")

    config = {
        "odoo": check_odoo_status(),
        "registration": {
            "disable_billing": False,
            "payment_window": 30
        },
        "orders": {
            "disable_checking": False
        },
        "clinical": {
            "disable_checking": False
        }
    }

    if os.path.isfile(reg_file):
        try:
            with open(reg_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                p_cfg = d.get("config", {}).get("paymentConfig", {}) or d.get("paymentConfig", {})
                config["registration"]["disable_billing"] = bool(p_cfg.get("disable billing", False))
                config["registration"]["payment_window"] = int(p_cfg.get("payment window", 30))
        except Exception as e:
            log(f"Warning reading registration app.json: {e}")

    if os.path.isfile(orders_file):
        try:
            with open(orders_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                p_cfg = d.get("config", {}).get("paymentConfig", {}) or d.get("paymentConfig", {})
                config["orders"]["disable_checking"] = bool(p_cfg.get("disable checking", False))
        except Exception as e:
            log(f"Warning reading orders app.json: {e}")

    if os.path.isfile(clinical_file):
        try:
            with open(clinical_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                p_cfg = d.get("config", {}).get("paymentConfig", {}) or d.get("paymentConfig", {})
                config["clinical"]["disable_checking"] = bool(p_cfg.get("disable checking", False))
        except Exception as e:
            log(f"Warning reading clinical app.json: {e}")

    is_bypass = config["orders"]["disable_checking"] and config["registration"]["disable_billing"]
    config["mode"] = "emergency_bypass" if is_bypass else "enforce_odoo"
    return config

def save_payment_config(payload):
    reg_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "registration", "app.json")
    orders_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "orders", "app.json")
    clinical_file = os.path.join(CONFIG_DIR, "openmrs", "apps", "clinical", "app.json")

    reg_payload = payload.get("registration", {})
    orders_payload = payload.get("orders", {})
    clinical_payload = payload.get("clinical", {})

    log(f"Saving payment config: registration={reg_payload}, orders={orders_payload}, clinical={clinical_payload}")

    # 1. Update Registration app.json
    if os.path.isfile(reg_file):
        try:
            with open(reg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "config" not in data or not isinstance(data["config"], dict):
                data["config"] = {}
            if "paymentConfig" not in data["config"] or not isinstance(data["config"]["paymentConfig"], dict):
                data["config"]["paymentConfig"] = {}
            
            if "disable_billing" in reg_payload:
                data["config"]["paymentConfig"]["disable billing"] = bool(reg_payload["disable_billing"])
            if "payment_window" in reg_payload:
                data["config"]["paymentConfig"]["payment window"] = int(reg_payload["payment_window"])
            
            write_file_safe(reg_file, json.dumps(data, indent=4))
            sync_file_to_bahmni_web(reg_file, "/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/registration/app.json")
            log("Updated registration paymentConfig successfully.")
        except Exception as e:
            log(f"Error updating registration app.json: {e}")
            raise

    # 2. Update Orders app.json
    if os.path.isfile(orders_file):
        try:
            with open(orders_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "config" not in data or not isinstance(data["config"], dict):
                data["config"] = {}
            if "paymentConfig" not in data["config"] or not isinstance(data["config"]["paymentConfig"], dict):
                data["config"]["paymentConfig"] = {}
            
            if "disable_checking" in orders_payload:
                data["config"]["paymentConfig"]["disable checking"] = bool(orders_payload["disable_checking"])
            
            write_file_safe(orders_file, json.dumps(data, indent=4))
            sync_file_to_bahmni_web(orders_file, "/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/orders/app.json")
            log("Updated orders paymentConfig successfully.")
        except Exception as e:
            log(f"Error updating orders app.json: {e}")
            raise

    # 3. Update Clinical app.json
    if os.path.isfile(clinical_file):
        try:
            with open(clinical_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "config" not in data or not isinstance(data["config"], dict):
                data["config"] = {}
            if "paymentConfig" not in data["config"] or not isinstance(data["config"]["paymentConfig"], dict):
                data["config"]["paymentConfig"] = {}
            
            if "disable_checking" in clinical_payload:
                data["config"]["paymentConfig"]["disable checking"] = bool(clinical_payload["disable_checking"])
            elif "disable_checking" in orders_payload:
                data["config"]["paymentConfig"]["disable checking"] = bool(orders_payload["disable_checking"])
            
            write_file_safe(clinical_file, json.dumps(data, indent=4))
            sync_file_to_bahmni_web(clinical_file, "/usr/local/apache2/htdocs/bahmni_config/openmrs/apps/clinical/app.json")
            log("Updated clinical paymentConfig successfully.")
        except Exception as e:
            log(f"Error updating clinical app.json: {e}")
            raise

    return load_payment_config()

# ── HTTP Server Request Handler ──────────────────────────────────────────────

class BackupAPIHandler(BaseHTTPRequestHandler):
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors()
    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_GET(self, head_only=False):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        # Handle path prefix if mounted at /backup-api or /api
        path = path.replace("/backup-api", "")
        if not path:
            path = "/"

        query_params = parse_qs(parsed.query)
        download_file = None
        if path.startswith("/download/") or path.startswith("/api/download/"):
            parts = path.split("/download/")
            if len(parts) > 1 and parts[1]:
                download_file = parts[1]
        elif path in ("/download", "/api/download") and "file" in query_params:
            download_file = query_params["file"][0]

        if download_file:
            self._serve_download(download_file, head_only=head_only)
            return

        if path in ("/api/backups", "/backups"):
            data = {"backups": list_backups(), "status": current_op}
            self._send_json(200, data)
        elif path in ("/api/status", "/status"):
            self._send_json(200, current_op)
        elif path in ("/api/backup/config", "/backup/config", "/api/config", "/config"):
            self._send_json(200, load_auto_config())
        elif path in ("/api/branding", "/branding"):
            self._send_json(200, load_branding_config())
        elif path in ("/api/payment-config", "/payment-config"):
            self._send_json(200, load_payment_config())
        else:
            self._send_json(404, {"error": "Endpoint not found", "path": path})

    def _serve_download(self, filename, head_only=False):
        safe_name = os.path.basename(filename.strip())
        if not safe_name or not safe_name.endswith(".tar.gz"):
            self._send_json(400, {"error": "Invalid backup archive filename"})
            return

        file_path = os.path.join(BACKUP_DIR, safe_name)
        if not os.path.isfile(file_path):
            self._send_json(404, {"error": f"Backup file not found: {safe_name}"})
            return

        try:
            file_size = os.path.getsize(file_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
            self.send_header("Content-Length", str(file_size))
            self._send_cors()
            self.end_headers()

            if head_only:
                return

            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"Download error for {safe_name}: {e}")

    def _handle_upload(self, query_params):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json(400, {"success": False, "error": "Content-Length header required for upload"})
            return

        content_type = self.headers.get("Content-Type", "")
        raw_name = query_params.get("filename", [""])[0] or self.headers.get("X-File-Name", "")
        do_restore = query_params.get("restore", ["false"])[0].lower() in ("true", "1", "yes") or \
                     self.headers.get("X-Restore-Now", "").lower() in ("true", "1", "yes")

        os.makedirs(BACKUP_DIR, exist_ok=True)

        if "multipart/form-data" in content_type:
            boundary = None
            for p in content_type.split(";"):
                p = p.strip()
                if p.startswith("boundary="):
                    boundary = p.split("=", 1)[1].strip('"').encode("latin1")
                    break
            if not boundary:
                self._send_json(400, {"success": False, "error": "Invalid multipart boundary"})
                return

            body_bytes = self.rfile.read(content_length)
            parts = body_bytes.split(b"--" + boundary)
            file_found = False
            for part in parts:
                if b'filename="' in part:
                    if not raw_name:
                        match = re.search(rb'filename="([^"]+)"', part)
                        if match:
                            raw_name = match.group(1).decode("utf-8", errors="replace")
                    header_end = part.find(b"\r\n\r\n")
                    if header_end != -1:
                        data = part[header_end + 4:]
                        if data.endswith(b"\r\n"):
                            data = data[:-2]
                        safe_name = os.path.basename(raw_name.strip() if raw_name else f"uploaded_backup_{int(time.time())}.tar.gz")
                        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', safe_name)
                        if not (safe_name.endswith(".tar.gz") or safe_name.endswith(".tgz")):
                            safe_name += ".tar.gz"
                        dest_path = os.path.join(BACKUP_DIR, safe_name)
                        with open(dest_path, "wb") as f:
                            f.write(data)
                        file_found = True
                        break
            if not file_found:
                self._send_json(400, {"success": False, "error": "No file content found in multipart body"})
                return
        else:
            safe_name = os.path.basename(raw_name.strip() if raw_name else f"uploaded_backup_{int(time.time())}.tar.gz")
            safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', safe_name)
            if not (safe_name.endswith(".tar.gz") or safe_name.endswith(".tgz")):
                safe_name += ".tar.gz"
            dest_path = os.path.join(BACKUP_DIR, safe_name)
            remaining = content_length
            with open(dest_path, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)

        # Validate archive integrity
        try:
            with tarfile.open(dest_path, "r:*") as t:
                members = t.getnames()
                if not members:
                    raise ValueError("Archive is empty")
        except Exception as e:
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            self._send_json(400, {"success": False, "error": f"Uploaded file is not a valid tar/gzip archive: {e}"})
            return

        size_mb = round(os.path.getsize(dest_path) / (1024 * 1024), 2)
        log(f"Received uploaded backup: {safe_name} ({size_mb} MB)")

        if do_restore:
            ok, msg = run_async("restore", execute_restore, safe_name)
            if not ok:
                self._send_json(409, {"success": False, "error": msg, "filename": safe_name})
                return
            self._send_json(200, {
                "success": True,
                "message": f"Archive uploaded successfully ({size_mb} MB) and restore started.",
                "filename": safe_name,
                "restoring": True
            })
        else:
            self._send_json(200, {
                "success": True,
                "message": f"Backup archive '{safe_name}' ({size_mb} MB) uploaded successfully.",
                "filename": safe_name,
                "restoring": False
            })

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/").replace("/backup-api", "")
        query_params = parse_qs(parsed.query)

        if path in ("/api/upload", "/upload"):
            self._handle_upload(query_params)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        payload = {}
        if body:
            try:
                payload = json.loads(body)
            except Exception:
                pass

        if path in ("/api/backup/full", "/backup/full"):
            ok, msg = run_async("full_backup", execute_full_backup)
            status_code = 200 if ok else 409
            self._send_json(status_code, {"success": ok, "message": msg})

        elif path in ("/api/backup/db", "/backup/db"):
            ok, msg = run_async("db_backup", execute_db_backup)
            status_code = 200 if ok else 409
            self._send_json(status_code, {"success": ok, "message": msg})

        elif path in ("/api/restore", "/restore"):
            archive_name = payload.get("archive")
            if not archive_name:
                self._send_json(400, {"success": False, "error": "Missing 'archive' in payload"})
                return
            ok, msg = run_async("restore", execute_restore, archive_name)
            status_code = 200 if ok else 409
            self._send_json(status_code, {"success": ok, "message": msg})

        elif path in ("/api/backup/delete", "/backup/delete", "/api/delete", "/delete"):
            archive_name = payload.get("archive") or query_params.get("archive", [""])[0]
            if not archive_name:
                self._send_json(400, {"success": False, "error": "Missing 'archive' in payload"})
                return
            try:
                deleted = delete_backup(archive_name)
                self._send_json(200, {"success": True, "message": f"Backup '{deleted}' deleted successfully."})
            except FileNotFoundError:
                self._send_json(404, {"success": False, "error": f"Backup '{archive_name}' not found."})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path in ("/api/backup/config", "/backup/config", "/api/config", "/config"):
            try:
                updated_cfg = save_auto_config(payload)
                self._send_json(200, {"success": True, "message": "Configuration saved successfully.", "config": updated_cfg})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path in ("/api/backup/test-external", "/backup/test-external"):
            target_path = payload.get("path", "")
            res = test_external_path(target_path)
            status_code = 200 if res.get("success") else 400
            self._send_json(status_code, res)

        elif path in ("/api/backup/test-remote", "/backup/test-remote"):
            res = test_remote_connection(payload)
            status_code = 200 if res.get("success") else 400
            self._send_json(status_code, res)

        elif path in ("/api/backup/sync-now", "/backup/sync-now"):
            def run_sync_all():
                archives = glob.glob(os.path.join(BACKUP_DIR, "bahmni_*.tar.gz"))
                archives.sort(key=os.path.getmtime, reverse=True)
                if not archives:
                    raise FileNotFoundError("No existing backup archive found to synchronize.")
                latest_arc = archives[0]
                post_backup_sync(latest_arc)
            ok, msg = run_async("sync_destinations", run_sync_all)
            status_code = 200 if ok else 409
            self._send_json(status_code, {"success": ok, "message": msg or "Synchronization initiated."})

        elif path in ("/api/branding", "/branding"):
            try:
                updated_branding = save_branding_config(payload)
                self._send_json(200, {"success": True, "message": "Branding updated successfully.", "branding": updated_branding})
            except Exception as e:
                log(f"Error saving branding: {e}")
                self._send_json(500, {"success": False, "error": str(e)})

        elif path in ("/api/payment-config", "/payment-config"):
            try:
                updated_cfg = save_payment_config(payload)
                self._send_json(200, {"success": True, "message": "Payment configuration updated successfully.", "config": updated_cfg})
            except Exception as e:
                log(f"Error saving payment configuration: {e}")
                self._send_json(500, {"success": False, "error": str(e)})

        else:
            self._send_json(404, {"error": "Endpoint not found", "path": path})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/").replace("/backup-api", "")
        query_params = parse_qs(parsed.query)
        archive_name = query_params.get("archive", [""])[0]
        if not archive_name and (path.startswith("/backup/") or path.startswith("/api/backup/")):
            archive_name = os.path.basename(path)

        if not archive_name:
            self._send_json(400, {"success": False, "error": "Missing archive filename"})
            return
        try:
            deleted = delete_backup(archive_name)
            self._send_json(200, {"success": True, "message": f"Backup '{deleted}' deleted successfully."})
        except FileNotFoundError:
            self._send_json(404, {"success": False, "error": f"Backup '{archive_name}' not found."})
        except Exception as e:
            self._send_json(500, {"success": False, "error": str(e)})

    def _send_json(self, code, data):
        content = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        # Quiet standard HTTP logs to avoid cluttering
        pass

def start_server():
    threading.Thread(target=ensure_restore_privilege, daemon=True).start()
    threading.Thread(target=start_scheduler_loop, daemon=True).start()
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadingHTTPServer(server_address, BackupAPIHandler)
    log(f"Bahmni Backup Service running on http://0.0.0.0:{PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("Server stopping...")
        httpd.server_close()

def main():
    parser = argparse.ArgumentParser(description="Bahmni Backup & Restore Tool")
    parser.add_argument("--backup-full", action="store_true", help="Run full system backup")
    parser.add_argument("--backup-db", action="store_true", help="Run database-only backup")
    parser.add_argument("--restore", type=str, help="Restore from archive filename or path")
    parser.add_argument("--list", action="store_true", help="List existing backups")
    parser.add_argument("--daemon", action="store_true", help="Run background HTTP API daemon")
    args = parser.parse_args()

    os.makedirs(BACKUP_DIR, exist_ok=True)

    if args.backup_full:
        print("[*] Starting Full System Backup...")
        arc = execute_full_backup()
        print(f"[✔] Full backup complete: {arc}")
    elif args.backup_db:
        print("[*] Starting Database-Only Backup...")
        arc = execute_db_backup()
        print(f"[✔] Database backup complete: {arc}")
    elif args.restore:
        print(f"[*] Starting Restore from: {args.restore}...")
        execute_restore(args.restore)
        print("[✔] Restore complete.")
    elif args.list:
        backups = list_backups()
        print(json.dumps(backups, indent=2))
    elif args.daemon:
        start_server()
    else:
        # Default if no arguments: start server daemon
        start_server()

if __name__ == "__main__":
    main()
