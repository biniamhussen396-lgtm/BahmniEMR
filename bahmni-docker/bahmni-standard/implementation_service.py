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
import re
import sys
import time
import json
import base64
import queue
import shutil
import uuid
import secrets
import subprocess
import threading
import http.client
from functools import wraps
from datetime import datetime
from urllib.parse import quote, urlparse
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
        "description": "Purge test/clinical patient data in OpenMRS, OpenELIS, PACS & Odoo (Full Reset also deep-wipes Odoo business data: sale orders, invoices, partners), delete non-essential users, reconfigure auto-MRN sequence, and re-apply Bahmni UI patches."
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


# ---------------------------------------------------------------------------
# Backup & Restore proxy  (restore was moved here from the Bahmni admin page)
# Proxies to the backup service: bahmni-backup-service on 127.0.0.1:5055
# ---------------------------------------------------------------------------
BACKUP_API_URL = os.environ.get("BACKUP_API_URL", "http://127.0.0.1:5055").rstrip("/")
_backup_parts = urlparse(BACKUP_API_URL)
BACKUP_API_HOST = _backup_parts.hostname or "127.0.0.1"
BACKUP_API_PORT = _backup_parts.port or 80
BACKUP_API_BASE = (_backup_parts.path or "").rstrip("")


def _backup_request(method, path, body=None, timeout=30):
    """Send a JSON request to the backup service. Returns (status, dict)."""
    conn = http.client.HTTPConnection(BACKUP_API_HOST, BACKUP_API_PORT, timeout=timeout)
    try:
        payload = None
        headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, BACKUP_API_BASE + path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {"raw": raw.decode("utf-8", "replace")[:2000]}
        return resp.status, data
    finally:
        conn.close()


def _backup_unreachable(exc):
    return jsonify({
        "success": False,
        "error": f"Backup service unreachable at {BACKUP_API_URL}: {exc}"
    }), 502


@app.route("/api/backups")
@require_openelis_maintenance
def api_backups_list():
    try:
        status, data = _backup_request("GET", "/backups")
    except Exception as e:
        return _backup_unreachable(e)
    return jsonify(data), status


@app.route("/api/backup/status")
@require_openelis_maintenance
def api_backup_status():
    try:
        status, data = _backup_request("GET", "/status")
    except Exception as e:
        return _backup_unreachable(e)
    return jsonify(data), status


@app.route("/api/restore", methods=["POST"])
@require_openelis_maintenance
def api_backup_restore():
    payload = request.get_json(silent=True) or {}
    archive = os.path.basename(str(payload.get("archive", "")).strip())
    if not archive or not (archive.endswith(".tar.gz") or archive.endswith(".tgz")):
        return jsonify({"success": False, "error": "Invalid backup archive name"}), 400
    try:
        # restore kicks off an async job on the backup service and returns fast
        status, data = _backup_request("POST", "/restore", body={"archive": archive}, timeout=15)
    except Exception as e:
        return _backup_unreachable(e)
    return jsonify(data), status


@app.route("/api/backup/upload", methods=["POST"])
@require_openelis_maintenance
def api_backup_upload():
    """Stream an uploaded archive through to the backup service (no buffering)."""
    filename = request.args.get("filename", "") or request.headers.get("X-File-Name", "")
    restore_now = (request.args.get("restore", "") or request.headers.get("X-Restore-Now", "")).lower() in ("1", "true", "yes")
    content_length = request.content_length or 0
    if content_length <= 0:
        return jsonify({"success": False, "error": "Content-Length header required for upload"}), 400

    # The backup service only lists/restores archives matching bahmni_*.tar.gz,
    # so normalise the name or the upload would be invisible (and unrestorable).
    filename = os.path.basename(filename.strip()) or f"bahmni_uploaded_backup_{int(time.time())}.tar.gz"
    if not filename.startswith("bahmni_"):
        filename = "bahmni_" + filename

    query = "?filename=" + quote(filename) + "&restore=" + ("true" if restore_now else "false")
    conn = http.client.HTTPConnection(BACKUP_API_HOST, BACKUP_API_PORT, timeout=3600)
    try:
        conn.putrequest("POST", BACKUP_API_BASE + "/upload" + query)
        conn.putheader("Content-Type", request.content_type or "application/gzip")
        conn.putheader("Content-Length", str(content_length))
        conn.putheader("X-Restore-Now", "true" if restore_now else "false")
        conn.endheaders()
        while True:
            chunk = request.stream.read(1 << 20)
            if not chunk:
                break
            conn.send(chunk)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {"success": False, "raw": raw.decode("utf-8", "replace")[:2000]}
        return jsonify(data), resp.status
    except Exception as e:
        return jsonify({"success": False, "error": f"Upload failed: {e}"}), 502
    finally:
        conn.close()


@app.route("/api/backups/download/<path:name>")
@require_openelis_maintenance
def api_backup_download(name):
    safe_name = os.path.basename(name.strip())
    if not safe_name or not safe_name.endswith(".tar.gz"):
        return jsonify({"error": "Invalid backup archive filename"}), 400
    try:
        conn = http.client.HTTPConnection(BACKUP_API_HOST, BACKUP_API_PORT, timeout=120)
        conn.request("GET", BACKUP_API_BASE + "/download/" + quote(safe_name))
        resp = conn.getresponse()
        if resp.status != 200:
            raw = resp.read()
            conn.close()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = {"error": raw.decode("utf-8", "replace")[:500]}
            return jsonify(data), resp.status
        headers = {}
        for h in ("Content-Type", "Content-Disposition", "Content-Length"):
            value = resp.getheader(h)
            if value:
                headers[h] = value

        def generate():
            try:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                conn.close()

        return Response(generate(), status=200, headers=headers)
    except Exception as e:
        return jsonify({"error": f"Download failed: {e}"}), 502


# ---------------------------------------------------------------------------
# Native Windows File / Folder Picker  (for the path inputs on tools 2/4/5)
# ---------------------------------------------------------------------------
# Tkinter is single-threaded, so every dialog is served by ONE dedicated
# worker thread. Flask request threads just hand a job over and wait for
# the result. This returns REAL absolute host paths (unlike
# <input type="file">, which browsers give fake paths for).
_dialog_jobs = queue.Queue()
_dialog_thread = None
_dialog_thread_lock = threading.Lock()


def _start_dialog_worker():
    global _dialog_thread
    with _dialog_thread_lock:
        if _dialog_thread is not None and _dialog_thread.is_alive():
            return

        def dialog_worker():
            while True:
                kind, title, filetypes, initialdir, result_q = _dialog_jobs.get()
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()
                    try:
                        root.attributes("-topmost", True)
                    except Exception:
                        pass
                    root.update()
                    try:
                        if kind == "dir":
                            path = filedialog.askdirectory(
                                parent=root, mustexist=True,
                                title=title or "Select folder",
                                initialdir=initialdir or None)
                        else:
                            path = filedialog.askopenfilename(
                                parent=root,
                                title=title or "Select file",
                                initialdir=initialdir or None,
                                filetypes=[tuple(x) for x in filetypes] if filetypes
                                          else [("All files", "*.*")])
                    finally:
                        root.destroy()
                    result_q.put(("ok", path or ""))
                except Exception as exc:
                    result_q.put(("error", str(exc)))

        _dialog_thread = threading.Thread(
            target=dialog_worker, daemon=True, name="path-picker-dialogs")
        _dialog_thread.start()


