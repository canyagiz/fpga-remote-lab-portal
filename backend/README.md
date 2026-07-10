# FPGA Remote Lab - Backend

FastAPI backend for the portal that will eventually replace CT200
(LabDiscoveryEngine) for the H-BRS FPGA Remote Lab.

## Current scope

Only **authentication** and **queue/reservation** logic are implemented right
now. Hardware access proxying, the multi-lab catalog, and the Arty Z7
integration are deliberately out of scope for this stage and will be added
later.

This backend was designed from scratch. An existing PHP/MySQL prototype
(`martinglucero/remote-lab`) was reviewed beforehand and is used only as a
conceptual reference for the data model and the registration security-chain
pattern (honeypot -> CSRF -> captcha -> rate limit) - none of its code was
reused, because its identity model was fully client-trusted (no server-side
session) and it had no server-side authorization checks at all.

Concretely, this implementation fixes two classes of bugs found in that
review:

- **Identity is resolved from a server-side session cookie**
  (`app/deps.py::get_current_user`), never from a client-supplied `userId`
  field. Every admin-only and per-user endpoint checks this server-side.
  The cookie itself is long-lived (`SESSION_MAX_AGE_DAYS`, default 30) and
  re-signed on every response, so it's a sliding window like most modern
  sites: staying active keeps you signed in, ~30 days of inactivity signs
  you out.
- **Queue position is recomputed on every state change** that removes a
  reservation from the `pending` set (cancel, complete, expire, or promotion
  to `active`) - see `app/services/queue.py::renumber_queue`. The old repo
  set `queue_position` once at creation and never touched it again, so
  whoever was behind position 0 waited forever.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: at minimum set a real SECRET_KEY.
# Leave SMTP_HOST empty for local dev - 2FA codes are logged instead of emailed.
# Leave DATABASE_URL as the default sqlite line for quick local testing.

uvicorn app.main:app --reload
```

API docs are then available at `http://localhost:8000/docs`.

Once `frontend/dist` exists (see `../frontend/README.md`), this same process
also serves the built frontend - see "Serving the frontend" below.

### Database

SQLite (the `.env.example` default) is only for quick local testing. CT210
runs **Postgres** - set `DATABASE_URL` to
`postgresql+psycopg2://<user>:<password>@localhost:5432/<dbname>` and make
sure `psycopg2-binary` is installed (already in `requirements.txt`). No
migration tool (Alembic) is wired up yet - `Base.metadata.create_all()` in
`app/main.py`'s lifespan handler creates tables on startup, which is fine
while the schema is still moving but should be replaced with real migrations
before this holds production data.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

`tests/test_reservations.py` specifically encodes the queue-advancement and
lab-exclusivity bugs described above as regression tests.

## API overview

Everything lives under `/api` so it can never collide with a frontend route
of the same name once the SPA is served from the same origin (e.g.
`GET /api/labs` vs. the frontend's `/labs` page).

| Endpoint | Method | Notes |
|---|---|---|
| `/api/auth/captcha` | GET | Math captcha, stored in session |
| `/api/auth/csrf-token` | GET | CSRF token, stored in session |
| `/api/auth/register` | POST | Honeypot + CSRF + captcha + IP rate limit |
| `/api/auth/login` | POST | Starts 2FA if enabled, sets `pending_2fa_user_id` in session |
| `/api/auth/verify-2fa` | POST | Reads pending user id from session, not the request body. First success turns `two_factor_enabled` off, so it's a one-time email confirmation, not a per-login gate |
| `/api/auth/resend-2fa` | POST | Same - session-scoped, can't be used to spam another account |
| `/api/auth/logout` | POST | Clears the session |
| `/api/auth/me` | GET | Current user, resolved from session |
| `/api/labs` | GET | List labs (any authenticated user) |
| `/api/labs` | POST | Create lab - requires `role == admin`, checked server-side |
| `/api/reservations/mine` | GET | Current user's open reservations |
| `/api/reservations` | POST | Book a future date/time slot |
| `/api/reservations/queue` | POST | Join the immediate queue for a lab |
| `/api/reservations/{id}/cancel` | POST | Cancel, then renumber the lab's queue |
| `/api/reservations/{id}/start` | POST | Promote a pending reservation to active, if it's actually your turn *and* the lab isn't occupied |
| `/api/reservations/{id}/complete` | POST | Finish a session, then renumber the queue |
| `/api/users` | GET | List users - admin only |
| `/api/users/{id}` | DELETE | Delete a user - admin only, blocks self-deletion and users with reservation history |
| `/health` | GET | Not under `/api` - plain infra health check |

A background task (`app/main.py::_expiry_sweep_loop`) periodically expires
overdue reservations server-side, so a slot is freed even if the user just
closes their browser tab - the old repo relied on the client to call this.

## Serving the frontend

`app/main.py` mounts `../frontend/dist` (if it exists) and serves
`index.html` as a fallback for any path that isn't an `/api/*` route or an
existing static file, so React Router's client-side routes work on a hard
refresh. Build the frontend first (see `../frontend/README.md`), then start
this backend normally - no separate frontend server needed in production.

## Hardware access (CT300)

`GET /api/labs/{id}/access` calls the lab's own hardware container REST
API directly (`app/services/weblab.py` - a plain HTTP call, no
labdiscoverylib/WebLab-Deusto dependency in this project) to start a real
session, then hands the browser a URL under `/hw/{lab_id}/...`.

In production (see `../deploy/`), **nginx** - not this app - reverse-proxies
that traffic straight to CT300, mirroring what CT200's own nginx does:
`/hw/{lab_id}/*` and `/labfiles/*` go directly to the matching CT300
container/port, with one exception - `POST /hw/{lab_id}/logout` is carved
out back to this app, because closing the reservation the instant an
in-lab "Log out" succeeds needs our own database (see
`app/routers/hardware_proxy.py`). The background sweep
(`services/queue.py::sweep_logged_out_sessions`) stays as a fallback for
whenever that request never arrives (closed tab, dropped connection).

## Deliberately deferred (see project migration plan)

- German translation
- Alembic migrations (schema changes are still applied by hand via `ALTER
  TABLE` - see `[[project_ct210_migration_plan]]`)
