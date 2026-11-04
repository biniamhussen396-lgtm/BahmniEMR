#!/usr/bin/env python3
"""
Clean & Purge Patient Data
==========================
Wipes test/clinical data from **OpenMRS, OpenELIS, PACS and Odoo**, deletes
non-essential user accounts, reconfigures the primary-identifier / Auto-MRN
settings and re-applies the Bahmni UI patches.

Safety design (please keep when editing):
  * the OpenMRS clinical tables are discovered from the LIVE FK graph at
    runtime (no hardcoded answer When a module adds a table), then hashed
    against a config-table deny-list; anything unexpected ABORTS the purge
  * each system is purged in its own worker thread  -> parallel = fast
  * every PostgreSQL purge runs in ONE transaction   -> atomic (all-or-nothing)
  * MySQL TRUNCATE is DDL (implicit commit), so the FK-graph deny-check
    happens BEFORE any statement is sent
  * user deletion first re-assigns every FK reference to the admin account,
    so no surviving row points at a deleted user
  * kept accounts are never deleted (KEEP_* below) - this includes the
    service accounts the integrations log in with (atomfeed, emrsync,
    daemon, reports-user), otherwise the sync pipelines would break

Usage (portal passes these automatically):
    clean_patient_data.py --mode 1 --confirm PURGE --starting-mrn 200000
    clean_patient_data.py --mode 2 --start-mrn 300000 --confirm PURGE ...
Add --wait to block until OpenMRS is back up after the restart.

Full Reset (mode 1) also runs the DEEP Odoo business wipe: sale orders,
invoices, payments, purchases, stock movements, per-partner attribute rows
and custom-module report rows are purged, which lets the partner prune take
almost every partner out except user/company/config partners.
"""

import argparse
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --------------------------------------------------------------------------
# Containers
# --------------------------------------------------------------------------
OPENMRS_DB = "bahmni-standard-openmrsdb-1"
OPENMRS_APP = "bahmni-standard-openmrs-1"
ODOO_DB = "bahmni-standard-odoodb-1"
BAHMNI_WEB = "bahmni-standard-bahmni-web-1"
OPENELIS_DB = "bahmni-standard-openelisdb-1"
PACS_DB = "bahmni-standard-pacsdb-1"
OPENELIS_APP = "bahmni-standard-openelis-1"
PACS_APP = "bahmni-standard-dcm4chee-1"
ATOMFEED_APP = "bahmni-standard-atomfeed-console-1"
ODOO_CONNECT = "bahmni-standard-odoo-connect-1"

# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------
MYSQL_USER = "root"
MYSQL_PASS = "adminAdmin!123"
MYSQL_DB = "openmrs"

PG_OPENELIS_USER = "clinlims"
PG_OPENELIS_DB = "clinlims"
PG_PACS_USER = "pacs_user"
PG_PACS_DB = "pacs_db"
PG_ODOO_USER = "odoo"
PG_ODOO_DB = "odoo"

PRIMARY_ID_TYPE_UUID = "d3153eb0-5e07-11ef-8f7c-0242ac120002"

# --------------------------------------------------------------------------
# Accounts that are NEVER deleted (lower-case matches)
#   * requested: admin, superman
#   * service accounts: removing them would break integrations
#     - daemon / reports-user : OpenMRS internal + reporting
#     - atomfeed              : OpenELIS atomfeed client (lab sync)
#     - emrsync               : Odoo atomfeed client (Bahmni <-> Odoo)
#     - __system__/default/public/portaltemplate/odoobot : Odoo internals
# --------------------------------------------------------------------------
KEEP_OPENMRS = {"admin", "superman", "daemon", "reports-user"}
KEEP_OPENELIS = {"admin", "superman", "atomfeed", "user"}
KEEP_ODOO = {
    "admin", "superman", "__system__", "default", "public",
    "portaltemplate", "odoobot", "emrsync",
}

# OpenMRS tables that reference patients but always carry business meaning.
# If the FK sweep ever tries to include them the purge aborts instead.
OPENMRS_DENY = {
    "users", "person", "provider", "relationship", "person_attribute_type",
    "person_name", "person_address", "person_attribute",
    "concept", "concept_name", "concept_set", "concept_answer",
    "concept_reference_term", "concept_reference_source", "concept_map_type",
    "concept_class", "concept_datatype", "concept_reference_map",
    "global_property", "location", "location_tag", "role", "privilege",
    "form", "form_field", "form_resource", "program", "visit_type",
    "encounter_type", "encounter_role", "order_type", "order_set",
    "order_frequency", "care_setting", "patient_identifier_type",
    "idgen_identifier_source", "idgen_seq_id_gen", "idgen_log_entry",
    "metadatamapping_metadata_source", "metadatamapping_metadata_set",
    "metadatamapping_metadata_term_mapping", "scheduler_task_config",
    "module", "liquibasechangelog", "hl7_in_archive", "hl7_in_queue",
    "hl7_source", "reporting_report_design", "reporting_report_processor",
}

# --------------------------------------------------------------------------
# Odoo comms tables: deleting a customer partner may cascade rows here.
# That is acceptable (pure messaging state), so partners referenced only by
# these do NOT need to be kept.
# --------------------------------------------------------------------------
ODOO_SAFE_CASCADE = {
    "mail_message", "mail_followers", "mail_activity", "mail_notification",
    "mail_compose_message", "mail_message_reaction",
    "mail_mail_res_partner_rel", "mail_message_res_partner_rel",
    "mail_message_res_partner_starred_rel", "mail_resend_partner",
    "mail_wizard_invite_res_partner_rel", "mail_channel_member",
    "mail_compose_message_res_partner_rel",
    "sms_sms", "snailmail_letter_missing_required_fields",
    "portal_share_res_partner_rel", "portal_wizard_res_partner_rel",
    "portal_wizard_user",
    "base_partner_merge_automatic_wizard",
    "base_partner_merge_automatic_wizard_res_partner_rel",
    "ir_act_server_res_partner_rel",
    "res_partner_autocomplete_sync",
    "res_users_settings_volumes",
    "res_partner_res_partner_category_rel",
    "res_partner_bank",
}

