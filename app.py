import os
import sqlite3
import secrets
import string
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "license_panel.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_text TEXT UNIQUE NOT NULL,
            game TEXT NOT NULL DEFAULT 'Free Fire',
            max_devices INTEGER NOT NULL DEFAULT 1,
            duration_days INTEGER NOT NULL DEFAULT 10,
            status TEXT NOT NULL DEFAULT 'Not Started',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            note TEXT DEFAULT ''
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS settings (
            name TEXT PRIMARY KEY, value TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS device_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_id INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            UNIQUE(license_id, device_id),
            FOREIGN KEY(license_id) REFERENCES licenses(id) ON DELETE CASCADE
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_sub TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            display_name TEXT NOT NULL DEFAULT '',
            panel_id TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            password_hash TEXT
        )""")
        user_cols = {r["name"] for r in con.execute("PRAGMA table_info(users)")}
        if "password_hash" not in user_cols:
            con.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        # Migrate existing installations without dropping their license records.
        cols = {r["name"] for r in con.execute("PRAGMA table_info(licenses)")}
        if "owner_id" not in cols:
            con.execute("ALTER TABLE licenses ADD COLUMN owner_id INTEGER REFERENCES users(id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_licenses_owner ON licenses(owner_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_bindings_license ON device_bindings(license_id)")
        con.execute("INSERT OR IGNORE INTO settings(name,value) VALUES('site_name','NEXUS KEY CONTROL')")
        con.execute("INSERT OR IGNORE INTO settings(name,value) VALUES('credits','999999')")


init_db()


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def make_key():
    alphabet = string.ascii_uppercase + string.digits
    return "NX-" + "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def current_owner_id():
    return None if session.get("role") == "admin" else session.get("user_id")


def license_scope():
    return ("", ()) if session.get("role") == "admin" else (" WHERE owner_id=?", (session.get("user_id"),))


def get_stats(owner_id=None):
    where = " WHERE owner_id=?" if owner_id is not None else ""
    params = (owner_id,) if owner_id is not None else ()
    with db() as con:
        total, active, expired = con.execute(
            f"SELECT COUNT(*), SUM(status='Active'), SUM(status='Expired') FROM licenses{where}", params
        ).fetchone()
        used = con.execute(
            f"""SELECT COUNT(DISTINCT b.device_id)
                FROM device_bindings b JOIN licenses l ON l.id=b.license_id{where.replace('owner_id', 'l.owner_id')}""",
            params,
        ).fetchone()[0]
        total_capacity = con.execute(
            f"SELECT COALESCE(SUM(max_devices),0) FROM licenses{where}", params
        ).fetchone()[0]
    return dict(total=total or 0, active=active or 0, expired=expired or 0,
                used=used or 0, capacity=total_capacity or 0,
                remaining=max(0, (total_capacity or 0) - (used or 0)))


@app.route("/")
def home():
    return redirect(url_for("dashboard") if session.get("logged_in") else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        # Keep the existing administrator login separate from customer accounts.
        username = request.form.get("username", "").strip()
        if username and secrets.compare_digest(username, ADMIN_USER) and secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session.update(logged_in=True, username=username, role="admin")
            flash("Admin access granted.", "success")
            return redirect(url_for("dashboard"))
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone() if email else None
        if user and user["password_hash"] and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(logged_in=True, role="user", user_id=user["id"],
                           username=user["display_name"] or user["email"], email=user["email"],
                           panel_id=user["panel_id"])
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid Gmail or website password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        display_name = request.form.get("display_name", "").strip()[:100]
        if not email or len(email) > 254 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Enter a valid Gmail address.", "error")
        elif not email.endswith("@gmail.com"):
            flash("Use a Gmail address to register.", "error")
        elif len(password) < 8:
            flash("Create a website password with at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            panel_id = secrets.token_urlsafe(24)
            password_hash = generate_password_hash(password)
            try:
                with db() as con:
                    con.execute(
                        """INSERT INTO users(google_sub,email,display_name,panel_id,created_at,password_hash)
                           VALUES(?,?,?,?,?,?)""",
                        ("local:" + email, email, display_name or email.split("@")[0], panel_id,
                         datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), password_hash)
                    )
                    user = con.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
                session.clear()
                session.update(logged_in=True, role="user", user_id=user["id"],
                               username=user["display_name"], email=user["email"], panel_id=user["panel_id"])
                flash("Account created. Your private panel is ready.", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("An account with this Gmail already exists. Please log in.", "error")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Session terminated.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    owner_id = current_owner_id()
    where = " WHERE owner_id=?" if owner_id is not None else ""
    params = (owner_id,) if owner_id is not None else ()
    with db() as con:
        recent = con.execute(f"SELECT * FROM licenses{where} ORDER BY id DESC LIMIT 5", params).fetchall()
        usage = con.execute(
            f"""SELECT l.id, COUNT(DISTINCT b.device_id) AS used
                FROM licenses l LEFT JOIN device_bindings b ON b.license_id=l.id
                {where} GROUP BY l.id ORDER BY l.id DESC LIMIT 8""",
            params
        ).fetchall()
    return render_template("dashboard.html", stats=get_stats(owner_id), recent=recent,
                           usage=usage, panel_link=url_for("user_connect", panel_id=session.get("panel_id"), _external=True)
                           if session.get("role") == "user" else None)


@app.route("/keys")
@login_required
def keys():
    q = request.args.get("q", "").strip()
    where, params = license_scope()
    with db() as con:
        if q:
            clause = (" AND " if where else " WHERE ") + "(key_text LIKE ? OR game LIKE ? OR status LIKE ?)"
            rows = con.execute(f"SELECT * FROM licenses{where}{clause} ORDER BY id DESC",
                               (*params, f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = con.execute(f"SELECT * FROM licenses{where} ORDER BY id DESC", params).fetchall()
        usage_map = {r["id"]: r["used"] for r in con.execute(
            f"""SELECT l.id, COUNT(DISTINCT b.device_id) AS used FROM licenses l
                LEFT JOIN device_bindings b ON b.license_id=l.id{where}
                GROUP BY l.id""", params
        )}
    return render_template("keys.html", rows=rows, q=q, usage_map=usage_map)


@app.route("/keys/new", methods=["GET", "POST"])
@login_required
def create_key():
    if request.method == "POST":
        game = request.form.get("game", "Free Fire")
        try:
            devices = max(1, min(1000000, int(request.form.get("devices", "1"))))
            days = max(1, min(3650, int(request.form.get("days", "10"))))
        except ValueError:
            flash("Devices and duration must be numbers.", "error")
            return redirect(url_for("create_key"))
        key_text = request.form.get("key_text", "").strip().upper() or make_key()
        note = request.form.get("note", "").strip()[:200]
        try:
            with db() as con:
                con.execute("""INSERT INTO licenses
                    (key_text,game,max_devices,duration_days,status,created_at,note,owner_id)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (key_text, game, devices, days, "Not Started",
                     datetime.now().strftime("%Y-%m-%d %H:%M"), note, current_owner_id()))
            flash("License key created successfully.", "success")
            return redirect(url_for("keys"))
        except sqlite3.IntegrityError:
            flash("That key already exists. Generate or enter a different key.", "error")
    return render_template("create.html")


