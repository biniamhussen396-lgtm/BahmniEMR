#!/usr/bin/env python3
import os
import sys
import uuid
import pymysql
import openpyxl
from datetime import datetime

DB_CONFIG = {
    "host": os.environ.get("OPENMRS_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("OPENMRS_DB_PORT", 3206 if os.name == "nt" else 3306)),
    "user": os.environ.get("OPENMRS_DB_USER", "root"),
    "password": os.environ.get("OPENMRS_DB_PASSWORD", "adminAdmin!123"),
    "database": os.environ.get("OPENMRS_DB_NAME", "openmrs"),
    "charset": "utf8mb4"
}

def clean_val(v):
    if v is None:
        return ""
    val = str(v).strip()
    return "" if val.lower() in ("none", "null") else val

def parse_dob(dob_raw):
    if not dob_raw:
        return "1985-01-01", 1
    if isinstance(dob_raw, datetime):
        return dob_raw.strftime("%Y-%m-%d"), 0
    s = str(dob_raw).strip()
    try:
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d"), 0
    except Exception:
        if s.isdigit():
            approx_yr = 2026 - int(s)
            return f"{max(1900, approx_yr)}-01-01", 1
        return "1985-01-01", 1

def run_excel_import(excel_path=None):
    if not excel_path:
        excel_path = sys.argv[1] if len(sys.argv) > 1 else "/home/kphcs/Documents/KPHCsmartcarePT.xlsx"
    if not os.path.exists(excel_path):
        print(f"[!] File not found: {excel_path}", flush=True)
        sys.exit(1)

    print("[*] Connecting to OpenMRS MySQL container...")
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("[✔] Database connected.")
    except Exception as e:
        print(f"[!] Database connection failed: {e}")
        sys.exit(1)

    cursor.execute("SELECT patient_identifier_type_id FROM patient_identifier_type WHERE name LIKE '%Bahmni%' OR name LIKE '%Patient%' LIMIT 1;")
    res = cursor.fetchone()
    id_type = res[0] if res else 3

    cursor.execute("SELECT location_id FROM location WHERE name LIKE '%Registration%' OR name LIKE '%Default%' LIMIT 1;")
    res = cursor.fetchone()
    loc_id = res[0] if res else 1

    print(f"[*] Reading data from {excel_path}...")
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    sheet = wb.active

    rows = sheet.iter_rows(values_only=True)
    header_row = next(rows, None)
    if not header_row:
        print("[!] Excel sheet is empty.")
        sys.exit(1)

    batch_size = 500
    batch = []
    imported_count = 0
    skipped_count = 0
    seen_ids = set()

    print("[*] Processing and streaming records into OpenMRS...\n")

    for row in rows:
        pid = clean_val(row[0]) if len(row) > 0 else ""
        surname = clean_val(row[1]) if len(row) > 1 else ""
        firstname = clean_val(row[2]) if len(row) > 2 else ""
        middlename = clean_val(row[3]) if len(row) > 3 else ""
        sex_raw = clean_val(row[4]).upper() if len(row) > 4 else "M"
        dob_raw = row[5] if len(row) > 5 else None
        district = clean_val(row[6]) if len(row) > 6 else ""
        community = clean_val(row[7]) if len(row) > 7 else ""
        phone = clean_val(row[8]) if len(row) > 8 else ""

        if not pid or not firstname:
            skipped_count += 1
            continue

        if pid in seen_ids:
            skipped_count += 1
            continue
        seen_ids.add(pid)

        # Fallback if grandfather name (surname) is blank
        if not surname:
            surname = middlename if middlename else firstname

        gender = "F" if sex_raw.startswith("F") or sex_raw == "ሴት" else "M"
        birthdate, is_est = parse_dob(dob_raw)

        batch.append({
            "pid": pid,
            "fname": firstname,
            "mname": middlename,
            "lname": surname,
            "gender": gender,
            "dob": birthdate,
            "is_est": is_est,
            "district": district,
            "community": community,
            "phone": phone
        })

        if len(batch) >= batch_size:
            insert_batch(cursor, conn, batch, id_type, loc_id)
            imported_count += len(batch)
            print(f"[Activity] {imported_count} patient profiles imported...")
            batch = []

    if batch:
        insert_batch(cursor, conn, batch, id_type, loc_id)
        imported_count += len(batch)

    cursor.close()
    conn.close()
    print("\n" + "=" * 70)
    print(f"[✔] EXCEL IMPORT FINISHED: {imported_count} imported | {skipped_count} skipped")
    print("=" * 70)

def insert_batch(cursor, conn, batch, id_type, loc_id):
    try:
        for r in batch:
            p_uuid = str(uuid.uuid4())

            # 1. Person
            cursor.execute(
                "INSERT INTO person (uuid, gender, birthdate, birthdate_estimated, creator, date_created, voided) "
                "VALUES (%s, %s, %s, %s, 1, NOW(), 0)",
                (p_uuid, r["gender"], r["dob"], r["is_est"])
            )
            person_id = cursor.lastrowid

            # 2. Person Name
            cursor.execute(
                "INSERT INTO person_name (uuid, person_id, given_name, middle_name, family_name, preferred, creator, date_created, voided) "
                "VALUES (%s, %s, %s, %s, %s, 1, 1, NOW(), 0)",
                (str(uuid.uuid4()), person_id, r["fname"], r["mname"], r["lname"])
            )

            # 3. Patient
            cursor.execute(
                "INSERT INTO patient (patient_id, creator, date_created, voided) VALUES (%s, 1, NOW(), 0)",
                (person_id,)
            )

            # 4. Patient Identifier (MRN / Card No)
            cursor.execute(
                "INSERT INTO patient_identifier (uuid, patient_id, identifier, identifier_type, location_id, preferred, creator, date_created, voided) "
                "VALUES (%s, %s, %s, %s, %s, 1, 1, NOW(), 0)",
                (str(uuid.uuid4()), person_id, r["pid"], id_type, loc_id)
            )

            # 5. Address (Woreda & Kebele)
            if r["district"] or r["community"]:
                cursor.execute(
                    "INSERT INTO person_address (uuid, person_id, city_village, county_district, country, preferred, creator, date_created, voided) "
                    "VALUES (%s, %s, %s, %s, 'Ethiopia', 1, 1, NOW(), 0)",
                    (str(uuid.uuid4()), person_id, r["community"], r["district"])
                )

            # 6. Phone Number (Attribute type 9)
            if r["phone"]:
                cursor.execute(
                    "INSERT INTO person_attribute (uuid, person_id, value, person_attribute_type_id, creator, date_created, voided) "
                    "VALUES (%s, %s, %s, 9, 1, NOW(), 0)",
                    (str(uuid.uuid4()), person_id, r["phone"])
                )

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[!] Batch insert error: {e}")

if __name__ == "__main__":
    run_excel_import()