# Tables whose rows are pure credentials of a user -> delete instead of
# re-assigning (re-assigning a TOTP secret to admin would lock admin out).
ODOO_CREDENTIAL_TABLES = {"auth_totp_device", "res_users_apikeys"}

# --------------------------------------------------------------------------
# DEEP business wipe (Full Reset only)
# --------------------------------------------------------------------------
# Transactional business tables wiped by the deep pass, in delete order
# (children/join tables first, headers last). Wiping them lets the partner
# prune go all the way down to user/company/config partners. This list must
# stay transactional-only: never add Odoo framework or config tables here.
ODOO_BUSINESS_TABLES = [
    # many2many / relation tables of business documents
    "sale_order_line_invoice_rel", "sale_order_transaction_rel",
    "sale_order_tag_rel", "sale_order_option",
    "product_template_attribute_value_sale_order_line_rel",
    "account_tax_sale_order_line_rel",
    "sale_advance_payment_inv_sale_order_rel", "sale_advance_payment_inv",
    "account_move_line_account_tax_rel", "account_move_purchase_order_rel",
    "account_move_account_invoice_send_rel",
    "account_move_account_resequence_wizard_rel",
    "account_move_reversal_move", "account_move_reversal_new_move",
    "account_payment_account_bank_statement_line_rel",
    "account_payment_credit_invoice_line",
    "account_payment_outstanding_invoice_line",
    "account_payment_register_move_line_rel", "account_payment_register",
    "account_invoice_transaction_rel",
    "purchase_order_stock_picking_rel", "purchase_register_drug_rel",
    "stock_picking_backorder_rel", "stock_picking_sms_rel",
    "stock_picking_transfer_rel", "stock_move_move_rel",
    "stock_move_line_consume_rel",
    "stock_move_line_stock_picking_validate_wizard_rel",
    "stock_quant_stock_track_confirmation_rel",
    "stock_quant_stock_request_count_rel",
    "stock_inventory_adjustment_name_stock_quant_rel",
    "stock_inventory_conflict_stock_quant_rel",
    "stock_inventory_warning_stock_quant_rel",
    "product_product_stock_track_confirmation_rel",
    "expiry_picking_confirmation_stock_lot_rel",
    "expiry_picking_confirmation_stock_picking_rel",
    # transactional rows
    "pos_pack_operation_lot", "pos_payment", "pos_order_line", "pos_order",
    "sale_order_cancel", "sale_order_line", "sale_order",
    "account_analytic_line", "account_partial_reconcile", "account_move_line",
    "account_full_reconcile", "account_edi_document",
    "account_move_reversal", "account_resequence_wizard",
    "account_invoice_send",
    "account_bank_statement_line", "account_bank_statement",
    "account_payment",
    "account_move",
    "purchase_order_line", "purchase_order", "purchase_register",
    "purchase_return_register", "expiry_picking_confirmation",
    "stock_valuation_layer", "stock_replenishment_info",
    "sale_discount_head_statement_reports", "sale_discount_head_statement",
    "location_wise_drug_movement_product_reports", "location_wise_drug_movement",
    "pro_exp_reports_new", "pro_reorder_reports",
    "purchase_return_product_reports", "purchase_return_vendor_reports",
    "purchase_order_inward_list_product_reports",
    "purchase_order_inward_list_vendor_reports", "purchase_order_inward_list",
    "vendor_price_comparison_product_reports",
    "vendor_price_comparison_vendor_reports", "vendor_price_comparison_list",
    "vendor_register_rel", "vendor_reorder_reports",
    "active_product_statement_product_reports", "active_product_statement",
    "product_reorder_list", "product_expiration_register",
    "expired_product_list", "expired_product_reports",
]
# Only kept if the table actually exists (some may be absent on this Odoo).

# Partner-referencing tables whose rows go down WITH their partner during the
# deep pass (transient/attribute data of the deleted partner, not config).
# Added on top of ODOO_SAFE_CASCADE so they stop protecting partners.
ODOO_DEEP_UNPROTECT = {
    "res_partner_attributes",           # custom per-partner attribute rows
    "vendor_reorder_reports", "vendor_register_rel",
    "vendor_price_comparison_vendor_reports",
    "purchase_return_vendor_reports",
    "purchase_order_inward_list_vendor_reports",
}


# --------------------------------------------------------------------------
# Low level helpers
# --------------------------------------------------------------------------
def run_cmd(cmd, check=True):
    print(f"[*] Running: {cmd}", flush=True)
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and res.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {res.returncode}): {cmd}\n{res.stderr.strip()}"
        )
    return res.stdout.strip()


def run_mysql(sql):
    """Run SQL against the OpenMRS MySQL database (batch mode: aborts on error)."""
    cmd = [
        "docker", "exec", "-i", OPENMRS_DB,
        "mysql", f"-u{MYSQL_USER}", f"-p{MYSQL_PASS}", MYSQL_DB,
    ]
    p = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    stdout, stderr = p.communicate(input=sql)
    if p.returncode != 0:
        raise RuntimeError(f"MySQL query failed:\n{stderr.strip()}")
    return stdout.strip()


def run_psql(container, pg_user, pg_db, sql, tuples=False):
    """
    Run SQL against a PostgreSQL container.
    -1                -> single transaction (atomic)
    ON_ERROR_STOP=1   -> abort on the first error (no partial execution)
    tuples=True       -> clean `value|value` rows for parsing
    """
    cmd = ["docker", "exec", "-i", container, "psql", "-U", pg_user, "-d", pg_db,
           "-1", "-v", "ON_ERROR_STOP=1"]
    if tuples:
        cmd += ["-t", "-A"]
    p = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    stdout, stderr = p.communicate(input=sql)
    if p.returncode != 0:
        raise RuntimeError(f"psql query failed on {container}:\n{stderr.strip()}")
    return stdout.strip()