@app.route("/keys/<int:key_id>/status", methods=["POST"])
@login_required
def change_status(key_id):
    status = request.form.get("status", "")
    if status not in ("Not Started", "Active", "Expired", "Revoked"):
        flash("Invalid status.", "error")
        return redirect(url_for("keys"))
    owner_id = current_owner_id()
    with db() as con:
        row = con.execute("SELECT * FROM licenses WHERE id=? AND (owner_id IS ? OR ?=1)",
                          (key_id, owner_id, 1 if session.get("role") == "admin" else 0)).fetchone()
        if row:
            expires = row["expires_at"]
            if status == "Active" and not expires:
                expires = (datetime.now() + timedelta(days=row["duration_days"])).strftime("%Y-%m-%d %H:%M")
            con.execute("UPDATE licenses SET status=?, expires_at=? WHERE id=?", (status, expires, key_id))
            flash(f"Key status updated to {status}.", "success")
        else:
            flash("Key not found.", "error")
    return redirect(url_for("keys"))


@app.route("/keys/<int:key_id>/delete", methods=["POST"])
@login_required
def delete_key(key_id):
    owner_id = current_owner_id()
    with db() as con:
        row = con.execute("SELECT id FROM licenses WHERE id=? AND (owner_id IS ? OR ?=1)",
                          (key_id, owner_id, 1 if session.get("role") == "admin" else 0)).fetchone()
        if row:
            con.execute("DELETE FROM device_bindings WHERE license_id=?", (key_id,))
            con.execute("DELETE FROM licenses WHERE id=?", (key_id,))
    flash("License key deleted." if row else "Key not found.", "success" if row else "error")
    return redirect(url_for("keys"))


