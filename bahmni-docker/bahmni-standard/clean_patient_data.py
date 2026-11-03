#!/usr/bin/env python3
import subprocess
import sys

# Container Names
OPENMRS_DB = "bahmni-standard-openmrsdb-1"
OPENMRS_APP = "bahmni-standard-openmrs-1"
ODOO_DB = "bahmni-standard-odoodb-1"
BAHMNI_WEB = "bahmni-standard-bahmni-web-1"

# Database Credentials
MYSQL_USER = "root"
MYSQL_PASS = "adminAdmin!123"
MYSQL_DB = "openmrs"

PRIMARY_ID_TYPE_UUID = "d3153eb0-5e07-11ef-8f7c-0242ac120002"


def run_cmd(cmd, check=True):
    print(f"[*] Running: {cmd}", flush=True)
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and res.returncode != 0:
        print(f"[!] Command failed:\n{res.stderr}", file=sys.stderr, flush=True)
        sys.exit(res.returncode)
    return res.stdout.strip()


def run_mysql(sql):
    cmd = [
        "docker", "exec", "-i", OPENMRS_DB,
        "mysql", f"-u{MYSQL_USER}", f"-p{MYSQL_PASS}", MYSQL_DB
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = p.communicate(input=sql)
    if p.returncode != 0:
        print(f"[!] MySQL query failed:\n{stderr}", file=sys.stderr, flush=True)
        sys.exit(p.returncode)
    return stdout.strip()


def purge_data(start_mrn=None):
    if not start_mrn:
        print("[*] Performing COMPLETE wipe of clinical patient data...")
        sql = """
        SET FOREIGN_KEY_CHECKS = 0;
        TRUNCATE TABLE obs;
        TRUNCATE TABLE encounter_provider;
        TRUNCATE TABLE encounter;
        TRUNCATE TABLE visit_attribute;
        TRUNCATE TABLE visit;
        TRUNCATE TABLE order_group;
        TRUNCATE TABLE orders;
        TRUNCATE TABLE test_order;
        TRUNCATE TABLE drug_order;
        TRUNCATE TABLE referral_order;
        TRUNCATE TABLE patient_identifier;
        TRUNCATE TABLE patient_program;
        TRUNCATE TABLE patient_state;
        TRUNCATE TABLE allergy;
        TRUNCATE TABLE patient;
        DELETE FROM person_name WHERE person_id NOT IN (SELECT person_id FROM users) AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);
        DELETE FROM person_address WHERE person_id NOT IN (SELECT person_id FROM users) AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);
        DELETE FROM person_attribute WHERE person_id NOT IN (SELECT person_id FROM users) AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);
        DELETE FROM person WHERE person_id NOT IN (SELECT person_id FROM users) AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);
        SET FOREIGN_KEY_CHECKS = 1;
        """
        run_mysql(sql)
    else:
        print(f"[*] Selectively purging patient data starting from MRN / Identifier >= '{start_mrn}'...")
        sql = f"""
        SET FOREIGN_KEY_CHECKS = 0;

        DROP TEMPORARY TABLE IF EXISTS target_patients_to_purge;
        CREATE TEMPORARY TABLE target_patients_to_purge AS
        SELECT DISTINCT patient_id 
        FROM patient_identifier 
        WHERE identifier >= '{start_mrn}';

        DELETE FROM obs WHERE person_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM encounter_provider WHERE encounter_id IN (
            SELECT encounter_id FROM encounter WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge)
        );
        DELETE FROM order_group WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM drug_order WHERE order_id IN (
            SELECT order_id FROM orders WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge)
        );
        DELETE FROM orders WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM encounter WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM visit_attribute WHERE visit_id IN (
            SELECT visit_id FROM visit WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge)
        );
        DELETE FROM visit WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM allergy WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM patient_program WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM patient_identifier WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);
        DELETE FROM patient WHERE patient_id IN (SELECT patient_id FROM target_patients_to_purge);

        DELETE FROM person_name WHERE person_id IN (SELECT patient_id FROM target_patients_to_purge)
          AND person_id NOT IN (SELECT person_id FROM users)
          AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);
        DELETE FROM person_address WHERE person_id IN (SELECT patient_id FROM target_patients_to_purge)
          AND person_id NOT IN (SELECT person_id FROM users)
          AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);
        DELETE FROM person_attribute WHERE person_id IN (SELECT patient_id FROM target_patients_to_purge)
          AND person_id NOT IN (SELECT person_id FROM users)
          AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);
        DELETE FROM person WHERE person_id IN (SELECT patient_id FROM target_patients_to_purge)
          AND person_id NOT IN (SELECT person_id FROM users)
          AND person_id NOT IN (SELECT person_id FROM provider WHERE person_id IS NOT NULL);

        DROP TEMPORARY TABLE target_patients_to_purge;
        SET FOREIGN_KEY_CHECKS = 1;
        """
        run_mysql(sql)

    odoo_sql = "DELETE FROM res_partner WHERE id NOT IN (SELECT partner_id FROM res_users) AND parent_id IS NULL;"
    print("[*] Pruning customer records in Odoo...")
    run_cmd(f'docker exec -i {ODOO_DB} psql -U odoo -d odoo -c "{odoo_sql}"', check=False)


def fix_global_properties_and_id_search():
    print("[*] Reconfiguring global properties and metadata mappings for ID search...")
    config_sql = f"""
    -- 1. Bahmni primary identifier type
    UPDATE global_property 
    SET property_value = '{PRIMARY_ID_TYPE_UUID}' 
    WHERE property = 'bahmni.primaryIdentifierType';

    -- 2. Allow flexible matching across identifiers
    UPDATE global_property 
    SET property_value = 'ANYWHERE' 
    WHERE property = 'patientIdentifierSearch.matchMode';

    -- 3. Clear strict Luhn check-digit validator for numeric identifiers
    UPDATE global_property 
    SET property_value = '' 
    WHERE property = 'patient.defaultPatientIdentifierValidator';

    -- 4. Clear regex masks/prefixes that alter search strings
    UPDATE global_property 
    SET property_value = NULL 
    WHERE property IN ('patient.identifierPrefix', 'patient.identifierRegex', 'patient.identifierSearchPattern', 'patient.identifierSuffix');

    UPDATE global_property 
    SET property_value = '' 
    WHERE property = 'bahmni.extraPatientIdentifierTypes';

    -- 5. Align emrapi metadata term mappings
    INSERT INTO metadatamapping_metadata_source (name, description, uuid, date_created, creator)
    VALUES ('org.openmrs.module.emrapi', 'EMR API Module', UUID(), NOW(), 1)
    ON DUPLICATE KEY UPDATE name = 'org.openmrs.module.emrapi';

    SET @src_id = (SELECT metadata_source_id FROM metadatamapping_metadata_source WHERE name = 'org.openmrs.module.emrapi' LIMIT 1);

    DELETE FROM metadatamapping_metadata_term_mapping 
    WHERE code IN ('primaryIdentifierType', 'emr.primaryIdentifierType');

    INSERT INTO metadatamapping_metadata_term_mapping 
    (metadata_source_id, code, name, metadata_class, metadata_uuid, date_created, creator, uuid)
    VALUES 
    (@src_id, 'primaryIdentifierType', 'Primary Identifier Type', 'org.openmrs.PatientIdentifierType', '{PRIMARY_ID_TYPE_UUID}', NOW(), 1, UUID()),
    (@src_id, 'emr.primaryIdentifierType', 'Primary Identifier Type', 'org.openmrs.PatientIdentifierType', '{PRIMARY_ID_TYPE_UUID}', NOW(), 1, UUID());
    """
    run_mysql(config_sql)


def configure_auto_mrn(starting_mrn):
    print(f"[*] Configuring Auto-MRN starting sequence to {starting_mrn}...")
    seq_sql = f"""
    UPDATE idgen_seq_id_gen 
    SET next_sequence_value = {starting_mrn},
        first_identifier_base = '{starting_mrn}'
    WHERE id = 1;
    """
    run_mysql(seq_sql)


def apply_frontend_patches():
    print("[*] Re-applying Bahmni Web UI patches...")
    run_cmd(
        f'docker exec -i {BAHMNI_WEB} sed -i '
        '\'s#\\$location\\.url("/patient/" + \\$scope\\.selectedPatient\\.uuid + "/crTriageVisit");#'
        'var cleanUuid = ($scope.selectedPatient.uuid || "").replace(/^\\/+/g, ""); '
        '\\$location.url("/patient/" + cleanUuid + "/crTriageVisit");#g\' '
        '/usr/local/apache2/htdocs/bahmni/registration/controllers/searchPatientController.js',
        check=False
    )
    run_cmd(
        f'docker exec -i {BAHMNI_WEB} sed -i '
        '\'s#\\$location\\.url("/patient/" + \\$scope\\.selectedPatient\\.uuid + "/prescription");#'
        'var cleanUuid = ($scope.selectedPatient.uuid || "").replace(/^\\/+/g, ""); '
        '\\$location.url("/patient/" + cleanUuid + "/prescription");#g\' '
        '/usr/local/apache2/htdocs/bahmni/registration/controllers/searchPatientController.js',
        check=False
    )
    run_cmd(
        f'docker exec -i {BAHMNI_WEB} sed -i '
        '\'s#\\$location\\.path("/patient/" + patientData\\.patient\\.uuid + "/crTriageVisit");#'
        'var cleanUuid = (patientData.patient.uuid || "").replace(/^\\/+/g, ""); '
        '\\$location.path("/patient/" + cleanUuid + "/crTriageVisit");#g\' '
        '/usr/local/apache2/htdocs/bahmni/registration/controllers/createCRTriagePatientController.js',
        check=False
    )
    run_cmd(
        f'docker exec -i {BAHMNI_WEB} sed -i '
        '\'s#const providerName = patientHistory\\.person\\.currentProvider\\.name#'
        'const providerName = (patientHistory \\&\\& patientHistory.person \\&\\& patientHistory.person.currentProvider) ? '
        'patientHistory.person.currentProvider.name : "";#g\' '
        '/usr/local/apache2/htdocs/bahmni/common/logicAndConditionProcessors/skipLogicProcessor.js',
        check=False
    )
    run_cmd(
        'docker exec lab-result-sync sh -c "echo \'{\\"last_result_id\\": 0}\' > last_result.json"',
        check=False
    )


def restart_services():
    print("[*] Bouncing sync services and OpenMRS application...")
    run_cmd("docker restart bahmni-standard-odoo-connect-1 bahmni-standard-atomfeed-console-1 bahmni-standard-odoo-ssl-1", check=False)
    run_cmd(f"docker restart {OPENMRS_APP}", check=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="BAHMNI / OPENMRS PATIENT DATA PURGE & REPAIR")
    parser.add_argument("--mode", choices=["1", "2"], help="1: Purge ALL, 2: Selective Purge")
    parser.add_argument("--start-mrn", help="Starting MRN if mode 2")
    parser.add_argument("--confirm", help="Must be 'PURGE'")
    parser.add_argument("--starting-mrn", type=int, default=200000, help="Desired starting number for Auto-MRN sequence")
    args = parser.parse_args()

    if args.mode:
        choice = args.mode
        start_mrn = args.start_mrn if choice == "2" else None
        if choice == "2" and not start_mrn:
            print("Invalid MRN provided. Aborting.", flush=True)
            sys.exit(1)
        confirm = args.confirm or ""
        if confirm != "PURGE":
            print("Aborted. Confirmation required (must type 'PURGE').", flush=True)
            sys.exit(0)
        starting_mrn = args.starting_mrn or 200000
    else:
        print("==========================================================")
        print("      BAHMNI / OPENMRS PATIENT DATA PURGE & REPAIR        ")
        print("==========================================================")
        print("Options:")
        print("  1. Purge ALL patients (Full Reset)")
        print("  2. Purge starting from a specific MRN / Identifier (Keep earlier records)")
        choice = input("\nEnter choice [1 or 2]: ").strip()

        start_mrn = None
        if choice == "2":
            start_mrn = input("Enter starting MRN/Identifier to delete from (e.g. 100000): ").strip()
            if not start_mrn:
                print("Invalid MRN provided. Aborting.")
                sys.exit(1)
            confirm = input(f"Confirm deleting all patients with identifier >= '{start_mrn}'? Type 'PURGE': ").strip()
        else:
            confirm = input("Confirm deleting ALL patient data? Type 'PURGE': ").strip()

        if confirm != "PURGE":
            print("Aborted.")
            sys.exit(0)

        # Prompt user for the Auto-MRN starting number
        starting_mrn_input = input("Enter desired starting number for Auto-MRN sequence (e.g., 200000): ").strip()
        if not starting_mrn_input.isdigit():
            print("[!] Invalid starting number provided. Defaulting to 200000.")
            starting_mrn = 200000
        else:
            starting_mrn = int(starting_mrn_input)

    purge_data(start_mrn)
    fix_global_properties_and_id_search()
    configure_auto_mrn(starting_mrn)
    apply_frontend_patches()
    restart_services()

    print(f"\n[✔] Data purge, configuration updates, Auto-MRN configuration ({starting_mrn}), and UI patches completed successfully.")


if __name__ == "__main__":
    main()