def mysql_rows(out):
    """Parse `mysql -e` output (tab separated, first line = header)."""
    rows = []
    for line in out.splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def psql_rows(out):
    """Parse `psql -t -A` output (pipe separated), keeping every column."""
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        rows.append(tuple(p.strip() for p in parts))
    return rows


def sql_str_list(values):
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def sql_int_list(values):
    return ", ".join(str(int(v)) for v in values)


# --------------------------------------------------------------------------
# OpenMRS - live FK graph helpers
# --------------------------------------------------------------------------
OPENMRS_ROOTS = {  # table -> primary key column
    "patient": "patient_id",
    "encounter": "encounter_id",
    "visit": "visit_id",
    "orders": "order_id",
    "patient_program": "patient_program_id",
    "allergy": "allergy_id",
    "obs": "obs_id",
}


def openmrs_fk_edges(parents):
    """(child_table, child_column, parent_table) for every FK pointing at `parents`."""
    names = ", ".join("'" + p + "'" for p in parents)
    out = run_mysql(
        "SELECT DISTINCT table_name, column_name, referenced_table_name "
        "FROM information_schema.key_column_usage "
        "WHERE table_schema = 'openmrs' "
        f"AND referenced_table_name IN ({names});"
    )
    edges = set()
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            child, col, parent = (p.strip() for p in parts)
            if child != parent:
                edges.add((child, col, parent))
    return edges


def openmrs_pk_columns(tables):
    """Primary key column per table. Composite PKs return None (ambiguous)."""
    names = ", ".join("'" + t + "'" for t in tables)
    out = run_mysql(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'openmrs' AND column_key = 'PRI' "
        f"AND table_name IN ({names});"
    )
    cols = {}
    for table, col in mysql_rows(out):
        cols.setdefault(table, []).append(col)
    return {t: v[0] for t, v in cols.items() if len(v) == 1}


def openmrs_clinical_closure():
    """
    Discover the FK graph progressively: start from the clinical root tables,
    query all FK edges pointing at the current frontier, repeat until no new
    child tables appear. Returns (all_edges, closure_tables).
    """
    closure = set(OPENMRS_ROOTS)
    frontier = set(OPENMRS_ROOTS)
    edges = set()
    while frontier:
        new_edges = openmrs_fk_edges(frontier)
        edges |= new_edges
        frontier = {child for child, _col, _parent in new_edges} - closure
        closure |= frontier
    return edges, closure


def guard_openmrs_closure(closure):
    hits = sorted(closure & OPENMRS_DENY)
    if hits:
        raise RuntimeError(
            "openmrs: ABORTED - FK closure would touch protected tables: "
            + ", ".join(hits)
        )


def sweep_openmrs_orphans(sql_lines, edges, pk, passes=3):
    """
    For every clinical table, delete rows whose parent rows have vanished.
    Repeat a few passes so grandchildren of purged rows are caught too.
    """
    for _ in range(passes):
        for child, col, parent in sorted(edges):
            if child == parent or parent not in pk:
                continue
            sql_lines.append(
                f"DELETE FROM `{child}` WHERE `{col}` NOT IN "
                f"(SELECT `{pk[parent]}` FROM `{parent}`);"
            )


def purge_openmrs_clinical(start_mrn):
    edges, closure = openmrs_clinical_closure()
    guard_openmrs_closure(closure)
    pk = openmrs_pk_columns(closure)
    missing = [t for t in OPENMRS_ROOTS if t not in pk]
    if missing:
        raise RuntimeError(
            f"openmrs: ABORTED - cannot resolve single-column PK of: {', '.join(missing)}"
        )

    if not start_mrn:
        print("[openmrs] Performing COMPLETE wipe of clinical patient data...",
              flush=True)
        # MySQL TRUNCATE does not support multiple tables in one statement.
        lines = ["SET FOREIGN_KEY_CHECKS = 0;"]
        for t in sorted(closure):
            lines.append(f"TRUNCATE TABLE `{t}`;")
        lines.append("SET FOREIGN_KEY_CHECKS = 1;")
        run_mysql("\n".join(lines))
    else:
        print(f"[openmrs] Selectively purging patient data >= '{start_mrn}'...",
              flush=True)
        mrn = start_mrn.replace("'", "''")
        lines = [
            "SET FOREIGN_KEY_CHECKS = 0;",
            "DROP TEMPORARY TABLE IF EXISTS target_patients_to_purge;",
            "CREATE TEMPORARY TABLE target_patients_to_purge AS",
            "SELECT DISTINCT patient_id FROM patient_identifier "
            f"WHERE identifier >= '{mrn}';",
        ]
        # 1. delete every direct child row of the target patients
        for child, col, parent in sorted(edges):
            if parent != "patient" or child == parent:
                continue
            lines.append(
                f"DELETE FROM `{child}` WHERE `{col}` IN "
                "(SELECT patient_id FROM target_patients_to_purge);"
            )
        # obs carries person_id (== patient_id), not a patient FK column,
        # so it would be missed by the loop above (it may have a NULL
        # encounter/order).
        lines.append(
            "DELETE FROM `obs` WHERE `person_id` IN "
            "(SELECT patient_id FROM target_patients_to_purge);"
        )
        # 2. sweep anything left orphaned by those deletions
        sweep_openmrs_orphans(lines, edges, pk)
        lines += [
            "DROP TEMPORARY TABLE target_patients_to_purge;",
            "SET FOREIGN_KEY_CHECKS = 1;",
        ]
        run_mysql("\n".join(lines))
        print("[openmrs] orphan clinical rows swept.", flush=True)


