# NEXUS KEY CONTROL — Green Hacker License Panel

A working Flask + SQLite license-key admin dashboard inspired by the provided screenshots, restyled with a neon green / deep black cyber interface.

## Features
- Admin sign-in and logout
- Dashboard stats and recent activity
- Create license keys (auto-generated or custom)
- Select game, device limit, duration, and notes
- Search/filter license keys
- Activate, expire, revoke, or delete keys
- Settings page
- SQLite database created automatically
- Responsive mobile-first UI

## Run locally
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run `python -m venv .venv`
4. Activate the environment:
   - Windows: `.venv\\Scripts\\activate`
   - macOS/Linux: `source .venv/bin/activate`
5. Run `pip install -r requirements.txt`
6. Run `python app.py`
7. Open `http://127.0.0.1:5000`

## Default demo login
- Username: `admin`
- Password: `ChangeMe123!`

Change these before deployment using environment variables:
- `ADMIN_USER`
- `ADMIN_PASSWORD`
- `SECRET_KEY`

Example (macOS/Linux):
```bash
export ADMIN_USER="your-admin"
export ADMIN_PASSWORD="use-a-long-unique-password"
export SECRET_KEY="a-long-random-secret"
python app.py
```

## Important
This is an admin panel demo and stores license records in a local SQLite database. It does **not** validate keys inside a game/app automatically. To do that, integrate the `/api/health` pattern with a separate authenticated license-validation API and your own client software. Before public deployment, use HTTPS, a strong secret key, secure hosting, rate limiting, CSRF protection, backups, and proper account/password management.
