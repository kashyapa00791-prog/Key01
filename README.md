# NEXUS KEY CONTROL

Flask + SQLite license panel with separate Google-authenticated user workspaces and an admin workspace.

## Features
- Existing admin login retained.
- Google OAuth registration and login. Google passwords are never requested or stored by this application.
- A separate workspace for each Google account; users can only view and manage their own keys.
- A unique per-user verification endpoint: `/u/<panel_id>/connect`.
- Legacy admin keys continue to use `/connect`.
- Key usage shows unique device IDs recorded against the configured device limit (`used / max_devices`).
- SQLite migration adds user ownership without deleting existing license records.

## Install and run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_USER="your-admin"
export ADMIN_PASSWORD="use-a-long-unique-password"
export GOOGLE_CLIENT_ID="your-google-oauth-client-id"
export GOOGLE_CLIENT_SECRET="your-google-oauth-client-secret"
python app.py
```
Open `http://127.0.0.1:5000`.

## Google OAuth setup
1. In Google Cloud Console, create an OAuth 2.0 Client ID of type **Web application**.
2. Add your deployed HTTPS origin to Authorized JavaScript origins if required by your setup.
3. Add this exact Authorized redirect URI:
   `https://YOUR-DOMAIN/auth/google/callback`
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on the hosting service.
5. Set `SECRET_KEY` to a long random value. Set `COOKIE_SECURE=1` when deployed behind HTTPS.

For local development, register `http://127.0.0.1:5000/auth/google/callback` as an additional redirect URI.

## Where data is stored
- User Google identity (Google subject ID, email, display name), unique panel ID, keys, key/device usage and settings are stored in `license_panel.db`.
- The Google account password is **not** stored. Google handles password entry and authentication through OAuth.
- OAuth client credentials and the Flask secret belong in hosting environment variables, not in the SQLite database or source code.

## Verification endpoint format
User-specific endpoint:
`https://YOUR-DOMAIN/u/USER_PANEL_ID/connect`

POST JSON:
```json
{"key":"NX-XXXX-XXXX-XXXX","device_id":"DEVICE-IDENTIFIER"}
```
A key is accepted only when it belongs to the Google account whose panel ID is in the endpoint URL. Existing admin-owned keys use `/connect`.

## Usage metric
The client must send `device_id` or `hwid` on every verification request. The API rejects requests without it so successful activations cannot silently go uncounted. The panel counts distinct device IDs per key; the `used / limit` display corresponds to unique devices / `max_devices`. This is a device count, not a verified count of individual people: one person using two devices counts twice, and multiple people sharing one device count once. Accurate human-user counts require a stable authenticated end-user ID in the client protocol.

## Deployment notes
Use HTTPS, keep OAuth credentials and `SECRET_KEY` private, and back up `license_panel.db`. Existing database records are retained and existing keys with no owner remain in the admin workspace.


## User accounts

Users register with a manually entered `@gmail.com` address and a separate NEXUS website password (minimum 8 characters). The Google account password is never requested or stored. Website passwords are stored as Werkzeug password hashes in the `users.password_hash` column of `license_panel.db`. Each registration receives a unique `panel_id` and its own `/u/<panel_id>/connect` verification endpoint.

Set a strong `SECRET_KEY`, `ADMIN_USER`, and `ADMIN_PASSWORD` in the hosting environment before deployment. Existing Google OAuth accounts migrated from earlier versions have no website password hash; they need a separate account/password migration flow before they can use the new manual login.