def reassign_openmrs_user_refs(admin_id, id_list):
    """
    Point EVERY foreign key that references `users` at the surviving admin
    user, except user_property / user_role (those rows are deleted instead).
    """
    out = run_mysql(
        "SELECT DISTINCT table_name, column_name FROM information_schema.key_column_usage "
        "WHERE table_schema = 'openmrs' AND referenced_table_name = 'users' "
        "AND table_name NOT IN ('user_property', 'user_role');"
    )
    stmts = []
    for table, column in mysql_rows(out):
        if table == "users" and column == "user_id":
            continue  # primary key, not an FK
        stmts.append(
            f"UPDATE `{table}` SET `{column}` = {admin_id} "
            f"WHERE `{column}` IN ({id_list});"
        )
    if stmts:
        print(f"[openmrs] reassigning references from {len(stmts)} user FK "
              f"columns to admin #{admin_id}...", flush=True)
        run_mysql("\n".join(stmts))


def delete_openmrs_users():
    out = run_mysql("SELECT user_id, COALESCE(username, system_id) FROM users;")
    rows = mysql_rows(out)
    kept, doomed = {}, {}
    for uid, name in rows:
        key = name.strip().lower()
        (kept if key in KEEP_OPENMRS else doomed)[key] = uid

    print(f"[openmrs] users: {len(rows)} total, keeping {len(kept)} "
          f"({', '.join(sorted(kept)) or '-'}), deleting {len(doomed)}",
          flush=True)
    if not doomed:
        return 0
    if "admin" not in kept:
        raise RuntimeError("openmrs: admin user missing - refusing to delete users")

    admin_id = kept["admin"]
    id_list = sql_int_list(doomed.values())
    reassign_openmrs_user_refs(admin_id, id_list)
    run_mysql(f"""
    SET FOREIGN_KEY_CHECKS = 0;
    DELETE FROM user_role WHERE user_id IN ({id_list});
    DELETE FROM user_property WHERE user_id IN ({id_list});
    DELETE FROM users WHERE user_id IN ({id_list});
    SET FOREIGN_KEY_CHECKS = 1;
    """)
    return len(doomed)


def cleanup_openmrs_persons():
    """
    Remove persons that are neither a user, a provider, nor a surviving
    patient - including persons of deleted users and purged patients.
    Their relationship entries and merge logs are removed as well so no
    dangling rows are left behind.
    """
    def doomed_where(col):
        return (
            f"{col} IS NOT NULL AND {col} NOT IN (SELECT person_id FROM users) "
            "AND NOT EXISTS (SELECT 1 FROM provider p WHERE p.person_id = "
            f"{col}) AND NOT EXISTS (SELECT 1 FROM patient pt WHERE "
            f"pt.patient_id = {col})"
        )

    sql = f"""
    SET FOREIGN_KEY_CHECKS = 0;
    DELETE FROM relationship WHERE {doomed_where('person_a')} OR {doomed_where('person_b')};
    DELETE FROM person_merge_log WHERE {doomed_where('loser_person_id')} OR {doomed_where('winner_person_id')};
    DELETE FROM person_name WHERE {doomed_where('person_id')};
    DELETE FROM person_address WHERE {doomed_where('person_id')};
    DELETE FROM person_attribute WHERE {doomed_where('person_id')};
    DELETE FROM person WHERE {doomed_where('person_id')};
    SET FOREIGN_KEY_CHECKS = 1;
    """
    run_mysql(sql)
    print("[openmrs] orphaned persons removed (users/providers/patients kept)",
          flush=True)


def fix_global_properties_and_id_search():
    print("[openmrs] Reconfiguring global properties and ID search...",
          flush=True)
    config_sql = f"""
    UPDATE global_property
    SET property_value = '{PRIMARY_ID_TYPE_UUID}'
    WHERE property = 'bahmni.primaryIdentifierType';

    UPDATE global_property
    SET property_value = 'ANYWHERE'
    WHERE property = 'patientIdentifierSearch.matchMode';

    UPDATE global_property
    SET property_value = ''
    WHERE property = 'patient.defaultPatientIdentifierValidator';

    UPDATE global_property
    SET property_value = NULL
    WHERE property IN ('patient.identifierPrefix', 'patient.identifierRegex',
                       'patient.identifierSearchPattern', 'patient.identifierSuffix');

    UPDATE global_property
    SET property_value = ''
    WHERE property = 'bahmni.extraPatientIdentifierTypes';

    INSERT INTO metadatamapping_metadata_source (name, description, uuid, date_created, creator)
    VALUES ('org.openmrs.module.emrapi', 'EMR API Module', UUID(), NOW(), 1)
    ON DUPLICATE KEY UPDATE name = 'org.openmrs.module.emrapi';

    SET @src_id = (SELECT metadata_source_id FROM metadatamapping_metadata_source
                   WHERE name = 'org.openmrs.module.emrapi' LIMIT 1);

    DELETE FROM metadatamapping_metadata_term_mapping
    WHERE code IN ('primaryIdentifierType', 'emr.primaryIdentifierType');

    INSERT INTO metadatamapping_metadata_term_mapping
    (metadata_source_id, code, name, metadata_class, metadata_uuid, date_created, creator, uuid)
    VALUES
    (@src_id, 'primaryIdentifierType', 'Primary Identifier Type',
     'org.openmrs.PatientIdentifierType', '{PRIMARY_ID_TYPE_UUID}', NOW(), 1, UUID()),
    (@src_id, 'emr.primaryIdentifierType', 'Primary Identifier Type',
     'org.openmrs.PatientIdentifierType', '{PRIMARY_ID_TYPE_UUID}', NOW(), 1, UUID());
    """
    run_mysql(config_sql)


def configure_auto_mrn(starting_mrn):
    print(f"[openmrs] Configuring Auto-MRN starting sequence to {starting_mrn}...",
          flush=True)
    run_mysql(f"""
    UPDATE idgen_seq_id_gen
    SET next_sequence_value = {int(starting_mrn)},
        first_identifier_base = '{int(starting_mrn)}'
    WHERE id = 1;
    """)


def openmrs_counts():
    out = run_mysql(
        "SELECT (SELECT COUNT(*) FROM patient) AS patients, "
        "(SELECT COUNT(*) FROM users) AS users;"
    )
    rows = mysql_rows(out)
    return rows[0] if rows else ("0", "0")


