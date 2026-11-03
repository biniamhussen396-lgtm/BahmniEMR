#!/usr/bin/env python3
import os
import subprocess
import sys
import glob
import uuid
from datetime import datetime

OPENMRS_CONTAINER = "bahmni-standard-openmrsdb-1"
APP_CONTAINER = "bahmni-standard-openmrs-1"
MYSQL_USER = "root"
MYSQL_PASS = "adminAdmin!123"
LIVE_DB = "openmrs"
DEFAULT_PDF_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backups", "patient_summary_pdfs"))
PDF_DIR = os.environ.get("PDF_DIR") or (sys.argv[1] if len(sys.argv) > 1 else (DEFAULT_PDF_DIR if os.name == "nt" or not os.path.exists("/opt/emr/backups/patient_summary_pdfs") else "/opt/emr/backups/patient_summary_pdfs"))
CONTAINER_DOC_DIR = "/home/bahmni/document_images"

def run_sql(query):
    cmd = [
        "docker", "exec", "-i", OPENMRS_CONTAINER,
        "mysql", f"-u{MYSQL_USER}", f"-p{MYSQL_PASS}", "--default-character-set=utf8mb4",
        "-s", "-N", "-D", LIVE_DB, "-e", query
    ]
    res = subprocess.run(cmd, capture_output=True)
    raw = res.stdout
    try:
        return raw.decode("utf-8").strip()
    except Exception:
        return raw.decode("latin-1", errors="replace").strip()

def main():
    print(f"\n=======================================================")
    print(f"[*] Attaching Generated Clinical Summaries to Bahmni...")
    print(f"=======================================================")

    pdf_files = glob.glob(os.path.join(PDF_DIR, "patient_*.pdf"))
    if not pdf_files:
        print(f"[!] No summary PDFs found in {PDF_DIR}")
        sys.exit(1)

    print(f"[✔] Found {len(pdf_files)} PDF summaries to process.")

    # 1. Look up static configuration concepts & types
    enc_type_id = run_sql("""
    SELECT encounter_type_id FROM encounter_type 
    WHERE name IN ('Patient Document', 'Consultation') 
    ORDER BY CASE WHEN name = 'Patient Document' THEN 1 ELSE 2 END 
    LIMIT 1;
    """) or "1"

    # Pre-fetch existing documents to avoid duplicate inserts
    existing_docs = set()
    existing_out = run_sql("SELECT value_text FROM obs WHERE concept_id = 57353 AND voided = 0;")
    for line in existing_out.splitlines():
        if line.strip():
            existing_docs.add(line.strip())

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    attached_count = 0
    skipped_count = 0

    total = len(pdf_files)
    for idx, pdf_path in enumerate(pdf_files, 1):
        filename = os.path.basename(pdf_path)
        # Extract MRN from 'patient_<MRN>.pdf'
        mrn = filename.replace("patient_", "").replace(".pdf", "").replace("_", "/")

        # 2. Lookup live patient ID
        pat_info = run_sql(f"""
        SELECT p.person_id, pt.patient_id 
        FROM patient_identifier pi 
        JOIN patient pt ON pi.patient_id = pt.patient_id 
        JOIN person p ON pt.patient_id = p.person_id 
        WHERE pi.identifier = '{mrn}' AND pt.voided = 0 LIMIT 1;
        """)

        if not pat_info:
            skipped_count += 1
            continue

        person_id, patient_id = pat_info.split("\t")[:2]
        target_filename = f"legacy_summary_{mrn.replace('/', '_')}.pdf"
        doc_rel_path = f"{patient_id}/{target_filename}"

        if doc_rel_path in existing_docs:
            skipped_count += 1
            if idx % 500 == 0 or idx == total:
                print(f"  [{idx}/{total}] Processed ({attached_count} attached, {skipped_count} skipped/existed)...", flush=True)
            continue

        # 3. Get or create active OPD Visit (visit_type_id = 4)
        visit_id = run_sql(f"""
        SELECT visit_id FROM visit 
        WHERE patient_id = {patient_id} AND voided = 0 
        ORDER BY date_started DESC LIMIT 1;
        """)

        if not visit_id:
            v_uuid = str(uuid.uuid4())
            run_sql(f"""
            INSERT INTO visit (patient_id, visit_type_id, date_started, location_id, creator, date_created, voided, uuid)
            VALUES ({patient_id}, 4, '{now_str}', 1, 1, '{now_str}', 0, '{v_uuid}');
            """)
            visit_id = run_sql(f"SELECT visit_id FROM visit WHERE uuid = '{v_uuid}';")

        # 4. Copy PDF to container document storage
        patient_folder = f"{CONTAINER_DOC_DIR}/{patient_id}"
        subprocess.run(f"docker exec {APP_CONTAINER} mkdir -p '{patient_folder}'", shell=True)
        subprocess.run(f"docker cp '{pdf_path}' '{APP_CONTAINER}:{patient_folder}/{target_filename}'", shell=True)

        # 5. Insert Encounter & Hierarchical Obs (Parent: 57356 -> Child: 57353)
        enc_uuid = str(uuid.uuid4())
        parent_obs_uuid = str(uuid.uuid4())
        child_obs_uuid = str(uuid.uuid4())

        insert_sql = f"""
        INSERT INTO encounter (
            encounter_type, patient_id, visit_id, location_id, encounter_datetime, 
            creator, date_created, voided, uuid
        ) VALUES (
            {enc_type_id}, {patient_id}, {visit_id}, 1, '{now_str}', 
            1, '{now_str}', 0, '{enc_uuid}'
        );
        SET @new_enc = LAST_INSERT_ID();

        INSERT INTO obs (
            person_id, concept_id, encounter_id, obs_datetime, location_id, 
            creator, date_created, voided, uuid
        ) VALUES (
            {person_id}, 57356, @new_enc, '{now_str}', 1, 
            1, '{now_str}', 0, '{parent_obs_uuid}'
        );
        SET @parent_obs = LAST_INSERT_ID();

        INSERT INTO obs (
            person_id, concept_id, encounter_id, obs_group_id, obs_datetime, location_id, 
            value_text, creator, date_created, voided, uuid
        ) VALUES (
            {person_id}, 57353, @new_enc, @parent_obs, '{now_str}', 1, 
            '{doc_rel_path}', 1, '{now_str}', 0, '{child_obs_uuid}'
        );
        """
        run_sql(insert_sql)
        existing_docs.add(doc_rel_path)
        attached_count += 1

        if idx % 100 == 0 or idx == total:
            print(f"  [{idx}/{total}] Processed ({attached_count} attached, {skipped_count} skipped/existed)...", flush=True)

    # Set container permissions once after the batch finishes
    print("[*] Setting filesystem permissions in Bahmni container...")
    subprocess.run(f"docker exec {APP_CONTAINER} chown -R bahmni:bahmni '{CONTAINER_DOC_DIR}'", shell=True)
    subprocess.run(f"docker exec {APP_CONTAINER} chmod -R 775 '{CONTAINER_DOC_DIR}'", shell=True)

    print(f"\n[✔] Attachment Complete! Total: {total} (Newly Attached: {attached_count}, Skipped/Existing: {skipped_count})")

if __name__ == "__main__":
    main()