@app.route("/api/browse", methods=["POST"])
@require_openelis_maintenance
def api_browse():
    """Open a native Windows file/folder dialog and return the absolute path."""
    data = request.json or {}
    kind = "dir" if str(data.get("type", "file")) == "dir" else "file"
    title = str(data.get("title", ""))[:100]
    filetypes = data.get("filetypes") or []

    # Start browsing where the current value (or the user's home) lives.
    current = str(data.get("current", "")).strip()
    initialdir = os.path.expanduser("~")
    if current:
        candidate = current if kind == "dir" else os.path.dirname(current)
        if candidate and os.path.isdir(candidate):
            initialdir = candidate

    _start_dialog_worker()
    result_q = queue.Queue()
    _dialog_jobs.put((kind, title, filetypes, initialdir, result_q))
    try:
        status, payload = result_q.get(timeout=1800)  # dialog may stay open a while
    except queue.Empty:
        return jsonify({"error": "No selection made (dialog timed out)."}), 504
    if status == "error":
        return jsonify({"error": f"Could not open the {kind} picker: {payload}"}), 500
    if not payload:
        return jsonify({"path": "", "cancelled": True})
    return jsonify({"path": payload})


# ---------------------------------------------------------------------------
# In-page file browser + drag & drop upload  (path inputs on tools 2 / 4 / 5)
# ---------------------------------------------------------------------------
# Browsers never expose the real disk path of a dragged file, so a drop is
# handled by copying the item into portal_uploads/ and handing that absolute
# path back to the input. Clicking "Browse" walks the host filesystem instead.
UPLOAD_ROOT = os.path.join(BASE_DIR, "portal_uploads")
UPLOAD_CHUNK = 1 << 20          # 1 MB streamed writes (backups can be huge)
UPLOAD_KEEP_DAYS = 7


def _fs_existing(path):
    """Expand ~ and $vars, absolutise, and return the path only if it exists."""
    if not path:
        return ""
    path = str(path).strip().strip('"')
    if not path:
        return ""
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    return path if os.path.exists(path) else ""


def _fs_drives():
    if os.name == "nt":
        import string
        return [f"{letter}:\\" for letter in string.ascii_uppercase
                if os.path.exists(f"{letter}:\\")]
    return ["/"]


def _fs_safe_parts(raw):
    """Turn a browser-supplied relative path into safe, relative components."""
    parts = []
    for part in str(raw or "").replace("\\", "/").split("/"):
        part = part.strip()
        # drop empty, ".", ".." and drive-letter segments (e.g. "C:")
        if not part or part in (".", "..") or (len(part) == 2 and part[1] == ":"):
            continue
        parts.append(part)
    return parts


def _fs_prune_uploads():
    """Best-effort cleanup so repeated drops cannot fill the disk."""
    try:
        cutoff = time.time() - UPLOAD_KEEP_DAYS * 86400
        for entry in os.scandir(UPLOAD_ROOT):
            if entry.is_dir(follow_symlinks=False) and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry.path, ignore_errors=True)
    except Exception:
        pass


@app.route("/api/fs/list")
@require_openelis_maintenance
def api_fs_list():
    """List a host directory so the picker modal can navigate by clicking."""
    raw = (request.args.get("path") or "").strip()
    if not raw:
        # Nothing yet -> offer the removable/fixed drives as the entry point.
        return jsonify({
            "path": "", "parent": "", "drives": _fs_drives(), "entries": [],
            "home": os.path.expanduser("~"), "uploads": UPLOAD_ROOT
        })

    path = _fs_existing(raw)
    if not path:
        return jsonify({"error": f"Path not found on this machine: {raw}"}), 404
    if not os.path.isdir(path):
        path = os.path.dirname(path)

    entries = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                    stat = entry.stat()
                    size, mtime = stat.st_size, stat.st_mtime
                except OSError:
                    is_dir, size, mtime = False, 0, 0
                entries.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": is_dir,
                    "size": size,
                    "mtime": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""
                })
    except PermissionError:
        return jsonify({"error": f"Access denied: {path}"}), 403
    except OSError as exc:
        return jsonify({"error": f"Cannot read {path}: {exc}"}), 400

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    parent = os.path.dirname(path)
    if parent == path:                 # filesystem root or drive root
        parent = ""
    return jsonify({
        "path": path, "parent": parent, "drives": [], "entries": entries,
        "home": os.path.expanduser("~"), "uploads": UPLOAD_ROOT
    })