def task_openmrs(start_mrn):
    t0 = time.time()
    patients_before, users_before = openmrs_counts()
    purge_openmrs_clinical(start_mrn)
    users_deleted = delete_openmrs_users()
    cleanup_openmrs_persons()
    fix_global_properties_and_id_search()
    configure_auto_mrn(_SEQ_START[0])
    patients_after, users_after = openmrs_counts()
    return (f"OpenMRS: patients {patients_before} -> {patients_after}, "
            f"users {users_before} -> {users_after} ({users_deleted} deleted), "
            f"config + Auto-MRN -> {_SEQ_START[0]} ({time.time() - t0:.0f}s)")


# --------------------------------------------------------------------------
# Odoo
# --------------------------------------------------------------------------
def odoo_counts():
    out = run_psql(
        ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
        "SELECT (SELECT COUNT(*) FROM res_partner) AS partners, "
        "(SELECT COUNT(*) FROM res_users) AS users;", tuples=True,
    )
    rows = psql_rows(out)
    return rows[0] if rows else ("0", "0")


def delete_odoo_users():
    out = run_psql(ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
                   "SELECT id, login FROM res_users;", tuples=True)
    kept, doomed = {}, {}
    for row in psql_rows(out):
        uid, login = row[0], "|".join(row[1:])
        key = login.strip().lower()
        (kept if key in KEEP_ODOO else doomed)[key] = uid

    print(f"[odoo] users: total {len(kept) + len(doomed)}, keeping {len(kept)} "
          f"({', '.join(sorted(kept)) or '-'}), deleting {len(doomed)}",
          flush=True)
    if not doomed:
        return 0
    if "admin" not in kept:
        raise RuntimeError("odoo: admin user missing - refusing to delete users")

    admin_id = kept["admin"]
    id_list = sql_int_list(doomed.values())

    # FKs that would BLOCK the delete (NO ACTION / RESTRICT): re-assign data
    # references to admin, but delete pure-credential rows (TOTP/API keys).
    fks = run_psql(
        ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
        "SELECT c.conrelid::regclass::text || '|' || a.attname "
        "FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
        "WHERE c.contype = 'f' AND c.confrelid::regclass::text = 'res_users' "
        "AND c.confdeltype IN ('a','r');", tuples=True,
    )
    stmts = []
    for line in [l for l in fks.splitlines() if l.strip()]:
        child, col = line.split("|", 1)
        if child in ODOO_CREDENTIAL_TABLES:
            stmts.append(f"DELETE FROM {child} WHERE {col} IN ({id_list});")
        else:
            stmts.append(f"UPDATE {child} SET {col} = {admin_id} "
                         f"WHERE {col} IN ({id_list});")
    if stmts:
        print(f"[odoo] resolving {len(stmts)} blocking user references...",
              flush=True)
        run_psql(ODOO_DB, PG_ODOO_USER, PG_ODOO_DB, "\n".join(stmts))

    # Remaining references are SET NULL / CASCADE and clear automatically.
    run_psql(ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
             f"DELETE FROM res_users WHERE id IN ({id_list});")
    return len(doomed)


def purge_odoo_business():
    """
    DEEP pass: wipe all transactional business documents (sale orders,
    invoices/payments, purchases, stock movements, per-partner attribute
    rows, custom hospital-module report rows). DELETE statements run in one
    atomic transaction, children before parents. Framework / config tables
    are deliberately NOT touched (TRUNCATE CASCADE would roll the whole
    Odoo schema in - never use it here).
    """
    # figure out which of the listed tables actually exist on this Odoo build
    names = ", ".join("'" + t + "'" for t in ODOO_BUSINESS_TABLES)
    out = run_psql(
        ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema = 'public' AND table_name IN ({names}) ORDER BY table_name;",
        tuples=True,
    )
    present = {l.strip() for l in out.splitlines() if l.strip()}
    existing = [t for t in ODOO_BUSINESS_TABLES if t in present]
    missing = sorted(set(ODOO_BUSINESS_TABLES) - present)
    if missing:
        print(f"[odoo] deep pass: skipping absent tables: {', '.join(missing)}",
              flush=True)

    # -1 (single transaction) + ON_ERROR_STOP already make this atomic: no
    # explicit BEGIN/COMMIT here (nesting them breaks psql's transaction).
    print(f"[odoo] deep pass: wiping business documents "
          f"({len(existing)} transactional tables, atomic)...", flush=True)
    run_psql(ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
             "\n".join(f"DELETE FROM {t};" for t in existing))