@app.route("/keys/<int:key_id>/reset-devices", methods=["POST"])
@login_required
def reset_devices(key_id):
    owner_id = current_owner_id()
    with db() as con:
        row = con.execute("SELECT id FROM licenses WHERE id=? AND (owner_id IS ? OR ?=1)",
                          (key_id, owner_id, 1 if session.get("role") == "admin" else 0)).fetchone()
        if row:
            con.execute("DELETE FROM device_bindings WHERE license_id=?", (key_id,))
    flash("Device bindings reset." if row else "Key not found.", "success" if row else "error")
    return redirect(url_for("keys"))


@app.route("/keys/<int:key_id>/devices")
@login_required
def view_devices(key_id):
    owner_id = current_owner_id()
    with db() as con:
        allowed = con.execute("SELECT id FROM licenses WHERE id=? AND (owner_id IS ? OR ?=1)",
                              (key_id, owner_id, 1 if session.get("role") == "admin" else 0)).fetchone()
        if not allowed:
            return jsonify(error="Key not found"), 404
        rows = con.execute("SELECT device_id, first_seen, last_seen FROM device_bindings WHERE license_id=? ORDER BY id",
                           (key_id,)).fetchall()
    return jsonify(devices=[dict(r) for r in rows])


@app.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    with db() as con:
        if request.method == "POST":
            name = request.form.get("site_name", "NEXUS KEY CONTROL").strip()[:60] or "NEXUS KEY CONTROL"
            con.execute("INSERT OR REPLACE INTO settings(name,value) VALUES('site_name',?)", (name,))
            flash("Settings saved.", "success")
        site_name = con.execute("SELECT value FROM settings WHERE name='site_name'").fetchone()["value"]
    return render_template("settings.html", site_name=site_name)


