import os, sqlite3, secrets, string
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "license_panel.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
        # नई टेबल: device bindings
        con.execute("""CREATE TABLE IF NOT EXISTS device_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_id INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            UNIQUE(license_id, device_id),
            FOREIGN KEY(license_id) REFERENCES licenses(id) ON DELETE CASCADE
        )""")
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

def make_key():
    alphabet = string.ascii_uppercase + string.digits
    return "NX-" + "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))

def stats():
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
        active = con.execute("SELECT COUNT(*) FROM licenses WHERE status='Active'").fetchone()[0]
        expired = con.execute("SELECT COUNT(*) FROM licenses WHERE status='Expired'").fetchone()[0]
    return dict(total=total, active=active, expired=expired)

@app.route("/")
def home():
    return redirect(url_for("dashboard") if session.get("logged_in") else url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if secrets.compare_digest(username, ADMIN_USER) and secrets.compare_digest(password, ADMIN_PASSWORD):
            session["logged_in"] = True
            session["username"] = username
            flash("Access granted. Welcome back, operator.", "success")
            return redirect(url_for("dashboard"))
        flash("Access denied. Check your credentials.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Session terminated.", "success")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    with db() as con:
        recent = con.execute("SELECT * FROM licenses ORDER BY id DESC LIMIT 5").fetchall()
    return render_template("dashboard.html", stats=stats(), recent=recent)

@app.route("/keys")
@login_required
def keys():
    q = request.args.get("q", "").strip()
    with db() as con:
        if q:
            rows = con.execute("SELECT * FROM licenses WHERE key_text LIKE ? OR game LIKE ? OR status LIKE ? ORDER BY id DESC",
                               (f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = con.execute("SELECT * FROM licenses ORDER BY id DESC").fetchall()
    return render_template("keys.html", rows=rows, q=q)

@app.route("/keys/new", methods=["GET", "POST"])
@login_required
def create_key():
    if request.method == "POST":
        game = request.form.get("game", "Free Fire")
        try:
            devices = max(1, min(100000000000000000000000000000000, int(request.form.get("devices", "1"))))
            days = max(1, min(3650, int(request.form.get("days", "10"))))
        except ValueError:
            flash("Devices and duration must be numbers.", "error")
            return redirect(url_for("create_key"))
        key_text = request.form.get("key_text", "").strip().upper() or make_key()
        note = request.form.get("note", "").strip()[:200]
        try:
            with db() as con:
                con.execute("INSERT INTO licenses(key_text,game,max_devices,duration_days,status,created_at,note) VALUES(?,?,?,?,?,?,?)",
                    (key_text, game, devices, days, "Not Started", datetime.now().strftime("%Y-%m-%d %H:%M"), note))
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
    with db() as con:
        row = con.execute("SELECT * FROM licenses WHERE id=?", (key_id,)).fetchone()
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
    with db() as con:
        con.execute("DELETE FROM device_bindings WHERE license_id=?", (key_id,))
        con.execute("DELETE FROM licenses WHERE id=?", (key_id,))
    flash("License key deleted.", "success")
    return redirect(url_for("keys"))

# नया: admin binding reset (user फोन बदले तो)
@app.route("/keys/<int:key_id>/reset-devices", methods=["POST"])
@login_required
def reset_devices(key_id):
    with db() as con:
        con.execute("DELETE FROM device_bindings WHERE license_id=?", (key_id,))
    flash("Device bindings reset. Key can be activated on a new device.", "success")
    return redirect(url_for("keys"))

# नया: bindings देखने के लिए (JSON)
@app.route("/keys/<int:key_id>/devices")
@login_required
def view_devices(key_id):
    with db() as con:
        rows = con.execute("SELECT device_id, first_seen, last_seen FROM device_bindings WHERE license_id=? ORDER BY id",
                           (key_id,)).fetchall()
    return jsonify(devices=[dict(r) for r in rows])

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    with db() as con:
        if request.method == "POST":
            name = request.form.get("site_name", "NEXUS KEY CONTROL").strip()[:60] or "NEXUS KEY CONTROL"
            con.execute("INSERT OR REPLACE INTO settings(name,value) VALUES('site_name',?)", (name,))
            flash("Settings saved.", "success")
        site_name = con.execute("SELECT value FROM settings WHERE name='site_name'").fetchone()["value"]
    return render_template("settings.html", site_name=site_name)

# ============================================================
#  /connect  —  mod APK / Lua loader के लिए verification endpoint
#  अब device-lock के साथ
# ============================================================
@app.route("/connect", methods=["GET", "POST"])
def connect():
    if request.method == "GET":
        return jsonify(ok=True, message="Nexus Connect endpoint is live. POST key to validate.")

    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict()

    key_text = str(payload.get("key") or payload.get("license") or "").strip().upper()
    device_id = str(payload.get("device_id") or payload.get("hwid") or "").strip()[:128]

    if not key_text:
        return jsonify(ok=False, error="Missing key"), 400

    with db() as con:
        row = con.execute("SELECT * FROM licenses WHERE key_text=?", (key_text,)).fetchone()

    if not row:
        return jsonify(ok=False, error="Invalid key"), 404
    if row["status"] == "Revoked":
        return jsonify(ok=False, error="Key revoked"), 403
    if row["status"] == "Expired":
        return jsonify(ok=False, error="Key expired"), 403

    expires = row["expires_at"]
    if expires:
        try:
            exp_dt = datetime.strptime(expires, "%Y-%m-%d %H:%M")
            if datetime.now() > exp_dt:
                with db() as con:
                    con.execute("UPDATE licenses SET status='Expired' WHERE id=?", (row["id"],))
                return jsonify(ok=False, error="Key expired"), 403
        except ValueError:
            pass

    # ---- DEVICE-LOCK LOGIC ----
    # device_id optional: अगर नहीं भेजा तो lock skip (backward compatible)
    if device_id:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db() as con:
            existing = con.execute(
                "SELECT id FROM device_bindings WHERE license_id=? AND device_id=?",
                (row["id"], device_id)
            ).fetchone()

            if existing:
                # पहले से bound है — last_seen update
                con.execute("UPDATE device_bindings SET last_seen=? WHERE id=?", (now_str, existing["id"]))
            else:
                # नया device — count check करें
                count = con.execute(
                    "SELECT COUNT(*) FROM device_bindings WHERE license_id=?",
                    (row["id"],)
                ).fetchone()[0]
                if count >= row["max_devices"]:
                    return jsonify(
                        ok=False,
                        error="Device limit reached",
                        max_devices=row["max_devices"],
                        hint="Contact admin to reset device bindings"
                    ), 403
                # नया binding जोड़ें
                con.execute(
                    "INSERT INTO device_bindings(license_id, device_id, first_seen, last_seen) VALUES(?,?,?,?)",
                    (row["id"], device_id, now_str, now_str)
                )

    # पहली बार activate
    if row["status"] == "Not Started":
        expires = (datetime.now() + timedelta(days=row["duration_days"])).strftime("%Y-%m-%d %H:%M")
        with db() as con:
            con.execute("UPDATE licenses SET status='Active', expires_at=? WHERE id=?", (expires, row["id"]))

    return jsonify(
        ok=True,
        key=row["key_text"],
        game=row["game"],
        status="Active",
        expires_at=expires,
        max_devices=row["max_devices"],
        device_id=device_id or None,
        server_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

@app.route("/api/health")
def health():
    return jsonify(ok=True, app="Nexus Key Control", timestamp=datetime.now().isoformat(timespec="seconds"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
