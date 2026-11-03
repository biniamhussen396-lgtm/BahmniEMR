#!/usr/bin/env python3
import os
import subprocess
import sys
import json
import glob
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

DEFAULT_BACKUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "CentOS Bahmni backups", "openmrs20261002_160501.sql.gz"))
DEFAULT_PDF_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backups", "patient_summary_pdfs"))
SPECIFIC_BACKUP = os.environ.get("SPECIFIC_BACKUP") or (sys.argv[1] if len(sys.argv) > 1 else (DEFAULT_BACKUP if os.name == "nt" or not os.path.exists("/opt/emr/CentOS Bahmni backups/openmrs20261002_160501.sql.gz") else "/opt/emr/CentOS Bahmni backups/openmrs20261002_160501.sql.gz"))
OPENMRS_CONTAINER = "bahmni-standard-openmrsdb-1"
APP_CONTAINER = "bahmni-standard-openmrs-1"
MYSQL_USER = "root"
MYSQL_PASS = "adminAdmin!123"
STAGE_DB = "openmrs_legacy_stage"
TARGET_DB = "openmrs"
PDF_OUTPUT_DIR = os.environ.get("PDF_OUTPUT_DIR") or (sys.argv[2] if len(sys.argv) > 2 else (DEFAULT_PDF_DIR if os.name == "nt" or not os.path.exists("/opt/emr/backups/patient_summary_pdfs") else "/opt/emr/backups/patient_summary_pdfs"))
CONTAINER_DOCS_DIR = "/home/bahmni/document_images"

def run_cmd(cmd, check=True):
    res = subprocess.run(cmd, shell=True, capture_output=True)
    if check and res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")
        print(f"[!] Command error: {err.strip()}", file=sys.stderr)
        sys.exit(res.returncode)
    return res.stdout.decode("utf-8", errors="replace").strip()

def run_sql(query, db=STAGE_DB):
    cmd = [
        "docker", "exec", "-i", OPENMRS_CONTAINER,
        "mysql", f"-u{MYSQL_USER}", f"-p{MYSQL_PASS}", "--default-character-set=utf8mb4",
        "-s", "-N", "-D", db, "-e", query
    ]
    res = subprocess.run(cmd, capture_output=True)
    raw = res.stdout
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")

def verify_and_stage():
    print(f"\n=======================================================")
    print(f"[*] Step 1: Checking Archive & Staging Status")
    print(f"=======================================================")
    if not os.path.exists(SPECIFIC_BACKUP):
        print(f"[!] Archive file not found: {SPECIFIC_BACKUP}")
        sys.exit(1)

    chk = run_sql("SELECT COUNT(*) FROM patient;", STAGE_DB).strip()
    if chk and chk.isdigit() and int(chk) > 0:
        print(f"[✔] Staging database `{STAGE_DB}` verified ready with {chk} patients.")
        return

    print(f"[*] Staging {STAGE_DB} from compressed backup...")
    run_cmd(
        f'docker exec -i {OPENMRS_CONTAINER} mysql -u{MYSQL_USER} -p"{MYSQL_PASS}" '
        f'-e "DROP DATABASE IF EXISTS {STAGE_DB}; CREATE DATABASE {STAGE_DB} CHARACTER SET utf8;"'
    )
    restore_cmd = (
        f'gunzip -c "{SPECIFIC_BACKUP}" | '
        f'sed "s/DEFINER=[^ ]*//g" | '
        f'docker exec -i {OPENMRS_CONTAINER} mysql -u{MYSQL_USER} -p"{MYSQL_PASS}" --force {STAGE_DB}'
    )
    subprocess.run(restore_cmd, shell=True, capture_output=True)
    print(f"[✔] Staging restoration completed.")

def parse_instruction(raw_instr):
    if not raw_instr:
        return ""
    if raw_instr.startswith("{") and "instructions" in raw_instr:
        try:
            data = json.loads(raw_instr)
            return data.get("instructions", "")
        except Exception:
            pass
    return raw_instr.replace('{"instructions":"', '').replace('"}', '').strip()