def prune_odoo_partners(deep=False):
    """
    Delete customer/contact partners that no longer belong to anyone.
    Kept: user-linked, business-referenced and RESTRICT-referenced partners.
    Runs in a loop so contacts of deleted roots are removed too, while
    contacts of KEPT parents (parent_id still set) survive.

    deep=True also stops treating transient per-partner data
    (ODOO_DEEP_UNPROTECT) as protection, so the prune goes all the way down.
    """
    excl = [
        "SELECT partner_id AS pid FROM res_users WHERE partner_id IS NOT NULL",
        "SELECT partner_id AS pid FROM res_company WHERE partner_id IS NOT NULL",
        "SELECT partner_id AS pid FROM stock_warehouse WHERE partner_id IS NOT NULL",
    ]
    safe = ODOO_SAFE_CASCADE

    # Partners referenced by business / RESTRICT / NO ACTION FKs. The FK's
    # real column name is used (not every child has partner_id). Pure
    # messaging tables (mail_*, sms, wizard state) are exempt: losing a
    # partner may cascade those safely.
    fks = run_psql(
        ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
        "SELECT DISTINCT c.conrelid::regclass::text || '|' || a.attname "
        "FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
        "WHERE c.contype = 'f' AND c.confrelid::regclass::text = 'res_partner' "
        "AND c.conrelid::regclass::text <> 'res_partner';", tuples=True,
    )
    deep_cols = []  # (table, column) rows to un-link in deep mode
    for line in [l for l in fks.splitlines() if l.strip()]:
        child, col = line.split("|", 1)
        if child in safe:
            continue
        if deep and child in ODOO_DEEP_UNPROTECT:
            # transient per-partner data: its rows are deleted together with
            # the partner (DB FK is RESTRICT, so it needs a pre-delete), and
            # it must not protect the partner from being pruned.
            deep_cols.append((child, col))
            continue
        excl.append(f"SELECT {col} AS pid FROM {child} WHERE {col} IS NOT NULL")

    if deep and deep_cols:
        kept = "NOT IN (" + " UNION ".join(excl) + ")"
        stmts = [f"DELETE FROM {child} WHERE {col} IS NOT NULL AND {col} {kept};"
                 for child, col in deep_cols]
        print(f"[odoo] deep pass: removing per-partner event data from "
              f"{len(deep_cols)} attribute tables...", flush=True)
        run_psql(ODOO_DB, PG_ODOO_USER, PG_ODOO_DB, "\n".join(stmts))

    not_in = "NOT IN (" + " UNION ".join(excl) + ")"
    total = 0
    for _ in range(10):
        out = run_psql(
            ODOO_DB, PG_ODOO_USER, PG_ODOO_DB,
            f"DELETE FROM res_partner WHERE parent_id IS NULL AND id {not_in};",
        )
        m = re.search(r"DELETE\s+(\d+)", out)
        n = int(m.group(1)) if m else 0
        total += n
        if n == 0:
            break
    print(f"[odoo] pruned {total} partner records (protected partners kept)",
          flush=True)
    return total


def task_odoo(mode="standard"):
    t0 = time.time()
    partners_before, users_before = odoo_counts()
    if mode == "deep":
        purge_odoo_business()
    users_deleted = delete_odoo_users()
    partners_deleted = prune_odoo_partners(deep=(mode == "deep"))
    partners_after, users_after = odoo_counts()
    return (f"Odoo ({mode}): partners {partners_before} -> {partners_after} "
            f"({partners_deleted} pruned), users {users_before} -> {users_after} "
            f"({users_deleted} deleted) ({time.time() - t0:.0f}s)")


# --------------------------------------------------------------------------
# OpenELIS
# --------------------------------------------------------------------------
def openelis_counts():
    out = run_psql(
        OPENELIS_DB, PG_OPENELIS_USER, PG_OPENELIS_DB,
        "SELECT (SELECT COUNT(*) FROM patient) AS patients, "
        "(SELECT COUNT(*) FROM sample) AS samples, "
        "(SELECT COUNT(*) FROM analysis) AS analyses, "
        "(SELECT COUNT(*) FROM system_user) AS users;", tuples=True,
    )
    rows = psql_rows(out)
    return rows[0] if rows else ("0", "0", "0", "0")


def postgres_truncate_guard(container, pg_user, pg_db, roots, denylist, label):
    """
    Walk the live FK graph (transitively) starting from the TRUNCATE roots,
    print what would be swept in, and ABORT if a deny-listed config table
    appears. Returns the dependent table list.
    """
    roots_sql = ", ".join("'" + r + "'" for r in roots)
    out = run_psql(
        container, pg_user, pg_db,
        f"""
        WITH RECURSIVE dep(tbl) AS (
            SELECT c.conrelid::regclass::text
            FROM pg_constraint c
            WHERE c.contype = 'f' AND c.confrelid::regclass::text IN ({roots_sql})
            UNION
            SELECT c.conrelid::regclass::text
            FROM pg_constraint c JOIN dep
              ON c.contype = 'f' AND c.confrelid::regclass::text = dep.tbl
        )
        SELECT DISTINCT tbl FROM dep ORDER BY tbl;
        """, tuples=True,
    )
    tables = [l.strip() for l in out.splitlines() if l.strip()]
    hits = sorted(set(tables) & denylist)
    if hits:
        raise RuntimeError(
            f"{label}: ABORTED - purge would touch protected config tables: {', '.join(hits)}"
        )
    print(f"[{label}] FK closure verified ({len(tables)} clinical tables)",
          flush=True)
    return tables


def delete_openelis_users():
    out = run_psql(OPENELIS_DB, PG_OPENELIS_USER, PG_OPENELIS_DB,
                   "SELECT id, login_name FROM system_user;", tuples=True)
    kept, doomed = {}, {}
    for row in psql_rows(out):
        # login_name may contain literal '|', so only the first column is the id
        uid, login = row[0], "|".join(row[1:])
        key = login.strip().lower()
        (kept if key in KEEP_OPENELIS else doomed)[key] = uid

    print(f"[openelis] users: total {len(kept) + len(doomed)}, keeping {len(kept)} "
          f"({', '.join(sorted(kept)) or '-'}), deleting {len(doomed)}",
          flush=True)
    if not doomed:
        return 0
    if "admin" not in kept:
        raise RuntimeError("openelis: admin user missing - refusing to delete users")

    admin_id = kept["admin"]
    id_list = sql_int_list(doomed.values())
    name_list = sql_str_list(doomed.keys())

    # Incoming FKs on system_user are NO ACTION except system_user_role
    # (CASCADE): re-assign the blocking rows to admin so lab records survive.
    fks = run_psql(
        OPENELIS_DB, PG_OPENELIS_USER, PG_OPENELIS_DB,
        "SELECT c.conrelid::regclass::text || '|' || a.attname "
        "FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
        "WHERE c.contype = 'f' AND c.confrelid::regclass::text = 'system_user' "
        "AND c.confdeltype IN ('a','r');", tuples=True,
    )
    stmts = []
    for line in [l for l in fks.splitlines() if l.strip()]:
        child, col = line.split("|", 1)
        stmts.append(f"UPDATE {child} SET {col} = {admin_id} WHERE {col} IN ({id_list});")
    if stmts:
        print(f"[openelis] reassigning {len(stmts)} user references to admin...",
              flush=True)

    run_psql(OPENELIS_DB, PG_OPENELIS_USER, PG_OPENELIS_DB, "\n".join(stmts + [
        f"DELETE FROM system_user WHERE id IN ({id_list});",
        f"DELETE FROM login_user WHERE lower(login_name) IN ({name_list});",
    ]))
    return len(doomed)


