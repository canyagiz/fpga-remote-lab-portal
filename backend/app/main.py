import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse

from app.config import settings
from app.database import SessionLocal, engine
from app.models import Lab
from app.routers import (
    admin,
    auth,
    hardware_proxy,
    inventory,
    labs,
    profile,
    reservations,
    stats,
)
from app.services.admin import sync_all_admin_roles
from app.services.queue import sweep_expired_reservations, sweep_logged_out_sessions

logger = logging.getLogger("fpga_remote_lab")


async def _expiry_sweep_loop():
    while True:
        await asyncio.sleep(settings.expiry_sweep_interval_seconds)
        db = SessionLocal()
        try:
            # Both sweeps are plain (synchronous) functions that can make
            # real HTTP calls to CT300 (sweep_logged_out_sessions always;
            # sweep_expired_reservations when closing an overrun session).
            # Calling them directly here - a coroutine - would block this
            # single-threaded event loop for however long CT300 takes to
            # respond (up to its 10s timeout, confirmed by measuring it
            # directly against an unreachable address), freezing every
            # other request the app is serving and delaying the next sweep
            # tick by the same amount. asyncio.to_thread runs them on a
            # worker thread instead, so a slow/unreachable board only
            # delays this loop's own next iteration, not the whole app.
            count = await asyncio.to_thread(sweep_expired_reservations, db)
            if count:
                logger.info("Expiry sweep: %d reservation(s) expired", count)
            await asyncio.to_thread(sweep_logged_out_sessions, db)
        finally:
            db.close()


# The lab catalog (which boards exist, their CT300-equivalent
# addresses, which are public) used to be a hardcoded Python list here,
# duplicated by hand into the nginx config's lab_id->port map - the two
# drifted out of sync more than once. Both now derive from the single
# backend/labs.yaml file instead (see labs.yaml.example for the
# annotated format, and deploy/generate_nginx_config.py for the nginx
# side of this).
_LABS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "labs.yaml"


class _LabSeedEntry(BaseModel):
    id: int
    name: str
    description: str
    image_url: str | None = None
    backend_url: str | None = None
    keywords: list[str] | None = None
    features: list[str] | None = None
    is_public: bool = False
    guide_url: str | None = None


class _LabCatalogConfig(BaseModel):
    labfiles_host: str | None = None
    labs: list[_LabSeedEntry]


def _load_lab_catalog() -> list[_LabSeedEntry]:
    if not _LABS_CONFIG_PATH.is_file():
        raise RuntimeError(
            f"{_LABS_CONFIG_PATH} not found - copy labs.yaml.example to labs.yaml and "
            "edit it for your own hardware before starting the app."
        )
    with open(_LABS_CONFIG_PATH) as f:
        raw = yaml.safe_load(f)
    return _LabCatalogConfig.model_validate(raw).labs


def _seed_labs():
    db = SessionLocal()
    try:
        if db.query(Lab).count() == 0:
            entries = _load_lab_catalog()
            db.add_all(Lab(**entry.model_dump()) for entry in entries)
            db.commit()
            # The ids above were assigned explicitly (from labs.yaml), not
            # by Postgres's own auto-increment - bump its sequence past
            # the highest one so the next admin-created lab doesn't
            # collide with a seeded id. SQLite (used by tests) has no
            # such sequence to fix.
            if engine.dialect.name == "postgresql":
                db.execute(text("SELECT setval('labs_id_seq', :max_id)"), {"max_id": max(e.id for e in entries)})
                db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The schema is owned by Alembic now (see backend/alembic/), not created
    # here on startup - a production deploy runs `alembic upgrade head`
    # before the service starts, so the app must not silently create tables
    # that a pending migration was supposed to define. Seeding the lab
    # catalog is still fine: it's data, not schema, and no-ops if the labs
    # table is already populated. Tests build their own schema directly (see
    # tests/conftest.py) instead of going through Alembic.
    _seed_labs()
    # Promote/demote existing accounts to match the admin allowlist (config
    # root admins + granted admin_emails rows) so an allowlist change takes
    # effect on deploy without each user having to log in again.
    _db = SessionLocal()
    try:
        sync_all_admin_roles(_db)
    finally:
        _db.close()
    sweep_task = asyncio.create_task(_expiry_sweep_loop())
    yield
    sweep_task.cancel()


app = FastAPI(title="FPGA Remote Lab", lifespan=lifespan)

# Session cookie is the sole source of identity for every authenticated
# request - see app/deps.py::get_current_user. No CORS middleware is added
# on purpose: the frontend is served from the same origin, so the old
# repo's `Access-Control-Allow-Origin: *` has no equivalent here.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.session_cookie_secure,
    max_age=settings.session_max_age_days * 24 * 60 * 60,
)

# Everything lives under /api so it can never collide with a frontend
# route of the same name (e.g. GET /api/labs vs. the SPA's /labs page,
# both served from the same origin).
app.include_router(auth.router, prefix="/api")
app.include_router(labs.router, prefix="/api")
app.include_router(reservations.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
# Agents post here with their own bearer token, not a user session -
# see routers/inventory.py::authenticate_agent. The admin half is a
# separate router so the two audiences' permissions never share a
# dependency by accident.
app.include_router(inventory.router, prefix="/api")
app.include_router(inventory.admin_router, prefix="/api")

# Not under /api: nginx now reverse-proxies /hw/{lab_id}/* and
# /labfiles/* straight to CT300 itself (see
# /etc/nginx/sites-available/fpga-remote-lab on CT210), except for this
# one path - the in-lab "Log out" button needs our own database, so
# nginx carves POST /hw/{lab_id}/logout out to us specifically. Still
# registered before the SPA catch-all below so it takes precedence.
app.include_router(hardware_proxy.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve the built frontend (frontend/dist, a sibling of this backend/
# directory) from the same origin as the API. Any path that isn't an API
# route or an existing static asset falls back to index.html, so React
# Router's client-side routes (e.g. /dashboard) work on a hard refresh too.
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        candidate = _frontend_dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_frontend_dist / "index.html")