# Suppress administrative and dummy concept containers
DUMMY_CONCEPTS_TO_DROP = {
    "promethazine hydrobromide", "rutin sodium sulfate", "dimethyl sulfone", 
    "lipotropic agents", "hydroxyamphetamine hydrobromide", "tegaserod", 
    "estradiol hemihydrate", "flupenthixol decanoate", "congenital retinal aneurysm", 
    "hydroxocobalamin acetate", "trichloroacetaldehyde", "pentylenetetrazole",
    "order ast", "crushing injury of toe", "pivampicillin hydrochloride",
    "ferrous ascorbate", "androgen receptor", "verbal autopsy visit date",
    "naphazoline nitrate", "propamidine"
}

DUMMY_DIAGNOSES = {
    "mepolizumab", "gronblad-strandberg syndrome", "allergenic extract, populus alba, p. deltoides",
    "population prevalence of hiv in pregnant women", "generalized infection during labor",
    "non-coded diagnosis", "diagnosis order", "visit diagnoses", "diagnosis"
}

DUMMY_LAB_NAMES = {
    "oxolinic acid", "lasix", "diverticular disease", "oral polio vax no.3",
    "tribasic potassium phosphate", "mesulfen", "propamidine", "naphazoline nitrate"
}

def clean_observation(question, answer, canvas):
    q_low = question.lower().strip()
    a_low = answer.lower().strip()

    if not a_low or a_low in ["-", "none", "null", "undefined", "false", "true", "no"]:
        return None
    if a_low in ["nad", "normal"] and any(k in q_low for k in [
        "throat", "pericarditis", "histidine", "fluconazole", "hearing", "divorced", 
        "t-pen", "stavudine", "aminoaciduria"
    ]):
        return None
    if a_low in ["non-coded diagnosis", "diagnosis order", "billable", "visit diagnoses"]:
        return None
    if q_low in [
        "order attributes", "undo discharge", "registration_concepts", 
        "verbal autopsy visit date", "four days a week", "refused to take", "follow-up condition", "dosage instructions"
    ]:
        return None

    if q_low in DUMMY_CONCEPTS_TO_DROP or a_low in DUMMY_CONCEPTS_TO_DROP:
        return None

    # 1. Chief Complaint & HPI
    if any(k in a_low for k in ["patient comes", "complain", "complaint", "duration", "history of", "presented", "yrs old", "years old", "flank pain", "back pain", "swelling", "headache", "tooth pain", "epigastric"]):
        return ("Chief Complaint & HPI", "Chief Complaint", answer)

    # 2. Vitals
    try:
        val_float = float(answer)
        if 35.0 <= val_float <= 42.5 and ("temp" in q_low or "cured" in q_low or "diagnosis" in q_low):
            return ("Vital Signs", "Temperature", f"{answer} °C")
        if 8 <= val_float <= 50 and ("status" in q_low or "respiratory" in q_low or "admin" in q_low):
            return ("Vital Signs", "Respiratory Rate", f"{int(val_float)} breaths/min")
        if 40 <= val_float <= 220 and ("pulse" in q_low or "heart rate" in q_low):
            return ("Vital Signs", "Pulse / Heart Rate", f"{int(val_float)} bpm")
        if val_float in [1440, 2880, 4320, 7200]:
            days = int(val_float // 1440)
            return ("Chief Complaint & HPI", "Duration of Symptoms", f"{days} days ({int(val_float)} mins)")
    except ValueError:
        pass

    # 3. Physical Examination Findings
    if any(k in a_low for k in ["pink", "conjunctiva", "conjactiva", "sclera", "icteric"]):
        return ("Physical Examination", "Eyes & Sclera", answer)

    if any(k in a_low for k in ["well looking", "sick looking", "acute sick", "oriented", "conscious", "consiouse", "tpp"]):
        return ("Physical Examination", "General Appearance & Mental Status", answer)

    if any(k in a_low for k in ["chest is clear", "breath sound", "wheeze", "crepitation"]):
        return ("Physical Examination", "Respiratory / Chest", answer)

    if any(k in a_low for k in ["s1 and s2", "s1 & s2", "well heard", "murmur"]):
        return ("Physical Examination", "Cardiovascular / Heart Sounds", answer)

    # 4. Symptoms
    if "paromomycin" in q_low or any(sym in a_low for sym in ["fever", "pain", "swelling", "vomiting", "lesion", "ear discharge", "bulching", "bloating"]):
        if len(answer) < 45 and not any(k in a_low for k in ["patient", "years", "health center"]):
            return ("Chief Complaint & HPI", "Reported Symptoms", answer)

    # 5. Diagnoses & Clinical Impressions
    if any(k in q_low for k in ["qid", "tid", "hs", "diagnosis", "confirmed"]):
        if a_low in DUMMY_DIAGNOSES or any(d in a_low for d in ["mepolizumab", "gronblad", "populus alba", "visit diagnoses"]):
            return None
        return ("Clinical Impression & Diagnosis", "Working Diagnosis", answer)

    # 6. Lab & Micro Findings
    if "diverticular disease" in q_low or "no hp seen" in a_low:
        return ("Orders & Lab Investigations", "Blood Film (BF / Malarial Parasite)", answer.upper())

    return None

def fetch_patient_data(pid):
    enc_sql = f"""
    SELECT 
        e.encounter_id,
        DATE_FORMAT(e.encounter_datetime, '%Y-%m-%d') as enc_date,
        DATE_FORMAT(e.encounter_datetime, '%H:%i') as enc_time,
        COALESCE(et.name, 'Consultation') as enc_type,
        COALESCE(CONCAT(pn.given_name, ' ', pn.family_name), 'Super User') as provider_name,
        COALESCE(l.name, 'Outpatient Department') as location_name
    FROM encounter e
    LEFT JOIN encounter_type et ON e.encounter_type = et.encounter_type_id
    LEFT JOIN encounter_provider ep ON e.encounter_id = ep.encounter_id AND ep.voided = 0
    LEFT JOIN provider pr ON ep.provider_id = pr.provider_id
    LEFT JOIN person_name pn ON pr.person_id = pn.person_id AND pn.preferred = 1
    LEFT JOIN location l ON e.location_id = l.location_id
    WHERE e.patient_id = {pid} AND e.voided = 0
    ORDER BY e.encounter_datetime DESC;
    """
    enc_out = run_sql(enc_sql)
    date_groups = {}

    for eline in enc_out.splitlines():
        eparts = eline.split("\t")
        if len(eparts) >= 6:
            eid, edate, etime, etype, eprovider, elocation = eparts[:6]

            # Observations
            obs_sql = f"""
            SELECT 
                COALESCE(f.name, '') as form_name,
                COALESCE(parent_cn.name, '') as canvas_name,
                COALESCE(cq.name, 'Observation') as concept_name,
                COALESCE(
                    ca.name,
                    o.value_text,
                    CAST(o.value_numeric AS CHAR),
                    CAST(o.value_datetime AS CHAR),
                    ''
                ) as answer_value
            FROM obs o
            LEFT JOIN encounter e ON o.encounter_id = e.encounter_id
            LEFT JOIN form f ON e.form_id = f.form_id
            LEFT JOIN obs parent_o ON o.obs_group_id = parent_o.obs_id
            LEFT JOIN concept_name parent_cn ON parent_o.concept_id = parent_cn.concept_id 
                AND parent_cn.locale = 'en' AND parent_cn.concept_name_type = 'FULLY_SPECIFIED' AND parent_cn.voided = 0
            LEFT JOIN concept_name cq ON o.concept_id = cq.concept_id 
                AND cq.locale = 'en' AND cq.concept_name_type = 'FULLY_SPECIFIED' AND cq.voided = 0
            LEFT JOIN concept_name ca ON o.value_coded = ca.concept_id 
                AND ca.locale = 'en' AND (ca.concept_name_type = 'FULLY_SPECIFIED' OR ca.locale_preferred = 1) AND ca.voided = 0
            WHERE o.encounter_id = {eid} AND o.voided = 0
            ORDER BY o.obs_id ASC;
            """
            obs_out = run_sql(obs_sql)
            obs_items = []
            for oline in obs_out.splitlines():
                oparts = oline.split("\t")
                if len(oparts) >= 4:
                    fname, ccanvas, cname, aname = oparts[0].strip(), oparts[1].strip(), oparts[2].strip(), oparts[3].strip()
                    obs_items.append({
                        "form": fname,
                        "canvas": ccanvas,
                        "concept": cname,
                        "answer": aname
                    })

            # Medications: Correctly fetch the actual prescribed medication names from drug, preferred concept name, or fully specified name
            safe_med_sql = f"""
            SELECT 
                COALESCE(d.name, cn_pref.name, cn_fs.name, 'Medication') as drug_name,
                COALESCE(CAST(do.dose AS CHAR), '') as dose,
                COALESCE(do.dosing_instructions, o.instructions, '') as instructions,
                COALESCE(CAST(do.duration AS CHAR), '') as duration
            FROM orders o
            JOIN drug_order do ON o.order_id = do.order_id
            LEFT JOIN drug d ON do.drug_inventory_id = d.drug_id
            LEFT JOIN concept_name cn_pref ON o.concept_id = cn_pref.concept_id AND cn_pref.locale = 'en' AND cn_pref.locale_preferred = 1 AND cn_pref.voided = 0
            LEFT JOIN concept_name cn_fs ON o.concept_id = cn_fs.concept_id AND cn_fs.locale = 'en' AND cn_fs.concept_name_type = 'FULLY_SPECIFIED' AND cn_fs.voided = 0
            WHERE o.encounter_id = {eid} AND o.voided = 0;
            """
            med_out = run_sql(safe_med_sql)
            med_items = []
            for mline in med_out.splitlines():
                mparts = mline.split("\t")
                if len(mparts) >= 4:
                    d_name = mparts[0].strip()
                    d_dose = mparts[1].strip()
                    d_inst = mparts[2].strip()
                    d_dur  = mparts[3].strip()
                    med_items.append({
                        "name": d_name,
                        "dose": d_dose,
                        "units": "Tablet" if d_dose and d_dose.isdigit() and int(d_dose) >= 100 else "",
                        "duration": d_dur,
                        "duration_units": "Days" if d_dur else "",
                        "instructions": d_inst
                    })

            # Orders: Exclude drug_order rows so lab orders stay separated
            ord_sql = f"""
            SELECT 
                COALESCE(ot.name, 'Investigation') as order_type,
                COALESCE(cn.name, 'Order') as order_name,
                COALESCE(
                    ca.name,
                    res_obs.value_text,
                    CAST(res_obs.value_numeric AS CHAR),
                    CAST(res_obs.value_datetime AS CHAR),
                    ''
                ) as result_value
            FROM orders o
            LEFT JOIN order_type ot ON o.order_type_id = ot.order_type_id
            LEFT JOIN concept_name cn ON o.concept_id = cn.concept_id AND cn.locale = 'en' AND cn.concept_name_type = 'FULLY_SPECIFIED' AND cn.voided = 0
            LEFT JOIN obs res_obs ON o.order_id = res_obs.order_id AND res_obs.voided = 0
            LEFT JOIN concept_name ca ON res_obs.value_coded = ca.concept_id AND ca.locale = 'en' AND (ca.concept_name_type = 'FULLY_SPECIFIED' OR ca.locale_preferred = 1) AND ca.voided = 0
            WHERE o.encounter_id = {eid} 
              AND o.order_id NOT IN (SELECT order_id FROM drug_order)
              AND o.voided = 0;
            """
            ord_out = run_sql(ord_sql)
            ord_items = []
            for orline in ord_out.splitlines():
                orparts = orline.split("\t")
                if len(orparts) >= 3:
                    ord_items.append({
                        "type": orparts[0].strip(),
                        "name": orparts[1].strip(),
                        "result": orparts[2].strip()
                    })

            enc_dict = {
                "id": eid,
                "date": edate,
                "time": etime,
                "type": etype,
                "provider": eprovider,
                "location": elocation,
                "observations": obs_items,
                "medications": med_items,
                "orders": ord_items
            }
            date_groups.setdefault(edate, []).append(enc_dict)

    return date_groups

def generate_pdf(patient, date_groups, filepath):
    doc = SimpleDocTemplate(filepath, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=32, bottomMargin=32)
    styles = getSampleStyleSheet()

    date_header_style = ParagraphStyle('DateH', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=colors.HexColor("#1A2B4C"), spaceBefore=10, spaceAfter=2)
    enc_strip_style = ParagraphStyle('EncStrip', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.HexColor("#0B3C5D"), spaceBefore=4, spaceAfter=2)
    sec_title_style = ParagraphStyle('SecTitle', parent=styles['Heading3'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor("#2C3E50"), spaceBefore=3, spaceAfter=1)
    item_style = ParagraphStyle('ItemStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor("#222222"), leftIndent=8, spaceBefore=1, spaceAfter=1)
    patient_meta_style = ParagraphStyle('PatMeta', parent=item_style, fontName='Helvetica-Bold')

    story = []
    p_name = f"{patient['given_name']} {patient['family_name']}".strip() or "Unknown Patient"
    story.append(Paragraph(f"<b>PATIENT CLINICAL SUMMARY — {p_name.upper()}</b>", date_header_style))
    story.append(Paragraph(f"<b>MRN:</b> {patient['mrn']} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Gender:</b> {patient['gender']} &nbsp;&nbsp;|&nbsp;&nbsp; <b>DOB:</b> {patient['birthdate']}", patient_meta_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A2B4C"), spaceBefore=3, spaceAfter=5))

    total_encounters_rendered = 0

    for date_str, encounters in date_groups.items():
        date_story = []

        for enc in encounters:
            sections = {}
            for item in enc['observations']:
                res = clean_observation(item['concept'], item['answer'], item['canvas'])
                if res:
                    sec_name, label, val = res
                    sections.setdefault(sec_name, []).append((label, val))

            # Display real medication names directly
            med_lines = []
            if enc['medications']:
                seen_meds = set()
                for m in enc['medications']:
                    drug_title = m['name']

                    details = []
                    if m['dose']:
                        details.append(f"Dose: {m['dose']} {m['units']}".strip())
                    if m['duration']:
                        details.append(f"Duration: {m['duration']} {m['duration_units']}".strip())
                    if m['instructions']:
                        clean_ins = parse_instruction(m['instructions'])
                        if clean_ins:
                            details.append(f"Instructions: {clean_ins}")

                    detail_str = " | ".join(details) if details else "As prescribed"
                    line = f"• <b>{drug_title}</b> — {detail_str}"
                    if line not in seen_meds:
                        seen_meds.add(line)
                        med_lines.append(line)

            # Lab investigations
            lab_entries = []
            if "Orders & Lab Investigations" in sections:
                for lbl, val in sections["Orders & Lab Investigations"]:
                    lab_entries.append((lbl, val))

            if enc['orders']:
                seen_orders = set()
                for ord_item in enc['orders']:
                    o_name = ord_item['name']
                    if o_name.lower() in DUMMY_LAB_NAMES:
                        if ord_item['result'] and ord_item['result'].lower() not in ["ordered", "naphazoline nitrate", "tenecteplase"]:
                            clean_test_title = "Urinalysis / General Lab Test" if "phosphate" in o_name.lower() else f"Lab Test ({o_name})"
                            lab_entries.append((clean_test_title, ord_item['result']))
                        continue
                    res_str = ord_item['result'] if ord_item['result'] else "Status: Ordered"
                    key = (o_name, res_str)
                    if key not in seen_orders:
                        seen_orders.add(key)
                        lab_entries.append((f"[{ord_item['type']}] {o_name}", res_str))

            has_clinical_data = any([sections, med_lines, lab_entries])
            if not has_clinical_data:
                continue

            total_encounters_rendered += 1
            enc_meta = f"Encounter: {enc['id']} | Provider: {enc['provider']} | Time: {enc['time']} | Location: {enc['location']}"
            date_story.append(Paragraph(enc_meta, enc_strip_style))

            ordered_sections = [
                "Chief Complaint & HPI",
                "Vital Signs",
                "Physical Examination",
                "Clinical Impression & Diagnosis",
            ]

            for s_name in ordered_sections:
                if s_name in sections:
                    date_story.append(Paragraph(f"<b>[{s_name.upper()}]</b>", sec_title_style))
                    seen_entries = set()
                    for lbl, val in sections[s_name]:
                        key = (lbl, val)
                        if key not in seen_entries:
                            seen_entries.add(key)
                            date_story.append(Paragraph(f"• <b>{lbl}:</b> {val}", item_style))
                    date_story.append(Spacer(1, 2))

            if med_lines:
                date_story.append(Paragraph("<b>[MEDICATIONS & PRESCRIPTIONS]</b>", sec_title_style))
                for line in med_lines:
                    date_story.append(Paragraph(line, item_style))
                date_story.append(Spacer(1, 2))

            if lab_entries:
                date_story.append(Paragraph("<b>[ORDERS & LAB INVESTIGATIONS]</b>", sec_title_style))
                dedup_labs = []
                seen_lab_tuples = set()
                for test_name, test_res in lab_entries:
                    if (test_name, test_res) not in seen_lab_tuples:
                        seen_lab_tuples.add((test_name, test_res))
                        dedup_labs.append((test_name, test_res))

                tbl_data = [[Paragraph(f"• <b>{t_name}</b>", item_style), Paragraph(str(t_res), item_style)] for t_name, t_res in dedup_labs[:25]]
                lab_table = Table(tbl_data, colWidths=[300, 240])
                lab_table.setStyle(TableStyle([
                    ('PADDING', (0,0), (-1,-1), 2),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
                ]))
                date_story.append(lab_table)
                date_story.append(Spacer(1, 2))

            date_story.append(Spacer(1, 3))

        if date_story:
            story.append(Paragraph(f"<b>{date_str}</b>", date_header_style))
            story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#A0AEC0"), spaceBefore=1, spaceAfter=3))
            story.extend(date_story)
            story.append(Spacer(1, 2))

    if total_encounters_rendered == 0:
        story.append(Paragraph("<i>No significant active clinical findings or orders recorded.</i>", item_style))

    doc.build(story)

def main():
    verify_and_stage()
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

    print("\n[*] Querying active patients with clinical encounters...")
    full_sql = """
    SELECT p.person_id, pi.identifier, 
           COALESCE(pn.given_name, ''), COALESCE(pn.family_name, ''), 
           COALESCE(p.gender, ''), COALESCE(CAST(p.birthdate AS CHAR), '')
    FROM patient pt
    JOIN person p ON pt.patient_id = p.person_id
    JOIN patient_identifier pi ON pt.patient_id = pi.patient_id
    LEFT JOIN person_name pn ON p.person_id = pn.person_id AND pn.preferred = 1
    WHERE pt.voided = 0
      AND EXISTS (SELECT 1 FROM encounter e WHERE e.patient_id = pt.patient_id AND e.voided = 0)
    GROUP BY pt.patient_id;
    """
    full_out = run_sql(full_sql)
    patients = []
    for line in full_out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 6:
            patients.append({
                "person_id": parts[0],
                "mrn": parts[1].strip(),
                "given_name": parts[2].strip(),
                "family_name": parts[3].strip(),
                "gender": parts[4].strip(),
                "birthdate": parts[5].strip()
            })

    total = len(patients)
    print(f"[✔] Total active patients to process: {total}")

    processed_count = 0
    for idx, pat in enumerate(patients, 1):
        mrn_clean = pat['mrn'].replace("/", "_")
        pdf_path = os.path.join(PDF_OUTPUT_DIR, f"patient_{mrn_clean}.pdf")

        try:
            d_groups = fetch_patient_data(pat["person_id"])
            generate_pdf(pat, d_groups, pdf_path)
            processed_count += 1
        except Exception as e:
            print(f"[!] Warning on MRN {pat['mrn']}: {e}", file=sys.stderr)
            continue

        if idx % 100 == 0 or idx == total:
            print(f"  [{idx}/{total}] Processed MRN {pat['mrn']} ({processed_count} generated)...", flush=True)

    print(f"\n[✔] PDF generation complete! Total processed: {total}")
    print(f"[*] PDFs saved in: {PDF_OUTPUT_DIR}")
    print("\n[*] Automatically attaching PDFs to Docker Bahmni Patient Documents...")
    subprocess.run(["sudo", "python3", "/opt/emr/bahmni-docker/bahmni-standard/attach_patient_documents.py"])

if __name__ == "__main__":
    main()