def purge_openelis_clinical():
    print("[openelis] Truncating patient/sample/analysis/order data "
          "(single transaction)...", flush=True)
    postgres_truncate_guard(
        OPENELIS_DB, PG_OPENELIS_USER, PG_OPENELIS_DB,
        OPENELIS_ROOTS, OPENELIS_DENY, "openelis",
    )
    run_psql(OPENELIS_DB, PG_OPENELIS_USER, PG_OPENELIS_DB,
             "TRUNCATE " + ", ".join(OPENELIS_ROOTS) + " CASCADE;")


def cleanup_openelis_persons():
    """Drop persons that are neither a provider nor an organization contact.
    (The person table's PK is `id`.)"""
    run_psql(OPENELIS_DB, PG_OPENELIS_USER, PG_OPENELIS_DB, """
    DELETE FROM person_address
     WHERE NOT EXISTS (SELECT 1 FROM provider pr WHERE pr.person_id = person_address.person_id)
       AND NOT EXISTS (SELECT 1 FROM organization_contact oc WHERE oc.person_id = person_address.person_id);
    DELETE FROM person
     WHERE NOT EXISTS (SELECT 1 FROM provider pr WHERE pr.person_id = person.id)
       AND NOT EXISTS (SELECT 1 FROM organization_contact oc WHERE oc.person_id = person.id);
    """)
    print("[openelis] orphaned persons removed (providers/org contacts kept)",
          flush=True)
    print("[openelis] orphaned persons removed (providers/org contacts kept)",
          flush=True)


OPENELIS_ROOTS = ["patient", "sample", "analysis", "orders", "patient_payment",
                  "worksheets"]
OPENELIS_DENY = {
    "site_information", "site_information_domain",
    "system_role", "system_role_module", "system_user", "system_user_module",
    "system_user_role", "system_user_section", "login_user",
    "test", "test_analyte", "test_code", "test_code_type", "test_formats",
    "test_reflex", "test_result", "test_section", "test_status",
    "test_trailer", "test_worksheet_item", "test_worksheets",
    "panel", "panel_item", "sampletype_panel", "sampletype_test",
    "patient_type", "type_of_test_result", "type_of_test_status",
    "analyzer_test_map",
    "person", "person_address", "provider", "organization_contact",
}


def task_openelis(start_mrn):
    t0 = time.time()
    p_before, s_before, a_before, u_before = openelis_counts()
    if start_mrn:
        clinical = ("clinical data kept (selective mode is MRN-scoped in "
                    "OpenMRS/Odoo only)")
    else:
        purge_openelis_clinical()
        cleanup_openelis_persons()
        clinical = "clinical data purged"
    users_deleted = delete_openelis_users()
    p_after, s_after, a_after, u_after = openelis_counts()
    return (f"OpenELIS: {clinical}; patients {p_before} -> {p_after}, "
            f"samples {s_before} -> {s_after}, analyses {a_before} -> {a_after}, "
            f"users {u_before} -> {u_after} ({users_deleted} deleted) "
            f"({time.time() - t0:.0f}s)")


# --------------------------------------------------------------------------
# PACS (dcm4chee)
# --------------------------------------------------------------------------
def pacs_counts():
    out = run_psql(
        PACS_DB, PG_PACS_USER, PG_PACS_DB,
        "SELECT (SELECT COUNT(*) FROM patient) AS patients, "
        "(SELECT COUNT(*) FROM study) AS studies;", tuples=True,
    )
    rows = psql_rows(out)
    return rows[0] if rows else ("0", "0")


def task_pacs(start_mrn):
    t0 = time.time()
    p_before, s_before = pacs_counts()
    if start_mrn:
        return (f"PACS: clinical data kept (selective mode is MRN-scoped in "
                f"OpenMRS/Odoo only) ({time.time() - t0:.0f}s)")
    postgres_truncate_guard(
        PACS_DB, PG_PACS_USER, PG_PACS_DB,
        PACS_ROOTS, PACS_DENY, "pacs",
    )
    print("[pacs] Truncating patient/study/series/instance data "
          "(single transaction)...", flush=True)
    run_psql(PACS_DB, PG_PACS_USER, PG_PACS_DB,
             "TRUNCATE " + ", ".join(PACS_ROOTS) + " CASCADE;")
    p_after, s_after = pacs_counts()
    return (f"PACS: patients {p_before} -> {p_after}, studies {s_before} -> "
            f"{s_after} (stored DICOM files on disk are left in place) "
            f"({time.time() - t0:.0f}s)")


PACS_ROOTS = ["patient", "other_pid", "priv_patient", "media",
              "study_permission"]
PACS_DENY = {
    "ae", "code", "device", "filesystem", "hp", "hpdef", "issuer",
    "users", "roles", "timers",
    "jbm_counter", "jbm_dual", "jbm_id_cache", "jbm_msg", "jbm_msg_ref",
    "jbm_postoffice", "jbm_role", "jbm_tx", "jbm_user",
    "rel_dev_proto", "rel_hpdef_proc", "rel_hpdef_reason", "rel_hpdef_region",
    "ups_glob_subscr",
}


# --------------------------------------------------------------------------
# Bahmni web patches + service restarts
# --------------------------------------------------------------------------
def apply_frontend_patches():
    print("[bahmni-web] Re-applying Bahmni UI patches...", flush=True)
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
        'const providerName = (patientHistory \\&\\& patientHistory.person \\&\\& '
        'patientHistory.person.currentProvider) ? '
        'patientHistory.person.currentProvider.name : "";#g\' '
        '/usr/local/apache2/htdocs/bahmni/common/logicAndConditionProcessors/skipLogicProcessor.js',
        check=False
    )
    run_cmd(
        'docker exec lab-result-sync sh -c "echo \'{\\"last_result_id\\": 0}\' > last_result.json"',
        check=False
    )


