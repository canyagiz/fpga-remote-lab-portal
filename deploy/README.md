# Deployment configs (CT210)

These files live on CT210 outside this repo checkout (systemd units under
`/etc/systemd/system/`, nginx sites under `/etc/nginx/sites-available/`) -
copies are kept here so a rebuilt CT210 (or a second instance) doesn't have
to reverse-engineer them from a running server.

## Layout

- `fpga-remote-lab.service` -> `/etc/systemd/system/fpga-remote-lab.service`
  Runs uvicorn bound to `127.0.0.1:8001` - internal only, not reachable
  from outside CT210. nginx is the public entry point.
- `nginx-fpga-remote-lab.conf` -> `/etc/nginx/sites-available/fpga-remote-lab`
  (then `ln -s` into `sites-enabled/`). Listens on port 8000 (same URL
  users already have: `http://10.30.70.24:8000/`) and splits traffic:
  - `POST /hw/{lab_id}/logout` -> our app (needs the database)
  - `/labfiles/*` -> the shared static-file server directly
  - `/hw/{lab_id}/*` (everything else) -> the matching hardware
    container directly, by port
  - everything else -> our app (the SPA and `/api/*`)
- `nginx-fpga-remote-lab.conf.j2` + `generate_nginx_config.py` - this
  file is **generated**, not hand-written. See "Lab catalog" below.

## Lab catalog (backend/labs.yaml)

Which labs exist, their hardware address, and which are public used to
be a Python list in `app/main.py`, hand-copied into this directory's
nginx config separately - the two drifted out of sync more than once.
Both now come from one file, `backend/labs.yaml` (see
`backend/labs.yaml.example` for the annotated format):

- `app/main.py::_seed_labs()` reads it directly to seed the database on
  first startup (only when the `labs` table is empty - editing this
  file later does not retroactively change an already-seeded lab row).
- `deploy/generate_nginx_config.py` reads the same file and renders
  `nginx-fpga-remote-lab.conf.j2` into the actual nginx config, turning
  each lab's `backend_url` into the `lab_id -> host:port` map nginx
  needs (and `labfiles_host` into the `/labfiles/` proxy target).

To add/remove a lab or change a board's address:

```bash
# 1. Edit backend/labs.yaml
# 2. Regenerate the nginx config from it:
python3 deploy/generate_nginx_config.py
# 3. Deploy both sides:
pct push 210 backend/labs.yaml /opt/fpga-remote-lab/backend/labs.yaml
pct push 210 deploy/nginx-fpga-remote-lab.conf /etc/nginx/sites-available/fpga-remote-lab
pct exec 210 -- nginx -t && pct exec 210 -- systemctl reload nginx
# 4. If the labs table is already seeded, a labs.yaml change doesn't
#    retroactively apply - update the existing row directly (or via a
#    future admin-edit endpoint) instead of restarting expecting a re-seed.
```

A board that doesn't run **labdiscoverylib** (the WebLab-Deusto-
compatible REST API `app/services/weblab.py` calls) won't actually work
through Access even with a correct `labs.yaml` entry - this file only
covers routing/catalog, not the hardware integration protocol itself.

## Applying other changes

```bash
# after editing nginx-fpga-remote-lab.conf.j2 (not the .conf directly -
# see "Lab catalog" above):
python3 deploy/generate_nginx_config.py
pct push 210 deploy/nginx-fpga-remote-lab.conf /etc/nginx/sites-available/fpga-remote-lab
pct exec 210 -- nginx -t && pct exec 210 -- systemctl reload nginx

# after editing fpga-remote-lab.service:
pct push 210 deploy/fpga-remote-lab.service /etc/systemd/system/fpga-remote-lab.service
pct exec 210 -- systemctl daemon-reload
pct exec 210 -- systemctl restart fpga-remote-lab
```

## Database schema (Alembic migrations)

The schema is owned by Alembic (`backend/alembic/`), not by the app - the
startup code no longer creates tables. The database URL is read from the
app's own settings (`.env`), so run these from `/opt/fpga-remote-lab/backend`
with the venv active.

```bash
# First-time / rebuilt server: create the whole schema from scratch.
cd /opt/fpga-remote-lab/backend && source .venv/bin/activate
alembic upgrade head
systemctl restart fpga-remote-lab   # lifespan then seeds the 4 labs

# After changing a model (new column/table): generate + apply a migration.
alembic revision --autogenerate -m "describe the change"
#   ^ review the generated file in alembic/versions/ before applying
alembic upgrade head

# Sanity checks:
alembic current   # which revision the live DB is at
alembic check     # fails if models and the live DB have drifted
```

**Never** apply schema changes with hand-written `ALTER TABLE` any more -
that was the old workflow and it left no record. Every change is a
committed migration file now.

> Tests do **not** use this database. `backend/tests/conftest.py` forces an
> isolated throwaway sqlite file (with a hard assertion that refuses to run
> against anything else), so `pytest` can never touch the production
> Postgres - a lesson learned the hard way when the un-isolated suite was
> wiping it on every run.

## Why nginx instead of proxying in the app itself

Earlier versions of this backend reverse-proxied hardware-lab traffic
itself (streaming httpx calls in `app/routers/hardware_proxy.py`). That
worked, but reimplemented in Python what a reverse proxy is already good
at - see `[[project_ct210_migration_plan]]` for the full history. nginx
now does the bulk of it; `hardware_proxy.py` keeps only the one route
that has to touch our own database (instant reservation close on
in-lab logout).
