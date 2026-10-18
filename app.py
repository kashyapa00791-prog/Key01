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
            devices = max(1, min(100, int(request.form.get("devices", "1"))))
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
        con.execute("DELETE FROM licenses WHERE id=?", (key_id,))
    flash("License key deleted.", "success")
    return redirect(url_for("keys"))

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

@app.route("/api/health")
def health():
    return jsonify(ok=True, app="Nexus Key Control", timestamp=datetime.now().isoformat(timespec="seconds"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