def validate_key_for_panel(panel_id, payload):
    key_text = str(payload.get("key") or payload.get("license") or "").strip().upper()
    device_id = str(payload.get("device_id") or payload.get("hwid") or "").strip()[:128]
    if not key_text:
        return jsonify(ok=False, error="Missing key"), 400
    if not device_id:
        return jsonify(ok=False, error="Missing device_id (or hwid); required for usage tracking"), 400
    with db() as con:
        owner = con.execute("SELECT id FROM users WHERE panel_id=?", (panel_id,)).fetchone()
        if not owner:
            return jsonify(ok=False, error="Unknown panel"), 404
        row = con.execute("SELECT * FROM licenses WHERE key_text=? AND owner_id=?",
                          (key_text, owner["id"])).fetchone()
        if not row:
            return jsonify(ok=False, error="Invalid key for this panel"), 404
        if row["status"] in ("Revoked", "Expired"):
            return jsonify(ok=False, error=f"Key {row['status'].lower()}"), 403
        expires = row["expires_at"]
        if expires:
            try:
                if datetime.now() > datetime.strptime(expires, "%Y-%m-%d %H:%M"):
                    con.execute("UPDATE licenses SET status='Expired' WHERE id=?", (row["id"],))
                    return jsonify(ok=False, error="Key expired"), 403
            except ValueError:
                pass
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if device_id:
            existing = con.execute("SELECT id FROM device_bindings WHERE license_id=? AND device_id=?",
                                   (row["id"], device_id)).fetchone()
            if existing:
                con.execute("UPDATE device_bindings SET last_seen=? WHERE id=?", (now, existing["id"]))
            else:
                count = con.execute("SELECT COUNT(*) FROM device_bindings WHERE license_id=?",
                                    (row["id"],)).fetchone()[0]
                if count >= row["max_devices"]:
                    return jsonify(ok=False, error="Device limit reached",
                                   max_devices=row["max_devices"]), 403
                con.execute("""INSERT INTO device_bindings
                    (license_id,device_id,first_seen,last_seen) VALUES(?,?,?,?)""",
                    (row["id"], device_id, now, now))
        if row["status"] == "Not Started":
            expires = (datetime.now() + timedelta(days=row["duration_days"])).strftime("%Y-%m-%d %H:%M")
            con.execute("UPDATE licenses SET status='Active', expires_at=? WHERE id=?", (expires, row["id"]))
        used = con.execute("SELECT COUNT(*) FROM device_bindings WHERE license_id=?", (row["id"],)).fetchone()[0]
    return jsonify(ok=True, key=row["key_text"], game=row["game"], status="Active",
                   expires_at=expires, max_devices=row["max_devices"], used_devices=used,
                   device_id=device_id or None, server_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@app.route("/connect", methods=["GET", "POST"])
def connect():
    if request.method == "GET":
        return jsonify(ok=True, message="Nexus legacy admin connect endpoint is live.")
    payload = request.get_json(silent=True) or request.form.to_dict()
    key_text = str(payload.get("key") or payload.get("license") or "").strip().upper()
    device_id = str(payload.get("device_id") or payload.get("hwid") or "").strip()[:128]
    if not key_text:
        return jsonify(ok=False, error="Missing key"), 400
    if not device_id:
        return jsonify(ok=False, error="Missing device_id (or hwid); required for usage tracking"), 400
    with db() as con:
        row = con.execute("SELECT * FROM licenses WHERE key_text=? AND owner_id IS NULL", (key_text,)).fetchone()
    if not row:
        return jsonify(ok=False, error="Invalid key"), 404
    # Legacy admin-issued keys retain their original verification path.
    return validate_admin_key(row, device_id)


def validate_admin_key(row, device_id):
    with db() as con:
        row = con.execute("SELECT * FROM licenses WHERE id=?", (row["id"],)).fetchone()
        if row["status"] in ("Revoked", "Expired"):
            return jsonify(ok=False, error=f"Key {row['status'].lower()}"), 403
        expires = row["expires_at"]
        if expires:
            try:
                if datetime.now() > datetime.strptime(expires, "%Y-%m-%d %H:%M"):
                    con.execute("UPDATE licenses SET status='Expired' WHERE id=?", (row["id"],))
                    return jsonify(ok=False, error="Key expired"), 403
            except ValueError:
                pass
        if device_id:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            existing = con.execute("SELECT id FROM device_bindings WHERE license_id=? AND device_id=?",
                                   (row["id"], device_id)).fetchone()
            if existing:
                con.execute("UPDATE device_bindings SET last_seen=? WHERE id=?", (now, existing["id"]))
            else:
                count = con.execute("SELECT COUNT(*) FROM device_bindings WHERE license_id=?", (row["id"],)).fetchone()[0]
                if count >= row["max_devices"]:
                    return jsonify(ok=False, error="Device limit reached", max_devices=row["max_devices"]), 403
                con.execute("INSERT INTO device_bindings(license_id,device_id,first_seen,last_seen) VALUES(?,?,?,?)",
                            (row["id"], device_id, now, now))
        if row["status"] == "Not Started":
            expires = (datetime.now() + timedelta(days=row["duration_days"])).strftime("%Y-%m-%d %H:%M")
            con.execute("UPDATE licenses SET status='Active', expires_at=? WHERE id=?", (expires, row["id"]))
        used = con.execute("SELECT COUNT(*) FROM device_bindings WHERE license_id=?", (row["id"],)).fetchone()[0]
    return jsonify(ok=True, key=row["key_text"], game=row["game"], status="Active",
                   expires_at=expires, max_devices=row["max_devices"], used_devices=used,
                   device_id=device_id or None, server_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@app.route("/u/<panel_id>/connect", methods=["GET", "POST"])
def user_connect(panel_id):
    if request.method == "GET":
        with db() as con:
            exists = con.execute("SELECT 1 FROM users WHERE panel_id=?", (panel_id,)).fetchone()
        return (jsonify(ok=True, message="User-specific verification endpoint is live.") if exists
                else (jsonify(ok=False, error="Unknown panel"), 404))
    payload = request.get_json(silent=True) or request.form.to_dict()
    return validate_key_for_panel(panel_id, payload)


@app.route("/api/health")
def health():
    return jsonify(ok=True, app="Nexus Key Control", timestamp=datetime.now().isoformat(timespec="seconds"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
