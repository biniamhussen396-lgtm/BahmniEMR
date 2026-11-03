#!/usr/bin/env python3
"""
Bahmni & OpenELIS Implementation Portal - Port 8001
Only accessible to authenticated OpenELIS users with the 'Maintenance' role.
Implements:
  1. clean_patient_data.py
  2. import_kphc_excel_patients.py
  3. attach_patient_documents.py
  4. interactive_pdf_pipeline.py
  5. migrate_patient_profiles.py
"""

import os
import sys
import time
import json
import base64
import uuid
import secrets
import subprocess
import threading
from functools import wraps
from datetime import datetime
from flask import (
    Flask, request, session, redirect, url_for,
    render_template_string, jsonify, Response, send_file
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Target script definitions
SCRIPTS = {
    "clean_patient_data": {
        "file": os.path.join(BASE_DIR, "clean_patient_data.py"),
        "title": "Clean & Purge Patient Data",
        "description": "Purge test/clinical patient data in OpenMRS & Odoo, reconfigure auto-MRN sequence, and re-apply Bahmni UI patches."
    },
    "import_kphc_excel_patients": {
        "file": os.path.join(BASE_DIR, "import_kphc_excel_patients.py"),
        "title": "Import KPHC Excel Patients",
        "description": "Import patient demographics, identifiers, woreda/kebele addresses, and phone attributes from Excel into OpenMRS."
    },
    "migrate_patient_profiles": {
        "file": os.path.join(BASE_DIR, "migrate_patient_profiles.py"),
        "title": "Migrate Patient Profiles",
        "description": "Migrate patient profiles and identifiers from openmrs_legacy_stage into production openmrs with ID offset handling."
    },
    "interactive_pdf_pipeline": {
        "file": os.path.join(BASE_DIR, "interactive_pdf_pipeline.py"),
        "title": "Interactive PDF Pipeline",
        "description": "Stage backup database, extract clinical encounters, generate patient summary PDFs, and attach them to Bahmni."
    },
    "attach_patient_documents": {
        "file": os.path.join(BASE_DIR, "attach_patient_documents.py"),
        "title": "Attach Patient Documents",
        "description": "Link generated clinical summary PDFs to OpenMRS encounter/obs records and set container permissions."
    }
}

# In-memory execution state
execution_lock = threading.Lock()
active_process = {
    "proc": None,
    "script_key": None,
    "status": "idle",  # idle, running, completed, error, cancelled
    "started_at": None,
    "ended_at": None,
    "user": None,
    "logs": []
}

# Auth cache to prevent excessive docker psql queries: {username: {password_hash, is_admin, roles, has_maintenance, expires}}
AUTH_CACHE = {}
CACHE_TTL_SECONDS = 300


# ---------------------------------------------------------------------------
# OpenELIS Blowfish Password Hashing
# ---------------------------------------------------------------------------
def openelis_encrypt_password(plain_pwd: str) -> str:
    """
    OpenELIS uses Blowfish ECB with key '1a2b3c4d5e6f8g9h' and PKCS5/7 padding,
    base64-encoded.
    """
    key = b"1a2b3c4d5e6f8g9h"
    padder = padding.PKCS7(64).padder()
    data = padder.update(plain_pwd.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.Blowfish(key), modes.ECB()).encryptor()
    encrypted = cipher.update(data) + cipher.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def verify_openelis_user(username: str, plain_password: str):
    """
    Validates user credentials against OpenELIS PostgreSQL database (clinlims)
    and verifies that the user holds a 'Maintenance' role or is_admin.
    """
    username_clean = username.strip().replace("'", "''")
    now = time.time()

    # Check in-memory cache
    cached = AUTH_CACHE.get(username_clean.lower())
    if cached and cached["expires"] > now:
        expected_hash = cached["password_hash"]
        if expected_hash == openelis_encrypt_password(plain_password):
            return True, cached

    # Query clinlims database via docker exec
    sql = f"""
    SELECT 
        lu.login_name, 
        lu.password, 
        lu.is_admin, 
        lu.account_locked, 
        lu.account_disabled,
        COALESCE(string_agg(sr.name, ','), '') as roles
    FROM clinlims.login_user lu
    LEFT JOIN clinlims.system_user su ON LOWER(lu.login_name) = LOWER(su.login_name)
    LEFT JOIN clinlims.system_user_role sur ON su.id = sur.system_user_id
    LEFT JOIN clinlims.system_role sr ON sur.role_id = sr.id
    WHERE LOWER(lu.login_name) = LOWER('{username_clean}')
    GROUP BY lu.login_name, lu.password, lu.is_admin, lu.account_locked, lu.account_disabled;
    """
    cmd = [
        "docker", "exec", "-i", "bahmni-standard-openelisdb-1",
        "psql", "-U", "clinlims", "-d", "clinlims", "-At", "-F", "|", "-c", sql
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        out = res.stdout.strip()
        if not out:
            return False, {"error": "User not found in OpenELIS database."}

        parts = out.split("|")
        if len(parts) < 5:
            return False, {"error": "Unexpected OpenELIS authentication response format."}

        login_name = parts[0]
        db_pw_hash = parts[1]
        is_admin = parts[2].strip().upper() == "Y"
        account_locked = parts[3].strip().upper() == "Y"
        account_disabled = parts[4].strip().upper() == "Y"
        roles_str = parts[5].strip() if len(parts) > 5 else ""
        roles_list = [r.strip() for r in roles_str.split(",") if r.strip()]

        if account_locked:
            return False, {"error": "This OpenELIS account is locked."}
        if account_disabled:
            return False, {"error": "This OpenELIS account is disabled."}

        entered_hash = openelis_encrypt_password(plain_password)
        if db_pw_hash != entered_hash:
            return False, {"error": "Invalid OpenELIS password."}

        # Check maintenance role requirement
        has_maintenance = is_admin or any("maint" in r.lower() for r in roles_list)

        user_info = {
            "login_name": login_name,
            "password_hash": db_pw_hash,
            "is_admin": is_admin,
            "roles": roles_list,
            "roles_display": ", ".join(roles_list) if roles_list else ("System Administrator" if is_admin else "None"),
            "has_maintenance": has_maintenance,
            "expires": now + CACHE_TTL_SECONDS
        }

        AUTH_CACHE[username_clean.lower()] = user_info

        if not has_maintenance:
            return False, {
                "error": f"Access Denied: OpenELIS user '{login_name}' does not have the Maintenance role.",
                "unauthorized_role": True,
                "user_info": user_info
            }

        return True, user_info

    except Exception as e:
        return False, {"error": f"Failed to contact OpenELIS database: {str(e)}"}


# ---------------------------------------------------------------------------
# Auth Decorator
# ---------------------------------------------------------------------------
def require_openelis_maintenance(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_sess = session.get("openelis_user")
        if not user_sess:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized: OpenELIS login required"}), 401
            return redirect(url_for("login", next=request.path))

        if not user_sess.get("has_maintenance"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Forbidden: Maintenance role required"}), 403
            return render_template_string(ACCESS_DENIED_TEMPLATE, user=user_sess), 403

        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# Background Process Execution
# ---------------------------------------------------------------------------
def append_log(line: str):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {line}"
    active_process["logs"].append(entry)
    if len(active_process["logs"]) > 2000:
        active_process["logs"].pop(0)


def run_script_worker(script_key: str, cmd_args: list, env_vars: dict = None):
    with execution_lock:
        active_process["script_key"] = script_key
        active_process["status"] = "running"
        active_process["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        active_process["ended_at"] = None
        active_process["logs"] = []

    append_log(f"Starting execution of {SCRIPTS[script_key]['title']}...")
    append_log(f"Command: {' '.join(cmd_args)}")

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    try:
        proc = subprocess.Popen(
            cmd_args,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )
        active_process["proc"] = proc

        for line in iter(proc.stdout.readline, ""):
            if line:
                append_log(line.rstrip())

        proc.stdout.close()
        return_code = proc.wait()

        with execution_lock:
            active_process["ended_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            active_process["proc"] = None
            if active_process["status"] != "cancelled":
                if return_code == 0:
                    active_process["status"] = "completed"
                    append_log("Execution finished successfully (exit code 0).")
                else:
                    active_process["status"] = "error"
                    append_log(f"Execution failed with exit code {return_code}.")

    except Exception as e:
        with execution_lock:
            active_process["status"] = "error"
            active_process["ended_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            active_process["proc"] = None
            append_log(f"Execution exception: {str(e)}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("openelis_user") and session.get("openelis_user", {}).get("has_maintenance"):
        return redirect(url_for("index"))

    error_msg = None
    unauthorized_user = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            error_msg = "Please provide both OpenELIS username and password."
        else:
            success, result = verify_openelis_user(username, password)
            if success:
                session.permanent = True
                session["openelis_user"] = result
                next_url = request.args.get("next") or url_for("index")
                return redirect(next_url)
            else:
                if result.get("unauthorized_role"):
                    unauthorized_user = result.get("user_info")
                    error_msg = result.get("error")
                else:
                    error_msg = result.get("error", "Authentication failed.")

    return render_template_string(LOGIN_TEMPLATE, error=error_msg, unauthorized_user=unauthorized_user)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_openelis_maintenance
def index():
    user = session.get("openelis_user")
    script_statuses = {}
    for k, v in SCRIPTS.items():
        script_statuses[k] = {
            "exists": os.path.exists(v["file"]),
            "size": os.path.getsize(v["file"]) if os.path.exists(v["file"]) else 0,
            "title": v["title"],
            "description": v["description"]
        }

    return render_template_string(
        INDEX_TEMPLATE,
        user=user,
        scripts=script_statuses,
        active_process=active_process
    )


@app.route("/api/status")
@require_openelis_maintenance
def api_status():
    with execution_lock:
        return jsonify({
            "status": active_process["status"],
            "script_key": active_process["script_key"],
            "script_title": SCRIPTS[active_process["script_key"]]["title"] if active_process["script_key"] else None,
            "started_at": active_process["started_at"],
            "ended_at": active_process["ended_at"],
            "user": active_process["user"],
            "logs_count": len(active_process["logs"])
        })


@app.route("/api/logs")
@require_openelis_maintenance
def api_logs():
    since = int(request.args.get("since", 0))
    with execution_lock:
        logs_slice = active_process["logs"][since:]
        return jsonify({
            "status": active_process["status"],
            "script_key": active_process["script_key"],
            "logs": logs_slice,
            "total": len(active_process["logs"])
        })


@app.route("/api/cancel", methods=["POST"])
@require_openelis_maintenance
def api_cancel():
    with execution_lock:
        if active_process["status"] == "running" and active_process["proc"]:
            try:
                active_process["proc"].terminate()
                active_process["status"] = "cancelled"
                active_process["ended_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                append_log("Process execution cancelled by user.")
                return jsonify({"success": True, "message": "Process terminated."})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": False, "message": "No running process to cancel."})


@app.route("/api/run/<script_key>", methods=["POST"])
@require_openelis_maintenance
def api_run_script(script_key):
    if script_key not in SCRIPTS:
        return jsonify({"error": f"Unknown script key: {script_key}"}), 400

    script_path = SCRIPTS[script_key]["file"]
    if not os.path.exists(script_path):
        return jsonify({"error": f"Script file not found: {script_path}"}), 404

    with execution_lock:
        if active_process["status"] == "running":
            return jsonify({"error": "Another script is already running. Please wait or cancel it."}), 409

    data = request.json or {}
    user = session.get("openelis_user", {}).get("login_name", "unknown")
    active_process["user"] = user

    cmd_args = [sys.executable, script_path]
    env_vars = {}

    # Script-specific parameters
    if script_key == "clean_patient_data":
        mode = str(data.get("mode", "1"))
        start_mrn = str(data.get("start_mrn", "")).strip()
        confirm = str(data.get("confirm", "")).strip()
        starting_mrn = str(data.get("starting_mrn", "200000")).strip()

        if confirm != "PURGE":
            return jsonify({"error": "Confirmation word 'PURGE' required."}), 400

        cmd_args.extend(["--mode", mode, "--confirm", "PURGE", "--starting-mrn", starting_mrn])
        if mode == "2":
            if not start_mrn:
                return jsonify({"error": "Starting MRN is required for selective purge."}), 400
            cmd_args.extend(["--start-mrn", start_mrn])

    elif script_key == "import_kphc_excel_patients":
        excel_path = data.get("excel_path", "").strip()
        if excel_path:
            cmd_args.append(excel_path)

    elif script_key == "interactive_pdf_pipeline":
        backup_file = data.get("backup_file", "").strip()
        pdf_out_dir = data.get("pdf_out_dir", "").strip()
        if backup_file:
            env_vars["SPECIFIC_BACKUP"] = backup_file
            cmd_args.append(backup_file)
        if pdf_out_dir:
            env_vars["PDF_OUTPUT_DIR"] = pdf_out_dir
            cmd_args.append(pdf_out_dir)

    elif script_key == "attach_patient_documents":
        pdf_dir = data.get("pdf_dir", "").strip()
        if pdf_dir:
            env_vars["PDF_DIR"] = pdf_dir
            cmd_args.append(pdf_dir)

    elif script_key == "migrate_patient_profiles":
        # migrate_patient_profiles requires no extra args
        pass

    # Launch in background thread
    t = threading.Thread(target=run_script_worker, args=(script_key, cmd_args, env_vars), daemon=True)
    t.start()

    return jsonify({
        "success": True,
        "message": f"Started {SCRIPTS[script_key]['title']}",
        "script_key": script_key
    })


# Background system health monitoring
SYSTEM_HEALTH = {
    "openelis_db": False,
    "openmrs_db": False,
    "openelis_users_count": 0,
    "openmrs_patients_count": 0,
    "staging_patients_count": 0,
    "docker_containers": {},
    "last_updated": None
}

def update_system_health():
    while True:
        try:
            # OpenELIS DB
            try:
                res = subprocess.run(
                    ["docker", "exec", "-i", "bahmni-standard-openelisdb-1", "psql", "-U", "clinlims", "-d", "clinlims", "-At", "-c", "SELECT count(*) FROM clinlims.login_user;"],
                    capture_output=True, text=True, timeout=10
                )
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    SYSTEM_HEALTH["openelis_db"] = True
                    SYSTEM_HEALTH["openelis_users_count"] = int(res.stdout.strip())
                else:
                    SYSTEM_HEALTH["openelis_db"] = False
            except Exception:
                SYSTEM_HEALTH["openelis_db"] = False

            # OpenMRS DB
            try:
                res = subprocess.run(
                    ["docker", "exec", "-i", "bahmni-standard-openmrsdb-1", "mysql", "-uroot", "-padminAdmin!123", "-D", "openmrs", "-sN", "-e", "SELECT count(*) FROM patient WHERE voided = 0;"],
                    capture_output=True, text=True, timeout=10
                )
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    SYSTEM_HEALTH["openmrs_db"] = True
                    SYSTEM_HEALTH["openmrs_patients_count"] = int(res.stdout.strip())
                else:
                    SYSTEM_HEALTH["openmrs_db"] = False
            except Exception:
                SYSTEM_HEALTH["openmrs_db"] = False

            # Staging DB check
            try:
                res = subprocess.run(
                    ["docker", "exec", "-i", "bahmni-standard-openmrsdb-1", "mysql", "-uroot", "-padminAdmin!123", "-D", "openmrs_legacy_stage", "-sN", "-e", "SELECT count(*) FROM patient WHERE voided = 0;"],
                    capture_output=True, text=True, timeout=10
                )
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    SYSTEM_HEALTH["staging_patients_count"] = int(res.stdout.strip())
                else:
                    SYSTEM_HEALTH["staging_patients_count"] = 0
            except Exception:
                SYSTEM_HEALTH["staging_patients_count"] = 0

            # Docker containers
            try:
                res = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}#{{.Status}}"],
                    capture_output=True, text=True, timeout=10
                )
                if res.returncode == 0:
                    c_dict = {}
                    for line in res.stdout.strip().splitlines():
                        if "#" in line:
                            cname, cstatus = line.split("#", 1)
                            c_dict[cname] = cstatus
                    SYSTEM_HEALTH["docker_containers"] = c_dict
            except Exception:
                pass

            SYSTEM_HEALTH["last_updated"] = datetime.now().strftime("%H:%M:%S")

        except Exception as e:
            pass

        time.sleep(30)


# Start background health monitoring thread
threading.Thread(target=update_system_health, daemon=True).start()


@app.route("/api/system-check")
@require_openelis_maintenance
def api_system_check():
    """Returns instant health status of openmrs, openelis, databases, and docker containers."""
    return jsonify(SYSTEM_HEALTH)


# ---------------------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------------------
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Bahmni & OpenELIS Implementation Portal - Login</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body {
      background: linear-gradient(135deg, #0d1b2a 0%, #1b263b 50%, #415a77 100%);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    .login-card {
      max-width: 460px;
      width: 100%;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
      overflow: hidden;
    }
    .login-header {
      background: #0056b3;
      padding: 30px 24px;
      color: white;
      text-align: center;
    }
    .login-header h3 {
      font-weight: 700;
      margin-bottom: 6px;
      letter-spacing: -0.5px;
    }
    .login-header p {
      font-size: 0.9rem;
      opacity: 0.85;
      margin-bottom: 0;
    }
    .login-body {
      padding: 32px 28px;
    }
    .role-badge {
      background: #e7f5ff;
      color: #0056b3;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 0.78rem;
      font-weight: 600;
      display: inline-block;
      margin-top: 8px;
    }
    .btn-login {
      background: #0056b3;
      border: none;
      padding: 12px;
      font-weight: 600;
      letter-spacing: 0.3px;
    }
    .btn-login:hover {
      background: #004494;
    }
  </style>
</head>
<body>
  <div class="login-card">
    <div class="login-header">
      <div class="mb-2"><i class="fa-solid fa-flask-vial fa-2x"></i></div>
      <h3>Implementation Portal</h3>
      <p>Bahmni & OpenELIS Data & Pipeline Manager</p>
      <div class="role-badge">
        <i class="fa-solid fa-shield-halved me-1"></i> Maintenance Role Required (Port 8001)
      </div>
    </div>
    <div class="login-body">
      {% if error %}
      <div class="alert alert-danger d-flex align-items-center" role="alert">
        <i class="fa-solid fa-triangle-exclamation me-2 fa-lg"></i>
        <div>
          <div>{{ error }}</div>
          {% if unauthorized_user %}
          <div class="small mt-1 text-muted">
            Assigned Roles: <strong>{{ unauthorized_user.roles_display }}</strong>.
            <br>You must have the <em>Maintenance Admin</em> role to access this portal.
          </div>
          {% endif %}
        </div>
      </div>
      {% endif %}

      <form method="POST">
        <div class="mb-3">
          <label class="form-label fw-semibold text-secondary">OpenELIS Username</label>
          <div class="input-group">
            <span class="input-group-text"><i class="fa-solid fa-user text-muted"></i></span>
            <input type="text" name="username" class="form-control" placeholder="e.g. admin or atomfeed" required autofocus>
          </div>
        </div>
        <div class="mb-4">
          <label class="form-label fw-semibold text-secondary">OpenELIS Password</label>
          <div class="input-group">
            <span class="input-group-text"><i class="fa-solid fa-lock text-muted"></i></span>
            <input type="password" name="password" class="form-control" placeholder="••••••••" required>
          </div>
        </div>
        <button type="submit" class="btn btn-login btn-primary w-100 shadow-sm">
          <i class="fa-solid fa-right-to-bracket me-2"></i> Authenticate & Enter
        </button>
      </form>
      <div class="mt-4 pt-3 border-top text-center text-muted small">
        <i class="fa-solid fa-lock me-1 text-success"></i> Direct encrypted authentication against OpenELIS database.
      </div>
    </div>
  </div>
</body>
</html>
"""

ACCESS_DENIED_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>403 - Access Denied</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body {
      background: #f8f9fa;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: system-ui, -apple-system, sans-serif;
    }
    .denied-box {
      max-width: 520px;
      padding: 40px;
      background: white;
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.1);
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="denied-box">
    <div class="text-danger mb-3"><i class="fa-solid fa-hand fa-4x"></i></div>
    <h3 class="fw-bold text-dark">Access Denied (403)</h3>
    <p class="text-muted">
      User <strong>{{ user.login_name }}</strong> is logged in, but does not possess the <strong>Maintenance</strong> role.
    </p>
    <div class="alert alert-warning text-start small">
      <strong>Your assigned roles:</strong> {{ user.roles_display }}
      <hr class="my-2">
      Only OpenELIS users with the <strong>Maintenance Admin</strong> role or Administrator privileges are permitted to use this portal on port 8001.
    </div>
    <div class="d-flex justify-content-center gap-2 mt-4">
      <a href="/logout" class="btn btn-outline-danger"><i class="fa-solid fa-right-from-bracket me-1"></i> Log Out & Switch Account</a>
    </div>
  </div>
</body>
</html>
"""

INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Bahmni & OpenELIS Implementation Dashboard (Port 8001)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    :root {
      --primary-color: #0b5ed7;
      --nav-bg: #0d1b2a;
      --card-border: #e2e8f0;
      --terminal-bg: #1e1e1e;
    }
    body {
      background-color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #334155;
    }
    .navbar {
      background-color: var(--nav-bg) !important;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .card {
      border: 1px solid var(--card-border);
      border-radius: 12px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.04);
      transition: all 0.2s ease;
    }
    .card:hover {
      box-shadow: 0 6px 16px rgba(0,0,0,0.08);
    }
    .card-header {
      background: white;
      border-bottom: 1px solid var(--card-border);
      font-weight: 700;
      padding: 16px 20px;
    }
    .terminal-window {
      background: var(--terminal-bg);
      color: #38ef7d;
      font-family: "Consolas", "Courier New", monospace;
      font-size: 0.88rem;
      border-radius: 10px;
      padding: 16px;
      height: 480px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-all;
      border: 1px solid #333;
    }
    .status-badge {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 4px 8px;
      border-radius: 6px;
    }
    .pill-role {
      background: #1e3a8a;
      color: #93c5fd;
      border-radius: 20px;
      padding: 3px 10px;
      font-size: 0.75rem;
      font-weight: 600;
    }
    .btn-action {
      font-weight: 600;
      border-radius: 8px;
      padding: 8px 16px;
    }
  </style>
</head>
<body>

  <!-- Top Navbar -->
  <nav class="navbar navbar-dark navbar-expand-lg py-2">
    <div class="container-fluid px-4">
      <a class="navbar-brand d-flex align-items-center" href="/">
        <i class="fa-solid fa-gears fa-lg text-primary me-2"></i>
        <span class="fw-bold tracking-tight">Bahmni Implementation Manager</span>
        <span class="badge bg-primary ms-2">Port 8001</span>
      </a>
      <div class="d-flex align-items-center gap-3 ms-auto">
        <span class="text-light small">
          <i class="fa-solid fa-user-shield text-info me-1"></i>
          Logged in: <strong>{{ user.login_name }}</strong>
          <span class="pill-role ms-1">Maintenance Role</span>
        </span>
        <a href="http://localhost:8052/openelis" target="_blank" class="btn btn-sm btn-outline-light">
          <i class="fa-solid fa-flask me-1"></i> OpenELIS
        </a>
        <a href="/logout" class="btn btn-sm btn-danger">
          <i class="fa-solid fa-right-from-bracket me-1"></i> Log Out
        </a>
      </div>
    </div>
  </nav>

  <div class="container-fluid px-4 py-4">

    <!-- System Health Summary -->
    <div class="row g-3 mb-4" id="systemHealthRow">
      <div class="col-md-3">
        <div class="card p-3">
          <div class="d-flex align-items-center justify-content-between">
            <div>
              <div class="text-muted small fw-semibold">OpenELIS Database</div>
              <div class="h5 mb-0 fw-bold" id="openelisDbStatus">Checking...</div>
            </div>
            <div class="rounded-circle bg-primary-subtle p-3 text-primary">
              <i class="fa-solid fa-database fa-lg"></i>
            </div>
          </div>
          <div class="small text-muted mt-2" id="openelisUserCount">...</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card p-3">
          <div class="d-flex align-items-center justify-content-between">
            <div>
              <div class="text-muted small fw-semibold">OpenMRS Production DB</div>
              <div class="h5 mb-0 fw-bold" id="openmrsDbStatus">Checking...</div>
            </div>
            <div class="rounded-circle bg-success-subtle p-3 text-success">
              <i class="fa-solid fa-hospital-user fa-lg"></i>
            </div>
          </div>
          <div class="small text-muted mt-2" id="openmrsPatientCount">...</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card p-3">
          <div class="d-flex align-items-center justify-content-between">
            <div>
              <div class="text-muted small fw-semibold">Legacy Staging DB</div>
              <div class="h5 mb-0 fw-bold" id="stagingDbStatus">Checking...</div>
            </div>
            <div class="rounded-circle bg-warning-subtle p-3 text-warning">
              <i class="fa-solid fa-box-archive fa-lg"></i>
            </div>
          </div>
          <div class="small text-muted mt-2" id="stagingPatientCount">...</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card p-3">
          <div class="d-flex align-items-center justify-content-between">
            <div>
              <div class="text-muted small fw-semibold">Execution Worker</div>
              <div class="h5 mb-0 fw-bold" id="workerStatusBadge">
                <span class="badge bg-secondary">Idle</span>
              </div>
            </div>
            <div class="rounded-circle bg-info-subtle p-3 text-info">
              <i class="fa-solid fa-microchip fa-lg"></i>
            </div>
          </div>
          <div class="small text-muted mt-2" id="workerDetail">Ready for tasks</div>
        </div>
      </div>
    </div>

    <!-- Main Content Grid -->
    <div class="row g-4">

      <!-- Left Column: Implementation Action Cards -->
      <div class="col-lg-7">

        <div class="accordion" id="toolsAccordion">

          <!-- 1. Clean Patient Data -->
          <div class="accordion-item card mb-3">
            <h2 class="accordion-header" id="headingClean">
              <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#collapseClean" aria-expanded="true">
                <i class="fa-solid fa-trash-can text-danger me-2"></i>
                <span class="fw-bold me-2">1. Clean & Purge Patient Data</span>
                <span class="badge bg-danger-subtle text-danger border border-danger-subtle ms-auto me-3">clean_patient_data.py</span>
              </button>
            </h2>
            <div id="collapseClean" class="accordion-collapse collapse show" data-bs-parent="#toolsAccordion">
              <div class="accordion-body">
                <p class="text-muted small">
                  Wipes test patient records from OpenMRS & Odoo, resets primary identifier global properties, configures the starting Auto-MRN sequence, and reapplies UI bugfix patches.
                </p>
                <div class="mb-3">
                  <label class="form-label fw-semibold small">Purge Scope Mode</label>
                  <div class="d-flex gap-3">
                    <div class="form-check">
                      <input class="form-check-input" type="radio" name="cleanMode" id="cleanMode1" value="1" checked onchange="toggleCleanMode()">
                      <label class="form-check-label" for="cleanMode1">Full Reset (Purge ALL clinical patients)</label>
                    </div>
                    <div class="form-check">
                      <input class="form-check-input" type="radio" name="cleanMode" id="cleanMode2" value="2" onchange="toggleCleanMode()">
                      <label class="form-check-label" for="cleanMode2">Selective Purge (Start from specific MRN)</label>
                    </div>
                  </div>
                </div>

                <div class="row g-2 mb-3" id="startMrnGroup" style="display: none;">
                  <div class="col-md-6">
                    <label class="form-label fw-semibold small">Starting MRN / Identifier to delete from</label>
                    <input type="text" id="cleanStartMrn" class="form-control form-control-sm" placeholder="e.g. 100000">
                  </div>
                </div>

                <div class="row g-2 mb-3">
                  <div class="col-md-6">
                    <label class="form-label fw-semibold small">Desired Auto-MRN Sequence Start</label>
                    <input type="number" id="cleanAutoMrn" class="form-control form-control-sm" value="200000">
                  </div>
                  <div class="col-md-6">
                    <label class="form-label fw-semibold small text-danger">Safety Confirmation (Type "PURGE")</label>
                    <input type="text" id="cleanConfirm" class="form-control form-control-sm" placeholder="Type PURGE to confirm">
                  </div>
                </div>

                <button class="btn btn-danger btn-action" onclick="executeCleanData()">
                  <i class="fa-solid fa-triangle-exclamation me-1"></i> Execute Patient Data Clean
                </button>
              </div>
            </div>
          </div>

          <!-- 2. Import KPHC Excel Patients -->
          <div class="accordion-item card mb-3">
            <h2 class="accordion-header" id="headingImport">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseImport">
                <i class="fa-solid fa-file-excel text-success me-2"></i>
                <span class="fw-bold me-2">2. Import KPHC Excel Patients</span>
                <span class="badge bg-success-subtle text-success border border-success-subtle ms-auto me-3">import_kphc_excel_patients.py</span>
              </button>
            </h2>
            <div id="collapseImport" class="accordion-collapse collapse" data-bs-parent="#toolsAccordion">
              <div class="accordion-body">
                <p class="text-muted small">
                  Batch imports patient demographics, identifier cards, Woreda/Kebele addresses, and phone numbers from the Excel spreadsheet into OpenMRS MySQL.
                </p>
                <div class="mb-3">
                  <label class="form-label fw-semibold small">Excel Spreadsheet File Path</label>
                  <input type="text" id="excelFilePath" class="form-control form-control-sm" value="/home/kphcs/Documents/KPHCsmartcarePT.xlsx">
                  <div class="form-text">You can enter a custom absolute path on the host or use the default standard path.</div>
                </div>
                <button class="btn btn-success btn-action" onclick="executeExcelImport()">
                  <i class="fa-solid fa-upload me-1"></i> Execute Excel Import
                </button>
              </div>
            </div>
          </div>

          <!-- 3. Migrate Patient Profiles -->
          <div class="accordion-item card mb-3">
            <h2 class="accordion-header" id="headingMigrate">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseMigrate">
                <i class="fa-solid fa-users-gear text-primary me-2"></i>
                <span class="fw-bold me-2">3. Migrate Patient Profiles</span>
                <span class="badge bg-primary-subtle text-primary border border-primary-subtle ms-auto me-3">migrate_patient_profiles.py</span>
              </button>
            </h2>
            <div id="collapseMigrate" class="accordion-collapse collapse" data-bs-parent="#toolsAccordion">
              <div class="accordion-body">
                <p class="text-muted small">
                  Transfers legacy patient demographics, person names, preferred identifiers, addresses, and phone attributes from <code>openmrs_legacy_stage</code> into live <code>openmrs</code> with safe ID offset synchronization.
                </p>
                <div class="alert alert-info py-2 small mb-3">
                  <i class="fa-solid fa-circle-info me-1"></i> Requires staging database <code>openmrs_legacy_stage</code> populated from backup.
                </div>
                <button class="btn btn-primary btn-action" onclick="executeProfileMigration()">
                  <i class="fa-solid fa-arrows-split-up-and-left me-1"></i> Run Profile Migration
                </button>
              </div>
            </div>
          </div>

          <!-- 4. Interactive PDF Pipeline -->
          <div class="accordion-item card mb-3">
            <h2 class="accordion-header" id="headingPdf">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapsePdf">
                <i class="fa-solid fa-file-pdf text-danger me-2"></i>
                <span class="fw-bold me-2">4. Interactive PDF Pipeline</span>
                <span class="badge bg-danger-subtle text-danger border border-danger-subtle ms-auto me-3">interactive_pdf_pipeline.py</span>
              </button>
            </h2>
            <div id="collapsePdf" class="accordion-collapse collapse" data-bs-parent="#toolsAccordion">
              <div class="accordion-body">
                <p class="text-muted small">
                  Restores backup into staging database, queries patients with encounters, formats patient clinical summaries as formatted PDFs with ReportLab, and automatically attaches them to Bahmni.
                </p>
                <div class="mb-3">
                  <label class="form-label fw-semibold small">Source SQL Archive Path (.sql.gz)</label>
                  <input type="text" id="pdfBackupPath" class="form-control form-control-sm" value="/opt/emr/CentOS Bahmni backups/openmrs20261002_160501.sql.gz">
                </div>
                <div class="mb-3">
                  <label class="form-label fw-semibold small">PDF Output Directory</label>
                  <input type="text" id="pdfOutputDir" class="form-control form-control-sm" value="/opt/emr/backups/patient_summary_pdfs">
                </div>
                <button class="btn btn-danger btn-action" onclick="executePdfPipeline()">
                  <i class="fa-solid fa-wand-magic-sparkles me-1"></i> Run PDF Generation Pipeline
                </button>
              </div>
            </div>
          </div>

          <!-- 5. Attach Patient Documents -->
          <div class="accordion-item card mb-3">
            <h2 class="accordion-header" id="headingAttach">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseAttach">
                <i class="fa-solid fa-paperclip text-secondary me-2"></i>
                <span class="fw-bold me-2">5. Attach Patient Documents</span>
                <span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle ms-auto me-3">attach_patient_documents.py</span>
              </button>
            </h2>
            <div id="collapseAttach" class="accordion-collapse collapse" data-bs-parent="#toolsAccordion">
              <div class="accordion-body">
                <p class="text-muted small">
                  Scans generated clinical summary PDFs, matches patients, creates Bahmni 'Patient Document' encounters and obs records, and sets container filesystem permissions.
                </p>
                <div class="mb-3">
                  <label class="form-label fw-semibold small">PDF Directory</label>
                  <input type="text" id="attachPdfDir" class="form-control form-control-sm" value="/opt/emr/backups/patient_summary_pdfs">
                </div>
                <button class="btn btn-secondary btn-action" onclick="executeAttachDocs()">
                  <i class="fa-solid fa-link me-1"></i> Attach Documents to Bahmni
                </button>
              </div>
            </div>
          </div>

        </div>

      </div>

      <!-- Right Column: Real-Time Live Execution Console -->
      <div class="col-lg-5">
        <div class="card h-100 d-flex flex-column">
          <div class="card-header d-flex justify-content-between align-items-center">
            <div>
              <i class="fa-solid fa-terminal me-2 text-primary"></i>
              <span>Live Execution Console</span>
            </div>
            <div class="d-flex align-items-center gap-2">
              <button class="btn btn-xs btn-outline-danger btn-sm" id="btnCancelProcess" onclick="cancelCurrentProcess()" style="display: none;">
                <i class="fa-solid fa-stop me-1"></i> Stop
              </button>
              <button class="btn btn-xs btn-outline-secondary btn-sm" onclick="clearConsole()">
                <i class="fa-solid fa-eraser"></i> Clear
              </button>
            </div>
          </div>
          <div class="card-body p-2 d-flex flex-column flex-grow-1">
            <div class="terminal-window flex-grow-1" id="terminalOutput">
[Console Ready] Waiting for implementation task trigger...
            </div>
          </div>
          <div class="card-footer bg-white border-top py-2 px-3 small d-flex justify-content-between align-items-center text-muted">
            <span id="consoleTaskInfo"><i class="fa-solid fa-circle text-secondary me-1"></i> Idle</span>
            <span id="logCounter">0 lines</span>
          </div>
        </div>
      </div>

    </div>

  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    let logOffset = 0;
    let pollInterval = null;
    let isExecuting = false;

    function toggleCleanMode() {
      const mode = document.querySelector('input[name="cleanMode"]:checked').value;
      document.getElementById('startMrnGroup').style.display = mode === '2' ? 'flex' : 'none';
    }

    function appendTerminal(text) {
      const term = document.getElementById('terminalOutput');
      term.textContent += text + '\\n';
      term.scrollTop = term.scrollHeight;
    }

    function clearConsole() {
      document.getElementById('terminalOutput').textContent = '';
      logOffset = 0;
      document.getElementById('logCounter').textContent = '0 lines';
    }

    async function triggerScript(scriptKey, payload) {
      if (isExecuting) {
        alert("A script is already currently running. Please wait for it to complete.");
        return;
      }

      clearConsole();
      appendTerminal(`[*] Initializing request for ${scriptKey}...`);

      try {
        const resp = await fetch(`/api/run/${scriptKey}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        const data = await resp.json();

        if (!resp.ok) {
          appendTerminal(`[!] Error: ${data.error || 'Failed to start execution'}`);
          alert(data.error || 'Execution failed to start');
          return;
        }

        isExecuting = true;
        document.getElementById('btnCancelProcess').style.display = 'inline-block';
        startLogPolling();

      } catch (err) {
        appendTerminal(`[!] Network Error: ${err.message}`);
      }
    }

    function startLogPolling() {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(async () => {
        try {
          const resp = await fetch(`/api/logs?since=${logOffset}`);
          if (!resp.ok) return;
          const data = await resp.json();

          if (data.logs && data.logs.length > 0) {
            const term = document.getElementById('terminalOutput');
            data.logs.forEach(line => {
              term.textContent += line + '\\n';
            });
            term.scrollTop = term.scrollHeight;
            logOffset = data.total;
            document.getElementById('logCounter').textContent = `${data.total} lines`;
          }

          // Update status badge
          const badge = document.getElementById('workerStatusBadge');
          const detail = document.getElementById('workerDetail');
          const taskInfo = document.getElementById('consoleTaskInfo');

          if (data.status === 'running') {
            badge.innerHTML = '<span class="badge bg-warning text-dark"><i class="fa-solid fa-spinner fa-spin me-1"></i> Running</span>';
            detail.textContent = `Executing ${data.script_key}...`;
            taskInfo.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-warning me-1"></i> Running: ${data.script_key}`;
          } else if (data.status === 'completed') {
            badge.innerHTML = '<span class="badge bg-success">Success</span>';
            detail.textContent = `Completed ${data.script_key}`;
            taskInfo.innerHTML = `<i class="fa-solid fa-circle-check text-success me-1"></i> Completed: ${data.script_key}`;
            isExecuting = false;
            document.getElementById('btnCancelProcess').style.display = 'none';
            clearInterval(pollInterval);
            refreshSystemHealth();
          } else if (data.status === 'error' || data.status === 'cancelled') {
            badge.innerHTML = `<span class="badge bg-danger">${data.status.toUpperCase()}</span>`;
            detail.textContent = `Terminated (${data.status})`;
            taskInfo.innerHTML = `<i class="fa-solid fa-circle-xmark text-danger me-1"></i> ${data.status.toUpperCase()}`;
            isExecuting = false;
            document.getElementById('btnCancelProcess').style.display = 'none';
            clearInterval(pollInterval);
            refreshSystemHealth();
          }
        } catch (e) {
          console.error("Polling error:", e);
        }
      }, 1000);
    }

    async function cancelCurrentProcess() {
      if (!confirm("Are you sure you want to stop the running script?")) return;
      try {
        const resp = await fetch('/api/cancel', {method: 'POST'});
        const data = await resp.json();
        appendTerminal(`[*] Cancel request sent: ${data.message || data.error}`);
      } catch (e) {
        appendTerminal(`[!] Cancel failed: ${e.message}`);
      }
    }

    // 1. Clean Data Trigger
    function executeCleanData() {
      const mode = document.querySelector('input[name="cleanMode"]:checked').value;
      const startMrn = document.getElementById('cleanStartMrn').value.trim();
      const autoMrn = document.getElementById('cleanAutoMrn').value.trim();
      const confirmWord = document.getElementById('cleanConfirm').value.trim();

      if (confirmWord !== "PURGE") {
        alert("You must type 'PURGE' in the confirmation box to proceed.");
        return;
      }
      if (mode === "2" && !startMrn) {
        alert("Please enter a starting MRN for selective purge.");
        return;
      }

      if (!confirm("WARNING: This will permanently delete patient records and reset Auto-MRN sequence. Proceed?")) {
        return;
      }

      triggerScript('clean_patient_data', {
        mode: mode,
        start_mrn: startMrn,
        starting_mrn: autoMrn,
        confirm: confirmWord
      });
    }

    // 2. Excel Import Trigger
    function executeExcelImport() {
      const path = document.getElementById('excelFilePath').value.trim();
      triggerScript('import_kphc_excel_patients', {excel_path: path});
    }

    // 3. Profile Migration Trigger
    function executeProfileMigration() {
      if (!confirm("Execute patient profile migration from openmrs_legacy_stage into production openmrs?")) return;
      triggerScript('migrate_patient_profiles', {});
    }

    // 4. PDF Pipeline Trigger
    function executePdfPipeline() {
      const backup = document.getElementById('pdfBackupPath').value.trim();
      const outDir = document.getElementById('pdfOutputDir').value.trim();
      triggerScript('interactive_pdf_pipeline', {backup_file: backup, pdf_out_dir: outDir});
    }

    // 5. Attach Documents Trigger
    function executeAttachDocs() {
      const pdfDir = document.getElementById('attachPdfDir').value.trim();
      triggerScript('attach_patient_documents', {pdf_dir: pdfDir});
    }

    // Refresh System Health Checks
    async function refreshSystemHealth() {
      try {
        const resp = await fetch('/api/system-check');
        if (!resp.ok) return;
        const data = await resp.json();

        // OpenELIS DB
        const elisDb = document.getElementById('openelisDbStatus');
        const elisCnt = document.getElementById('openelisUserCount');
        if (data.openelis_db) {
          elisDb.innerHTML = '<span class="text-success"><i class="fa-solid fa-check me-1"></i> Active</span>';
          elisCnt.textContent = `${data.openelis_users_count} OpenELIS users registered`;
        } else {
          elisDb.innerHTML = '<span class="text-danger"><i class="fa-solid fa-times me-1"></i> Offline</span>';
          elisCnt.textContent = 'Unable to query clinlims';
        }

        // OpenMRS DB
        const mrsDb = document.getElementById('openmrsDbStatus');
        const mrsCnt = document.getElementById('openmrsPatientCount');
        if (data.openmrs_db) {
          mrsDb.innerHTML = '<span class="text-success"><i class="fa-solid fa-check me-1"></i> Active</span>';
          mrsCnt.textContent = `${data.openmrs_patients_count} active patients`;
        } else {
          mrsDb.innerHTML = '<span class="text-danger"><i class="fa-solid fa-times me-1"></i> Offline</span>';
          mrsCnt.textContent = 'MySQL unreachable';
        }

        // Staging DB
        const stgDb = document.getElementById('stagingDbStatus');
        const stgCnt = document.getElementById('stagingPatientCount');
        if (data.staging_patients_count > 0) {
          stgDb.innerHTML = '<span class="text-warning"><i class="fa-solid fa-check me-1"></i> Staged</span>';
          stgCnt.textContent = `${data.staging_patients_count} legacy records ready`;
        } else {
          stgDb.innerHTML = '<span class="text-muted">Empty / None</span>';
          stgCnt.textContent = 'No staging table found';
        }

      } catch (e) {
        console.error("Health check error:", e);
      }
    }

    // Initial load
    refreshSystemHealth();
  </script>
</body>
</html>
"""


def main():
    port = int(os.environ.get("IMPLEMENTATION_PORT", 8001))
    print(f"============================================================")
    print(f"  Bahmni & OpenELIS Implementation Portal")
    print(f"  Listening on: http://0.0.0.0:{port}")
    print(f"  Access: OpenELIS users with 'Maintenance' role only")
    print(f"============================================================")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