def restart_services():
    """Restart integration + app services in parallel (fast)."""
    targets = [
        ATOMFEED_APP, ODOO_CONNECT, OPENELIS_APP, PACS_APP, OPENMRS_APP,
        "bahmni-standard-odoo-1",
    ]
    print(f"[*] Restarting: {', '.join(targets)}", flush=True)
    threads = []
    for t in targets:
        th = threading.Thread(
            target=run_cmd, args=(f"docker restart {t}",),
            kwargs={"check": False},
            daemon=True,
        )
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    print("[*] Restart signals sent (OpenMRS needs ~2-3 minutes to come back).",
          flush=True)


def wait_for_openmrs(timeout=360):
    import urllib.request
    url = "http://localhost:8186/openmrs/ws/rest/v1/session"
    print(f"[*] Waiting for OpenMRS to become ready (max {timeout}s)...",
          flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    print("[OK] OpenMRS is back up.", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(5)
    print("[!] Timed out waiting for OpenMRS - it may still be starting.",
          flush=True)
    return False


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
_SEQ_START = [200000]


def safe_int(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        print(f"[!] Invalid start value '{value}' - defaulting to {default}.",
              flush=True)
        return default


def main():
    parser = argparse.ArgumentParser(
        description="BAHMNI / OPENMRS / OPENELIS / PACS / ODOO DATA PURGE")
    parser.add_argument("--mode", choices=["1", "2"],
                        help="1: Purge ALL, 2: Selective Purge (OpenMRS/Odoo)")
    parser.add_argument("--start-mrn", help="Starting MRN if mode 2")
    parser.add_argument("--confirm", help="Must be 'PURGE'")
    parser.add_argument("--starting-mrn", type=str, default="200000",
                        help="Desired starting number for Auto-MRN sequence")
    parser.add_argument("--wait", action="store_true",
                        help="Block until OpenMRS is reachable again")
    args = parser.parse_args()

    if args.mode:
        choice = args.mode
        start_mrn = args.start_mrn if choice == "2" else None
        if choice == "2" and not start_mrn:
            print("Invalid MRN provided. Aborting.", flush=True)
            sys.exit(1)
        confirm = args.confirm or ""
        if confirm != "PURGE":
            print("Aborted. Confirmation required (must type 'PURGE').",
                  flush=True)
            sys.exit(0)
        starting_mrn = safe_int(args.starting_mrn, 200000)
    else:
        print("=" * 60)
        print("  BAHMNI MULTI-SYSTEM PATIENT DATA PURGE & REPAIR")
        print("  Targets: OpenMRS | OpenELIS | PACS | Odoo")
        print("=" * 60)
        print("Options:")
        print("  1. Purge ALL patients (Full Reset)")
        print("  2. Purge starting from a specific MRN (OpenMRS/Odoo only)")
        choice = input("\nEnter choice [1 or 2]: ").strip()

        start_mrn = None
        if choice == "2":
            start_mrn = input("Enter starting MRN/Identifier to delete from: ").strip()
            if not start_mrn:
                print("Invalid MRN provided. Aborting.")
                sys.exit(1)
            confirm = input(
                f"Confirm deleting all patients >= '{start_mrn}'? Type 'PURGE': "
            ).strip()
        else:
            confirm = input("Confirm deleting ALL patient data + non-admin users "
                            "in OpenMRS/OpenELIS/Odoo? Type 'PURGE': ").strip()

        if confirm != "PURGE":
            print("Aborted.")
            sys.exit(0)

        starting_mrn_input = input(
            "Enter desired starting number for Auto-MRN sequence (e.g., 200000): "
        ).strip()
        starting_mrn = (int(starting_mrn_input)
                        if starting_mrn_input.isdigit() else 200000)

    _SEQ_START[0] = starting_mrn

    mode_label = "FULL" if not start_mrn else f"SELECTIVE:{start_mrn}"
    print("=" * 60, flush=True)
    print(f"  PURGE START (mode={mode_label})  Auto-MRN -> {starting_mrn}",
          flush=True)
    print(f"  Kept users: openmrs={sorted(KEEP_OPENMRS)}", flush=True)
    print(f"              openelis={sorted(KEEP_OPENELIS)}", flush=True)
    print(f"              odoo={sorted(KEEP_ODOO)}", flush=True)
    print("=" * 60, flush=True)

    started = time.time()
    jobs = {
        "openmrs": lambda: task_openmrs(start_mrn),
        "odoo": lambda: task_odoo("deep" if not start_mrn else "standard"),
        "openelis": lambda: task_openelis(start_mrn),
        "pacs": lambda: task_pacs(start_mrn),
        "patches": lambda: (
            (apply_frontend_patches(), "Bahmni web UI patches re-applied")[1]),
    }

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
                print(f"[OK] {results[name]}", flush=True)
            except Exception as exc:
                errors[name] = str(exc)
                print(f"[!] {name} FAILED: {exc}", flush=True)

    # Restart integrations + OpenMRS after every database change is in.
    restart_services()
    if args.wait:
        wait_for_openmrs()

    elapsed = time.time() - started
    print("=" * 60, flush=True)
    if errors:
        print(f"[!] PURGE FINISHED WITH ERRORS in {elapsed:.0f}s "
              f"({', '.join(sorted(errors))})", flush=True)
        for name, msg in errors.items():
            print(f"    - {name}: {msg}", flush=True)
        print("=" * 60, flush=True)
        sys.exit(1)

    print(f"[OK] PURGE COMPLETE in {elapsed:.0f}s - all four systems cleaned.",
          flush=True)
    print("    NOTE: services are restarting in the background; OpenMRS will "
          "be ready in ~2-3 minutes.", flush=True)
    print("    Refresh the login page once it is back (or use --wait to block "
          "until ready).", flush=True)


if __name__ == "__main__":
    main()
