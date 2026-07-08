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

uvicorn app.main:app --reload
```

API docs are then available at `http://localhost:8000/docs`.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

`tests/test_reservations.py` specifically encodes the queue-advancement and
lab-exclusivity bugs described above as regression tests.

## API overview

| Endpoint | Method | Notes |
|---|---|---|
| `/auth/captcha` | GET | Math captcha, stored in session |
| `/auth/csrf-token` | GET | CSRF token, stored in session |
| `/auth/register` | POST | Honeypot + CSRF + captcha + IP rate limit |
| `/auth/login` | POST | Starts 2FA if enabled, sets `pending_2fa_user_id` in session |
| `/auth/verify-2fa` | POST | Reads pending user id from session, not the request body |
| `/auth/resend-2fa` | POST | Same - session-scoped, can't be used to spam another account |
| `/auth/logout` | POST | Clears the session |
| `/auth/me` | GET | Current user, resolved from session |
| `/labs` | GET | List labs (any authenticated user) |
| `/labs` | POST | Create lab - requires `role == admin`, checked server-side |
| `/reservations/mine` | GET | Current user's open reservations |
| `/reservations` | POST | Book a future date/time slot |
| `/reservations/queue` | POST | Join the immediate queue for a lab |
| `/reservations/{id}/cancel` | POST | Cancel, then renumber the lab's queue |
| `/reservations/{id}/start` | POST | Promote a pending reservation to active, if it's actually your turn *and* the lab isn't occupied |
| `/reservations/{id}/complete` | POST | Finish a session, then renumber the queue |

A background task (`app/main.py::_expiry_sweep_loop`) periodically expires
overdue reservations server-side, so a slot is freed even if the user just
closes their browser tab - the old repo relied on the client to call this.

## Deliberately deferred (see project migration plan)

- Hardware-access proxy layer (nginx `auth_request` + CT300 containers)
- Multi-lab catalog population (Cyclone X/IV/V, Arty Z7)
- German translation