@app.route("/api/fs/upload", methods=["POST"])
@require_openelis_maintenance
def api_fs_upload():
    """Stream one dropped file into portal_uploads/<batch>/<root>/<relpath>."""
    batch = re.sub(r"[^A-Za-z0-9_-]", "", str(request.form.get("batch", "")))[:40]
    if not batch:
        batch = uuid.uuid4().hex[:12]

    root_parts = _fs_safe_parts(request.form.get("root_name", ""))
    root_name = root_parts[-1] if root_parts else ""
    rel_parts = _fs_safe_parts(request.form.get("relpath", ""))
    if root_name and rel_parts and rel_parts[0] == root_name:
        rel_parts = rel_parts[1:]      # root folder already lives in batch_dir

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "No file was received."}), 400

    # Never trust the browser's filename: keep the basename only.
    safe_name = os.path.basename(str(upload.filename).replace("\\", "/").strip())
    if not safe_name:
        safe_name = "dropped_file"
    if rel_parts:
        rel_parts[-1] = safe_name
    else:
        rel_parts = [safe_name]

    batch_dir = os.path.join(UPLOAD_ROOT, batch, root_name) if root_name \
        else os.path.join(UPLOAD_ROOT, batch)
    target = os.path.join(batch_dir, *rel_parts)

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as out:
            while True:
                chunk = upload.stream.read(UPLOAD_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
    except OSError as exc:
        return jsonify({"error": f"Could not save the dropped file: {exc}"}), 500

    _fs_prune_uploads()

    root_path = os.path.join(UPLOAD_ROOT, batch, root_name) if root_name \
        else os.path.dirname(target)
    return jsonify({
        "path": target,
        "root": root_path,
        "bytes": os.path.getsize(target)
    })


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
    /* ---- Path inputs (tools 2 / 4 / 5): click-to-pick + drag & drop ---- */
    .path-zone {
      position: relative;
      border-radius: 10px;
      transition: all 0.15s ease;
    }
    .path-zone.dragging {
      background: #e7f1ff;
      border: 1.5px dashed #0b5ed7;
      padding: 8px;
      box-shadow: inset 0 0 0 1px rgba(11, 94, 215, 0.15);
    }
    .path-drop {
      margin-top: 6px;
      font-size: 0.78rem;
      color: #64748b;
    }
    .path-zone.dragging .path-drop {
      color: #0b5ed7;
      font-weight: 600;
    }
    .path-status {
      min-height: 1.1em;
      font-size: 0.76rem;
      word-break: break-all;
    }
    /* ---- In-page file browser modal ---- */
    .fs-crumb {
      display: flex;
      flex-wrap: wrap;
      gap: 2px;
      font-size: 0.78rem;
      margin-bottom: 6px;
    }
    .fs-crumb button {
      border: none;
      background: #f1f5f9;
      border-radius: 5px;
      padding: 2px 7px;
      color: #0b5ed7;
      font-size: 0.76rem;
    }
    .fs-crumb button:hover { background: #e2e8f0; }
    .fs-list {
      max-height: 44vh;
      min-height: 180px;
      overflow-y: auto;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      background: #fff;
    }
    .fs-row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 5px 10px;
      border-bottom: 1px solid #f1f5f9;
      cursor: pointer;
      font-size: 0.85rem;
    }
    .fs-row:last-child { border-bottom: none; }
    .fs-row:hover { background: #f8fafc; }
    .fs-row.selected { background: #e7f1ff; }
    .fs-row .fs-name {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .fs-row .fs-meta {
      color: #94a3b8;
      font-size: 0.72rem;
      white-space: nowrap;
    }
    .fs-empty {
      padding: 28px 12px;
      text-align: center;
      color: #94a3b8;
      font-size: 0.85rem;
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
                  Wipes test/clinical patient data from OpenMRS, OpenELIS, PACS (dcm4chee) & Odoo, deletes non-essential user accounts (keeps admin, superman and service accounts), resets primary identifier global properties, configures the starting Auto-MRN sequence, and reapplies UI bugfix patches. Full Reset also performs a deep Odoo business wipe (sale orders, invoices, payments, purchases, stock movements, customer/vendor partners). Selective mode (choice 2) is MRN-scoped in OpenMRS & Odoo only.
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
                  <div class="path-zone" id="zone-excelFilePath">
                    <div class="input-group input-group-sm">
                      <span class="input-group-text"><i class="fa-solid fa-file-excel text-success"></i></span>
                      <input type="text" id="excelFilePath" class="form-control form-control-sm" data-kind="file" data-title="Select KPHC Excel patient file" data-filetypes="Excel Files (*.xlsx);Excel 97-2003 (*.xls);All Files (*.*)" value="/home/kphcs/Documents/KPHCsmartcarePT.xlsx">
                      <button type="button" class="btn btn-outline-primary" title="Browse the server filesystem" onclick="browsePath('excelFilePath')"><i class="fa-solid fa-folder-open me-1"></i>Browse</button>
                      <button type="button" class="btn btn-outline-secondary" title="Clear" onclick="clearPath('excelFilePath')"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="path-drop"><i class="fa-solid fa-hand-pointer me-1"></i>Click <b>Browse</b> to navigate the server and pick the file, or <b>drag &amp; drop</b> it here from File&nbsp;Explorer (it is copied into <code>portal_uploads</code>).</div>
                    <div class="path-status" id="status-excelFilePath"></div>
                  </div>
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
                  <div class="path-zone" id="zone-pdfBackupPath">
                    <div class="input-group input-group-sm">
                      <span class="input-group-text"><i class="fa-solid fa-file-zipper text-danger"></i></span>
                      <input type="text" id="pdfBackupPath" class="form-control form-control-sm" data-kind="file" data-title="Select source SQL backup archive" data-filetypes="SQL Archives (*.sql.gz,*.gz,*.sql);Compressed (*.zip,*.7z,*.rar);All Files (*.*)" value="/opt/emr/CentOS Bahmni backups/openmrs20261002_160501.sql.gz">
                      <button type="button" class="btn btn-outline-primary" title="Browse the server filesystem" onclick="browsePath('pdfBackupPath')"><i class="fa-solid fa-folder-open me-1"></i>Browse</button>
                      <button type="button" class="btn btn-outline-secondary" title="Clear" onclick="clearPath('pdfBackupPath')"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="path-drop"><i class="fa-solid fa-hand-pointer me-1"></i>Click <b>Browse</b> to pick the backup on the server, or <b>drag &amp; drop</b> the archive here (copied into <code>portal_uploads</code>).</div>
                    <div class="path-status" id="status-pdfBackupPath"></div>
                  </div>
                </div>
                <div class="mb-3">
                  <label class="form-label fw-semibold small">PDF Output Directory</label>
                  <div class="path-zone" id="zone-pdfOutputDir">
                    <div class="input-group input-group-sm">
                      <span class="input-group-text"><i class="fa-solid fa-folder-tree text-danger"></i></span>
                      <input type="text" id="pdfOutputDir" class="form-control form-control-sm" data-kind="dir" data-title="Select PDF output folder" value="/opt/emr/backups/patient_summary_pdfs">
                      <button type="button" class="btn btn-outline-primary" title="Browse the server filesystem" onclick="browsePath('pdfOutputDir')"><i class="fa-solid fa-folder-open me-1"></i>Browse</button>
                      <button type="button" class="btn btn-outline-secondary" title="Clear" onclick="clearPath('pdfOutputDir')"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="path-drop"><i class="fa-solid fa-hand-pointer me-1"></i>Click <b>Browse</b>, enter a folder and press <b>Select this folder</b>, or <b>drag &amp; drop</b> a folder here (copied into <code>portal_uploads</code>).</div>
                    <div class="path-status" id="status-pdfOutputDir"></div>
                  </div>
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
                  <div class="path-zone" id="zone-attachPdfDir">
                    <div class="input-group input-group-sm">
                      <span class="input-group-text"><i class="fa-solid fa-folder-open text-secondary"></i></span>
                      <input type="text" id="attachPdfDir" class="form-control form-control-sm" data-kind="dir" data-title="Select folder of generated PDFs" value="/opt/emr/backups/patient_summary_pdfs">
                      <button type="button" class="btn btn-outline-primary" title="Browse the server filesystem" onclick="browsePath('attachPdfDir')"><i class="fa-solid fa-folder-open me-1"></i>Browse</button>
                      <button type="button" class="btn btn-outline-secondary" title="Clear" onclick="clearPath('attachPdfDir')"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="path-drop"><i class="fa-solid fa-hand-pointer me-1"></i>Click <b>Browse</b> and hit <b>Select this folder</b>, or <b>drag &amp; drop</b> the folder of PDFs here (copied into <code>portal_uploads</code>).</div>
                    <div class="path-status" id="status-attachPdfDir"></div>
                  </div>
                </div>
                <button class="btn btn-secondary btn-action" onclick="executeAttachDocs()">
                  <i class="fa-solid fa-link me-1"></i> Attach Documents to Bahmni
                </button>
              </div>
            </div>
          </div>

          <!-- 6. Backup & Restore -->
          <div class="accordion-item card mb-3">
            <h2 class="accordion-header" id="headingBackup">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseBackup">
                <i class="fa-solid fa-database text-warning me-2"></i>
                <span class="fw-bold me-2">6. Backup &amp; Restore</span>
                <span class="badge bg-warning-subtle text-warning border border-warning-subtle ms-auto me-3">bahmni_backup_service</span>
              </button>
            </h2>
            <div id="collapseBackup" class="accordion-collapse collapse" data-bs-parent="#toolsAccordion">
              <div class="accordion-body">
                <p class="text-muted small">
                  Lists the system backup archives, lets you download them, upload an archive from your computer, and restore the system from an archive. Restoring replaces the current databases and volumes, then restarts the application containers &mdash; a typed confirmation is required.
                </p>

                <div class="d-flex gap-2 mb-3">
                  <button class="btn btn-sm btn-outline-primary" onclick="loadBackups()"><i class="fa-solid fa-rotate me-1"></i> Refresh list</button>
                  <span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle align-self-center" id="backupStatusBadge">Idle</span>
                </div>

                <div class="table-responsive mb-3">
                  <table class="table table-sm table-hover align-middle mb-0" id="backupTable">
                    <thead class="table-light">
                      <tr>
                        <th>Archive</th>
                        <th>Type</th>
                        <th>Created</th>
                        <th class="text-end">Size</th>
                        <th class="text-end">Actions</th>
                      </tr>
                    </thead>
                    <tbody id="backupRows">
                      <tr><td colspan="5" class="text-muted small">Loading ...</td></tr>
                    </tbody>
                  </table>
                </div>

                <div class="mb-2">
                  <label class="form-label fw-semibold small">Upload a backup archive (.tar.gz)</label>
                  <input type="file" class="form-control form-control-sm" id="backupFileInput" accept=".gz,.tgz">
                  <div class="form-check mt-2">
                    <input class="form-check-input" type="checkbox" id="backupRestoreNow">
                    <label class="form-check-label small" for="backupRestoreNow">Restore immediately after upload</label>
                  </div>
                  <button class="btn btn-warning btn-sm mt-2" onclick="uploadBackup()" id="btnUploadBackup"><i class="fa-solid fa-upload me-1"></i> Upload archive</button>
                  <div class="progress mt-2" id="backupUploadProgress" style="display: none; height: 18px;">
                    <div class="progress-bar progress-bar-striped progress-bar-animated" id="backupUploadBar" role="progressbar" style="width: 0%">0%</div>
                  </div>
                </div>

                <div class="alert alert-warning py-2 small mb-0">
                  <i class="fa-solid fa-triangle-exclamation me-1"></i> A restore overwrites all current clinical data. Keep a fresh backup of the live system before restoring.
                </div>
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

  <!-- Reusable in-page file / folder picker (used by tools 2, 4 and 5) -->
  <div class="modal fade" id="pathPickerModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-lg modal-dialog-scrollable">
      <div class="modal-content">
        <div class="modal-header py-2">
          <h5 class="modal-title fw-bold" id="pathPickerTitle"><i class="fa-solid fa-folder-tree me-2"></i>Select location</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body p-3">
          <div class="d-flex gap-1 mb-2 flex-wrap">
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="fsNavigate('')"><i class="fa-solid fa-compact-disc me-1"></i>Drives</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="fsHome()"><i class="fa-solid fa-house me-1"></i>Home</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="fsUploads()"><i class="fa-solid fa-box-archive me-1"></i>Uploads</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="fsUp()"><i class="fa-solid fa-arrow-up me-1"></i>Up</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="fsNavigate(fsPath)"><i class="fa-solid fa-rotate-right me-1"></i>Refresh</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="browseNative()" title="Fall back to the native Windows picker"><i class="fa-solid fa-window-restore me-1"></i>Windows dialog</button>
          </div>
          <div class="fs-crumb" id="fsCrumb"></div>
          <div class="input-group input-group-sm mb-2">
            <span class="input-group-text"><i class="fa-solid fa-route"></i></span>
            <input type="text" id="fsPathBox" class="form-control form-control-sm" placeholder="Type or paste a path, then press Enter" onkeydown="if(event.key==='Enter'){event.preventDefault();fsNavigate(this.value);}">
            <button type="button" class="btn btn-outline-primary" onclick="fsNavigate(document.getElementById('fsPathBox').value)">Go</button>
          </div>
          <div class="input-group input-group-sm mb-2" id="fsFilterWrap" style="display: none;">
            <span class="input-group-text">Show</span>
            <select id="fsFilter" class="form-select form-select-sm" onchange="fsFilterIdx = parseInt(this.value, 10) || 0; fsRender();"></select>
          </div>
          <div class="fs-list" id="fsList"></div>
          <div class="form-text small" id="fsStatus"></div>
        </div>
        <div class="modal-footer py-2">
          <div class="input-group input-group-sm" style="flex: 1 1 auto;">
            <span class="input-group-text"><i class="fa-solid fa-location-dot"></i></span>
            <input type="text" id="fsSelected" class="form-control form-control-sm" placeholder="Selected path (you can also type it here)">
          </div>
          <button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
          <button type="button" class="btn btn-sm btn-primary" id="fsConfirmBtn" onclick="fsConfirm()"><i class="fa-solid fa-check me-1"></i>Select</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Restore confirmation (typed) -->
  <div class="modal fade" id="restoreModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header py-2 bg-danger text-white">
          <h5 class="modal-title fw-bold"><i class="fa-solid fa-triangle-exclamation me-2"></i>Confirm System Restore</h5>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body p-3">
          <p class="small mb-2">You are about to restore the entire system from:</p>
          <p class="fw-bold small bg-light border rounded p-2 mb-3" id="restoreArchiveName"></p>
          <ul class="small text-danger ps-3 mb-3">
            <li>All current clinical data will be replaced.</li>
            <li>Application containers will be restarted.</li>
            <li>This cannot be undone.</li>
          </ul>
          <label class="form-label fw-semibold small text-danger">Safety Confirmation (Type "RESTORE")</label>
          <input type="text" class="form-control form-control-sm" id="restoreConfirmInput" placeholder="Type RESTORE to confirm" oninput="document.getElementById('btnConfirmRestore').disabled = this.value.trim() !== 'RESTORE';">
        </div>
        <div class="modal-footer py-2">
          <button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
          <button type="button" class="btn btn-sm btn-danger" id="btnConfirmRestore" disabled onclick="executeRestore()"><i class="fa-solid fa-database me-1"></i> Restore now</button>
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

    // ------------------------------------------------------------------
    // Path inputs (tools 2 / 4 / 5): in-page file browser + drag & drop
    // ------------------------------------------------------------------
    const FS_BS = String.fromCharCode(92);   // backslash, kept out of literals
    let fsInput = null, fsKind = 'file', fsTitle = 'Select location';
    let fsPath = '', fsParent = '', fsDrives = [], fsEntries = [];
    let fsFilters = [], fsFilterIdx = 0, fsSelected = '';
    let fsHomePath = '', fsUploadsPath = '', fsModal = null;

    function fsEsc(s) {
      return String(s == null ? '' : s)
        .split('&').join('&amp;')
        .split('<').join('&lt;')
        .split('>').join('&gt;')
        .split('"').join('&quot;');
    }

    function fsNorm(p) { return String(p || '').split(FS_BS).join('/'); }

    function fsDirOf(p) {
      const n = fsNorm(p);
      const i = n.lastIndexOf('/');
      if (i < 0) return '';
      let d = n.slice(0, i);
      // "C:" alone is drive-relative on Windows - keep the trailing slash
      if (/^[A-Za-z]:$/.test(d)) d += '/';
      if (d === '' && n.charAt(0) === '/') d = '/';
      return d;
    }

    function fsBaseOf(p) {
      const n = fsNorm(p).replace(/\\/+$/, '');
      return n.slice(n.lastIndexOf('/') + 1);
    }

    function fsSize(bytes) {
      const b = Number(bytes) || 0;
      if (b < 1024) return b + ' B';
      if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
      if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
      return (b / 1073741824).toFixed(2) + ' GB';
    }

    function fsParseFiletypes(spec) {
      const out = [];
      String(spec || '').split(';').forEach(part => {
        part = part.trim();
        if (!part) return;
        const m = part.match(/^(.*)\\((.*)\\)$/);
        const label = (m ? m[1] : part).trim();
        const pattern = m ? m[2] : '*.*';
        const exts = [];
        let all = false;
        pattern.split(',').forEach(p => {
          p = p.trim().toLowerCase();
          if (p === '*.*' || p === '*') all = true;
          else if (p.indexOf('*.') === 0) exts.push(p.slice(1));
        });
        out.push({label: label || part, exts: exts, all: all || exts.length === 0});
      });
      if (!out.length) out.push({label: 'All files', exts: [], all: true});
      return out;
    }

    function fsMatches(name) {
      const f = fsFilters[fsFilterIdx] || {all: true, exts: []};
      if (f.all) return true;
      const lower = String(name).toLowerCase();
      return f.exts.some(e => lower.slice(-e.length) === e);
    }

    function setPathStatus(inputId, msg, level) {
      const el = document.getElementById('status-' + inputId);
      if (!el) return;
      if (!msg) { el.innerHTML = ''; return; }
      const cls = level === 'error' ? 'text-danger' : (level === 'success' ? 'text-success' : 'text-info');
      const icon = level === 'error' ? 'fa-triangle-exclamation'
                 : (level === 'success' ? 'fa-circle-check' : 'fa-circle-info');
      el.className = 'path-status mt-1 ' + cls;
      el.innerHTML = '<i class="fa-solid ' + icon + ' me-1"></i>' + fsEsc(msg);
    }

    function clearPath(inputId) {
      const el = document.getElementById(inputId);
      if (el) el.value = '';
      setPathStatus(inputId, '', '');
    }

    // --- picker modal --------------------------------------------------
    function browsePath(inputId) { openPathPicker(inputId); }

    function openPathPicker(inputId) {
      const el = document.getElementById(inputId);
      if (!el) return;

      fsInput = el;
      fsKind = el.dataset.kind === 'dir' ? 'dir' : 'file';
      fsTitle = el.dataset.title || 'Select location';
      fsFilters = fsParseFiletypes(el.dataset.filetypes || '');
      fsFilterIdx = 0;
      fsPath = ''; fsParent = ''; fsDrives = []; fsEntries = []; fsSelected = '';

      document.getElementById('pathPickerTitle').innerHTML =
        '<i class="fa-solid ' + (fsKind === 'dir' ? 'fa-folder-tree' : 'fa-file-arrow-up') + ' me-2"></i>' + fsEsc(fsTitle);
      document.getElementById('fsFilter').innerHTML =
        fsFilters.map((f, i) => '<option value="' + i + '">' + fsEsc(f.label) + '</option>').join('');
      document.getElementById('fsFilterWrap').style.display =
        (fsKind === 'file' && fsFilters.length > 1) ? 'flex' : 'none';
      document.getElementById('fsConfirmBtn').innerHTML = fsKind === 'dir'
        ? '<i class="fa-solid fa-folder-open me-1"></i>Select this folder'
        : '<i class="fa-solid fa-check me-1"></i>Select file';
      document.getElementById('fsSelected').value = '';
      document.getElementById('fsStatus').textContent = '';
      document.getElementById('fsCrumb').innerHTML = '';
      document.getElementById('fsList').innerHTML =
        '<div class="fs-empty"><i class="fa-solid fa-spinner fa-spin me-1"></i>Loading...</div>';

      if (!fsModal) fsModal = new bootstrap.Modal(document.getElementById('pathPickerModal'));
      fsModal.show();

      // Start where the input already points (dir for folders, parent for files)
      const cur = (el.value || '').trim();
      let start = '';
      if (cur) {
        if (fsKind === 'dir') start = cur;
        else start = fsBaseOf(cur).indexOf('.') >= 0 ? fsDirOf(cur) : cur;
      }
      fsNavigate(start);
    }

    async function fsNavigate(path) {
      const status = document.getElementById('fsStatus');
      status.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i>Loading ' + fsEsc(path || 'drives') + ' ...';
      try {
        const resp = await fetch('/api/fs/list?path=' + encodeURIComponent(path || ''));
        const data = await resp.json();
        if (!resp.ok) {
          if (fsKind === 'dir' && path) {
            // Folder may not exist yet (e.g. an output dir the script creates)
            fsPath = path; fsParent = ''; fsDrives = []; fsEntries = []; fsSelected = path;
            fsRender();
            status.innerHTML = '<span class="text-danger">' + fsEsc(data.error || 'Not found') + '</span>' +
              ' <span class="text-muted">- you can still select it if the script will create it.</span>';
          } else {
            status.innerHTML = '<span class="text-danger">' + fsEsc(data.error || 'Cannot list that folder') + '</span>';
          }
          return;
        }
        if (data.home) fsHomePath = data.home;
        if (data.uploads) fsUploadsPath = data.uploads;
        fsPath = data.path || '';
        fsParent = data.parent || '';
        fsDrives = data.drives || [];
        fsEntries = data.entries || [];
        fsSelected = fsKind === 'dir' ? fsPath : '';
        fsRender();
        status.innerHTML = fsEntries.length
          ? fsEsc(fsEntries.length + ' item(s)')
          : '<span class="text-muted">This folder is empty.</span>';
      } catch (err) {
        status.innerHTML = '<span class="text-danger">Lookup failed: ' + fsEsc(err.message) + '</span>';
      }
    }

    function fsHome() { fsNavigate(fsHomePath || ''); }
    function fsUploads() { fsNavigate(fsUploadsPath || ''); }
    function fsUp() { fsNavigate(fsParent || ''); }

    function fsRender() {
      // breadcrumb
      const crumb = document.getElementById('fsCrumb');
      if (!fsPath) {
        crumb.innerHTML = '<span class="text-muted">This machine &mdash; pick a drive</span>';
      } else {
        const n = fsNorm(fsPath);
        const segs = n.split('/').filter(s => s !== '');
        let built = n.charAt(0) === '/' ? '/' : '';
        let html = '<button type="button" data-p="" title="All drives"><i class="fa-solid fa-hard-drive"></i></button>';
        segs.forEach((seg, idx) => {
          built = built === '/' ? '/' + seg : (built ? built + '/' + seg : seg);
          const last = idx === segs.length - 1;
          html += '<span class="px-1 text-muted">/</span>' +
            (last
              ? '<button type="button" disabled class="fw-semibold">' + fsEsc(seg) + '</button>'
              : '<button type="button" data-p="' + fsEsc(built) + '">' + fsEsc(seg) + '</button>');
        });
        crumb.innerHTML = html;
      }

      // selection box: folders always reflect the folder being viewed
      if (fsKind === 'dir') {
        fsSelected = fsPath;
        document.getElementById('fsSelected').value = fsPath;
      } else if (fsSelected) {
        document.getElementById('fsSelected').value = fsSelected;
      }

      // list
      let rows = '';
      if (fsDrives.length) {
        fsDrives.forEach(d => {
          rows += '<div class="fs-row" data-path="' + fsEsc(d) + '" data-dir="1" title="' + fsEsc(d) + '">' +
            '<i class="fa-solid fa-hard-drive text-primary me-2"></i>' +
            '<span class="fs-name">' + fsEsc(d) + '</span>' +
            '<span class="fs-meta">drive</span></div>';
        });
      } else {
        if (fsParent) {
          rows += '<div class="fs-row" data-path="' + fsEsc(fsParent) + '" data-dir="1">' +
            '<i class="fa-solid fa-arrow-up text-secondary me-2"></i>' +
            '<span class="fs-name fst-italic">.. (up one level)</span></div>';
        }
        fsEntries.forEach(e => {
          if (e.is_dir) {
            rows += '<div class="fs-row" data-path="' + fsEsc(e.path) + '" data-dir="1" title="' + fsEsc(e.path) + '">' +
              '<i class="fa-solid fa-folder text-warning me-2"></i>' +
              '<span class="fs-name">' + fsEsc(e.name) + '</span>' +
              '<span class="fs-meta">' + fsEsc(e.mtime || '') + '</span></div>';
          } else if (fsMatches(e.name)) {
            rows += '<div class="fs-row" data-path="' + fsEsc(e.path) + '" data-dir="0" title="' + fsEsc(e.path) + '">' +
              '<i class="fa-regular fa-file-lines text-secondary me-2"></i>' +
              '<span class="fs-name">' + fsEsc(e.name) + '</span>' +
              '<span class="fs-meta">' + fsSize(e.size) + ' &middot; ' + fsEsc(e.mtime || '') + '</span></div>';
          }
        });
      }
      document.getElementById('fsList').innerHTML = rows ||
        '<div class="fs-empty"><i class="fa-regular fa-folder-open mb-2 d-block" style="font-size:2rem;"></i>' +
        (fsKind === 'file' ? 'No files match this filter in this folder.' : 'This folder is empty.') + '</div>';
    }

    function fsPickRow(row) {
      const path = row.dataset.path;
      const isDir = row.dataset.dir === '1';
      if (isDir) { fsNavigate(path); return; }
      fsSelected = path;
      document.querySelectorAll('#fsList .fs-row').forEach(r => {
        r.classList.toggle('selected', r.dataset.path === path);
      });
      document.getElementById('fsSelected').value = path;
      document.getElementById('fsStatus').innerHTML = '<i class="fa-solid fa-circle-check text-success me-1"></i>' + fsEsc(path);
    }

    function fsConfirm() {
      if (!fsInput) return;
      const typed = document.getElementById('fsSelected').value.trim();
      const chosen = typed || fsSelected || (fsKind === 'dir' ? fsPath : '');
      if (!chosen) {
        alert('Pick a ' + (fsKind === 'dir' ? 'folder' : 'file') + ' first.');
        return;
      }
      if (fsKind === 'file' && !fsMatches(fsBaseOf(chosen))) {
        const label = (fsFilters[fsFilterIdx] || {label: 'the current filter'}).label;
        if (!confirm('"' + fsBaseOf(chosen) + '" does not match "' + label + '". Select it anyway?')) return;
      }
      fsInput.value = chosen;
      fsModal.hide();
      setPathStatus(fsInput.id, (fsKind === 'dir' ? 'Folder' : 'File') + ' selected: ' + chosen, 'success');
    }

    // Fallback: the native Windows picker served by /api/browse
    async function browseNative() {
      if (!fsInput) return;
      const status = document.getElementById('fsStatus');
      status.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i>Waiting for the Windows dialog on the server ...';
      try {
        const resp = await fetch('/api/browse', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            type: fsKind,
            title: fsTitle,
            current: (fsInput.value || '').trim(),
            filetypes: fsFilters.map(f => [
              f.label,
              f.all ? '*.*' : f.exts.map(e => '*' + e).join(';')
            ])
          })
        });
        const data = await resp.json();
        if (!resp.ok) {
          status.innerHTML = '<span class="text-danger">' + fsEsc(data.error || 'Picker failed') + '</span>';
          return;
        }
        if (data.cancelled || !data.path) { status.textContent = ''; fsRender(); return; }
        fsInput.value = data.path;
        fsModal.hide();
        setPathStatus(fsInput.id, (fsKind === 'dir' ? 'Folder' : 'File') + ' selected: ' + data.path, 'success');
      } catch (err) {
        status.innerHTML = '<span class="text-danger">' + fsEsc(err.message) + '</span>';
      }
    }

    // --- drag & drop ---------------------------------------------------
    function fsReadAll(reader) {
      return new Promise(resolve => {
        const out = [];
        const step = () => reader.readEntries(chunk => {
          if (!chunk || !chunk.length) { resolve(out); return; }
          chunk.forEach(c => out.push(c));
          step();
        }, () => resolve(out));
        step();
      });
    }

    async function fsCollect(nodes, prefix) {
      const out = [];
      for (const node of nodes) {
        const rel = prefix ? prefix + '/' + node.name : node.name;
        if (node.isFile) {
          try {
            const file = await new Promise((res, rej) => node.file(res, rej));
            if (file) out.push({file: file, rel: rel});
          } catch (err) { /* unreadable entry: skip it */ }
        } else if (node.isDirectory) {
          const kids = await fsReadAll(node.createReader());
          const sub = await fsCollect(kids, rel);
          sub.forEach(s => out.push(s));
        }
      }
      return out;
    }

    async function handlePathDrop(e, inputId) {
      e.preventDefault();
      e.stopPropagation();

      const input = document.getElementById(inputId);
      if (!input) return;
      const kind = input.dataset.kind === 'dir' ? 'dir' : 'file';
      const dt = e.dataTransfer;
      if (!dt) return;

      // Entry API keeps the relative structure (needed for folder drops)
      let dropped = [];
      try {
        const items = dt.items ? Array.from(dt.items) : [];
        const nodes = items.map(it => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null)).filter(Boolean);
        if (nodes.length) dropped = await fsCollect(nodes, '');
      } catch (err) { dropped = []; }
      if (!dropped.length && dt.files) {
        dropped = Array.from(dt.files).map(f => ({file: f, rel: f.name}));
      }
      if (!dropped.length) {
        setPathStatus(inputId, 'Nothing usable was dropped on the box.', 'error');
        return;
      }

      const folderDrop = dropped.some(d => d.rel.indexOf('/') >= 0);
      const tops = [];
      dropped.forEach(d => {
        const top = d.rel.split('/')[0];
        if (tops.indexOf(top) < 0) tops.push(top);
      });

      if (kind === 'file') {
        if (folderDrop || dropped.length > 1) {
          setPathStatus(inputId, 'This field takes a single file - drop one file, or use Browse.', 'error');
          return;
        }
      } else if (!folderDrop) {
        setPathStatus(inputId, 'This field takes a folder - drop a folder from File Explorer, or use Browse.', 'error');
        return;
      }

      const rootName = kind === 'dir' && tops.length === 1 ? tops[0] : '';
      const batch = 'b' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

      setPathStatus(inputId, 'Uploading 1/' + dropped.length + ' ...', 'info');
      let last = null;
      for (let i = 0; i < dropped.length; i++) {
        const item = dropped[i];
        const fd = new FormData();
        fd.append('batch', batch);
        fd.append('root_name', rootName);
        fd.append('relpath', item.rel);
        fd.append('file', item.file, item.file.name);

        let resp, data;
        try {
          resp = await fetch('/api/fs/upload', {method: 'POST', body: fd});
          data = await resp.json();
        } catch (err) {
          setPathStatus(inputId, 'Upload failed: ' + err.message, 'error');
          return;
        }
        if (!resp.ok) {
          setPathStatus(inputId, 'Upload failed: ' + (data.error || ('HTTP ' + resp.status)), 'error');
          return;
        }
        last = data;
        setPathStatus(inputId, 'Copying ' + (i + 1) + '/' + dropped.length + ' - ' +
          fsBaseOf(item.rel) + ' (' + fsSize(data.bytes) + ')', 'info');
      }
      if (!last) return;

      const finalPath = kind === 'dir' ? last.root : last.path;
      input.value = finalPath;
      setPathStatus(inputId, 'Copied into portal_uploads: ' + finalPath, 'success');
    }

    function initPathZones() {
      document.querySelectorAll('.path-zone').forEach(zone => {
        const input = zone.querySelector('input[type="text"]');
        if (!input || input.dataset.wired === '1') return;
        input.dataset.wired = '1';
        let depth = 0;
        zone.addEventListener('dragenter', e => {
          e.preventDefault();
          depth++;
          zone.classList.add('dragging');
        });
        zone.addEventListener('dragover', e => {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
        });
        zone.addEventListener('dragleave', () => {
          depth = Math.max(0, depth - 1);
          if (!depth) zone.classList.remove('dragging');
        });
        zone.addEventListener('drop', e => {
          depth = 0;
          zone.classList.remove('dragging');
          handlePathDrop(e, input.id);
        });
      });
    }

    async function triggerScript(scriptKey, payload) {
      if (isExecuting) {
        alert("A script is already currently running. Please wait for it to complete.");
        return;
      }
      if (typeof backupBusy !== 'undefined' && backupBusy) {
        alert("A backup/restore operation is running. Please wait for it to complete.");
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

    // Returns the path, "" to run with the script default, or null to abort
    function pathOrConfirm(inputId, label) {
      const val = (document.getElementById(inputId).value || '').trim();
      if (val) return val;
      if (confirm('No ' + label + ' selected. OK = run with the built-in default, Cancel = abort.')) return '';
      return null;
    }

    // 2. Excel Import Trigger
    function executeExcelImport() {
      const path = pathOrConfirm('excelFilePath', 'Excel file');
      if (path === null) return;
      triggerScript('import_kphc_excel_patients', {excel_path: path});
    }

    // 3. Profile Migration Trigger
    function executeProfileMigration() {
      if (!confirm("Execute patient profile migration from openmrs_legacy_stage into production openmrs?")) return;
      triggerScript('migrate_patient_profiles', {});
    }

    // 4. PDF Pipeline Trigger
    function executePdfPipeline() {
      const backup = pathOrConfirm('pdfBackupPath', 'SQL backup archive');
      if (backup === null) return;
      const outDir = pathOrConfirm('pdfOutputDir', 'PDF output directory');
      if (outDir === null) return;
      triggerScript('interactive_pdf_pipeline', {backup_file: backup, pdf_out_dir: outDir});
    }

    // 5. Attach Documents Trigger
    function executeAttachDocs() {
      const pdfDir = pathOrConfirm('attachPdfDir', 'PDF directory');
      if (pdfDir === null) return;
      triggerScript('attach_patient_documents', {pdf_dir: pdfDir});
    }

    // 6. Backup & Restore (proxied to the backup service)
    let backupBusy = false;
    let backupPollInterval = null;
    let backupLogOffset = 0;

    function backupEsc(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    }

    function updateBackupBadge(st) {
      const badge = document.getElementById('backupStatusBadge');
      if (!st) { badge.className = 'badge bg-secondary-subtle text-secondary border border-secondary-subtle'; badge.textContent = 'Idle'; return; }
      if (st.status === 'running') {
        badge.className = 'badge bg-warning text-dark';
        badge.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i> ' + backupEsc(st.type || 'working') + ' ' + (st.progress || 0) + '%';
      } else if (st.status === 'completed') {
        badge.className = 'badge bg-success';
        badge.textContent = 'Last op: completed';
      } else if (st.status === 'error') {
        badge.className = 'badge bg-danger';
        badge.textContent = 'Last op: failed';
      } else {
        badge.className = 'badge bg-secondary-subtle text-secondary border border-secondary-subtle';
        badge.textContent = 'Idle';
      }
    }

    async function loadBackups() {
      const body = document.getElementById('backupRows');
      body.innerHTML = '<tr><td colspan="5" class="text-muted small">Loading ...</td></tr>';
      try {
        const resp = await fetch('/api/backups');
        const data = await resp.json();
        if (!resp.ok) {
          body.innerHTML = '<tr><td colspan="5" class="text-danger small">' + backupEsc(data.error || 'Failed to load backups') + '</td></tr>';
          return;
        }
        renderBackups(data.backups || []);
        updateBackupBadge(data.status);
        if (data.status && data.status.status === 'running' && !backupPollInterval) {
          backupBusy = true;
          startBackupPolling();
        }
      } catch (err) {
        body.innerHTML = '<tr><td colspan="5" class="text-danger small">' + backupEsc(err.message) + '</td></tr>';
      }
    }

    function renderBackups(list) {
      const body = document.getElementById('backupRows');
      if (!list.length) {
        body.innerHTML = '<tr><td colspan="5" class="text-muted small">No backup archives found. Create one from the Bahmni admin Backup page.</td></tr>';
        return;
      }
      body.innerHTML = list.map(b => (
        '<tr>' +
          '<td class="small text-break"><i class="fa-solid fa-file-zipper me-1 text-secondary"></i>' + backupEsc(b.name) + '</td>' +
          '<td class="small">' + backupEsc(b.type || '') + '</td>' +
          '<td class="small text-nowrap">' + backupEsc(b.modified || '') + '</td>' +
          '<td class="small text-end text-nowrap">' + (b.size_mb != null ? b.size_mb + ' MB' : '') + '</td>' +
          '<td class="text-end text-nowrap">' +
            '<a class="btn btn-sm btn-outline-primary me-1" href="/api/backups/download/' + encodeURIComponent(b.name) + '"><i class="fa-solid fa-download me-1"></i> Download</a>' +
            '<button class="btn btn-sm btn-warning" data-name="' + backupEsc(b.name) + '" onclick="openRestoreModal(this.dataset.name)"' + (backupBusy ? ' disabled' : '') + '><i class="fa-solid fa-database me-1"></i> Restore</button>' +
          '</td>' +
        '</tr>'
      )).join('');
    }

    function openRestoreModal(name) {
      if (backupBusy) { alert('A backup/restore operation is already running. Please wait for it to finish.'); return; }
      const label = document.getElementById('restoreArchiveName');
      label.textContent = name;
      label.dataset.archive = name;
      const inp = document.getElementById('restoreConfirmInput');
      inp.value = '';
      document.getElementById('btnConfirmRestore').disabled = true;
      new bootstrap.Modal(document.getElementById('restoreModal')).show();
    }

    async function executeRestore() {
      const name = document.getElementById('restoreArchiveName').dataset.archive;
      if (!name) return;
      bootstrap.Modal.getInstance(document.getElementById('restoreModal')).hide();
      if (isExecuting) { alert('A script is currently running. Wait for it to finish before restoring.'); return; }
      clearConsole();
      appendTerminal('[*] Requesting restore from ' + name + ' ...');
      try {
        const resp = await fetch('/api/restore', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({archive: name})
        });
        const data = await resp.json();
        if (!resp.ok) {
          appendTerminal('[!] ' + (data.error || data.message || 'Restore failed to start'));
          alert(data.error || data.message || 'Restore failed to start');
          return;
        }
        appendTerminal('[*] ' + (data.message || 'Restore started.'));
        backupBusy = true;
        startBackupPolling();
      } catch (err) {
        appendTerminal('[!] Network Error: ' + err.message);
      }
    }

    function uploadBackup() {
      const input = document.getElementById('backupFileInput');
      const file = input.files && input.files[0];
      if (!file) { alert('Choose a backup archive (.tar.gz) first.'); return; }
      const restoreNow = document.getElementById('backupRestoreNow').checked;
      if (restoreNow && !confirm('Upload "' + file.name + '" and restore the system from it immediately?')) return;
      if (restoreNow && isExecuting) { alert('A script is currently running. Wait for it to finish before restoring.'); return; }
      if (backupBusy) { alert('A backup/restore operation is already running. Please wait for it to finish.'); return; }

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/backup/upload?filename=' + encodeURIComponent(file.name) + '&restore=' + (restoreNow ? 'true' : 'false'));
      xhr.setRequestHeader('Content-Type', 'application/gzip');
      const bar = document.getElementById('backupUploadBar');
      const wrap = document.getElementById('backupUploadProgress');
      wrap.style.display = 'block';
      bar.style.width = '0%';
      bar.textContent = '0%';
      xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
          const pct = Math.round(e.loaded / e.total * 100);
          bar.style.width = pct + '%';
          bar.textContent = pct + '%';
        }
      };
      xhr.onload = () => {
        wrap.style.display = 'none';
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (e) { /* non-JSON response */ }
        if (xhr.status >= 200 && xhr.status < 300) {
          alert(data.message || 'Upload complete.');
          if (data.restoring) {
            clearConsole();
            appendTerminal('[*] ' + (data.message || 'Restore started after upload.'));
            backupBusy = true;
            startBackupPolling();
          } else {
            loadBackups();
          }
        } else {
          alert(data.error || data.raw || ('Upload failed (HTTP ' + xhr.status + ')'));
        }
      };
      xhr.onerror = () => {
        wrap.style.display = 'none';
        alert('Upload failed: network error');
      };
      appendTerminal('[*] Uploading ' + file.name + (restoreNow ? ' (restore starts after upload)' : '') + ' ...');
      xhr.send(file);
    }

    function startBackupPolling() {
      if (backupPollInterval) clearInterval(backupPollInterval);
      backupLogOffset = 0;
      updateBackupBadge({status: 'running', type: 'starting', progress: 0});
      backupPollInterval = setInterval(async () => {
        try {
          const resp = await fetch('/api/backup/status');
          if (!resp.ok) return;
          const st = await resp.json();

          const logs = st.logs || [];
          if (logs.length < backupLogOffset) backupLogOffset = 0;   // new op reset the buffer
          if (logs.length > backupLogOffset) {
            const term = document.getElementById('terminalOutput');
            logs.slice(backupLogOffset).forEach(line => { term.textContent += line + '\\n'; });
            term.scrollTop = term.scrollHeight;
            backupLogOffset = logs.length;
            document.getElementById('logCounter').textContent = backupLogOffset + ' lines';
          }

          updateBackupBadge(st);
          const taskInfo = document.getElementById('consoleTaskInfo');

          if (st.status === 'running') {
            taskInfo.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-warning me-1"></i> ' + backupEsc(st.type || 'backup') + ': ' + (st.progress || 0) + '%';
          } else if (st.status === 'completed') {
            clearInterval(backupPollInterval); backupPollInterval = null;
            backupBusy = false;
            taskInfo.innerHTML = '<i class="fa-solid fa-circle-check text-success me-1"></i> ' + backupEsc(st.type || 'operation') + ' completed';
            appendTerminal('[*] ' + (st.message || 'Operation completed.'));
            loadBackups();
            refreshSystemHealth();
          } else if (st.status === 'error') {
            clearInterval(backupPollInterval); backupPollInterval = null;
            backupBusy = false;
            taskInfo.innerHTML = '<i class="fa-solid fa-circle-xmark text-danger me-1"></i> ' + backupEsc(st.type || 'operation') + ' failed';
            appendTerminal('[!] ' + (st.message || 'Operation failed.'));
            loadBackups();
          }
        } catch (e) {
          console.error('Backup poll error:', e);
        }
      }, 1000);
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

    // Path picker events (delegated so re-renders keep working)
    document.getElementById('fsList').addEventListener('click', e => {
      const row = e.target.closest('.fs-row');
      if (row) fsPickRow(row);
    });
    document.getElementById('fsList').addEventListener('dblclick', e => {
      const row = e.target.closest('.fs-row');
      if (row && row.dataset.dir !== '1' && fsKind === 'file') fsConfirm();
    });
    document.getElementById('fsCrumb').addEventListener('click', e => {
      const btn = e.target.closest('button[data-p]');
      if (btn) fsNavigate(btn.dataset.p);
    });

    // Initial load
    initPathZones();
    refreshSystemHealth();
    loadBackups();
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
