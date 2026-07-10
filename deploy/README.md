# Deployment configs (CT210)

These files live on CT210 outside this repo checkout (systemd units under
`/etc/systemd/system/`, nginx sites under `/etc/nginx/sites-available/`) -
copies are kept here so a rebuilt CT210 (or a second instance) doesn't have
to reverse-engineer them from a running server.

## Layout

- `fgpa-remote-lab.service` -> `/etc/systemd/system/fgpa-remote-lab.service`
  Runs uvicorn bound to `127.0.0.1:8001` - internal only, not reachable
  from outside CT210. nginx is the public entry point.
- `nginx-fgpa-remote-lab.conf` -> `/etc/nginx/sites-available/fgpa-remote-lab`
  (then `ln -s` into `sites-enabled/`). Listens on port 8000 (same URL
  users already have: `http://10.30.70.24:8000/`) and splits traffic:
  - `POST /hw/{lab_id}/logout` -> our app (needs the database)
  - `/labfiles/*` -> CT300's own nginx directly (static lab images)
  - `/hw/{lab_id}/*` (everything else) -> the matching CT300 hardware
    container directly, by port (static map inside the file - keep it in
    sync with `backend/app/main.py::_REAL_LABS` if a lab's port changes
    or a new lab is added)
  - everything else -> our app (the SPA and `/api/*`)

## Applying a change

```bash
# after editing nginx-fgpa-remote-lab.conf:
pct push 210 deploy/nginx-fgpa-remote-lab.conf /etc/nginx/sites-available/fgpa-remote-lab
pct exec 210 -- nginx -t && pct exec 210 -- systemctl reload nginx

# after editing fgpa-remote-lab.service:
pct push 210 deploy/fgpa-remote-lab.service /etc/systemd/system/fgpa-remote-lab.service
pct exec 210 -- systemctl daemon-reload
pct exec 210 -- systemctl restart fgpa-remote-lab
```

## Why nginx instead of proxying in the app itself

Earlier versions of this backend reverse-proxied hardware-lab traffic
itself (streaming httpx calls in `app/routers/hardware_proxy.py`). That
worked, but reimplemented in Python what a reverse proxy is already good
at - see `[[project_ct210_migration_plan]]` for the full history. nginx
now does the bulk of it; `hardware_proxy.py` keeps only the one route
that has to touch our own database (instant reservation close on
in-lab logout).
