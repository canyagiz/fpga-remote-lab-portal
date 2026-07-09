import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Lab
from app.routers import auth, labs, reservations, users
from app.services.queue import sweep_expired_reservations

logger = logging.getLogger("fpga_remote_lab")


async def _expiry_sweep_loop():
    while True:
        await asyncio.sleep(settings.expiry_sweep_interval_seconds)
        db = SessionLocal()
        try:
            count = sweep_expired_reservations(db)
            if count:
                logger.info("Expiry sweep: %d reservation(s) expired", count)
        finally:
            db.close()


# Metadata mirrors CT200's laboratories.yml/resources.yml (the LabDiscoveryEngine
# portal this replaces). backend_url points directly at the CT300 hardware
# containers (network_mode: host, one per board) instead of through CT200's
# proxy path. Only Arty Z7 is public for now, matching CT200's current
# live behavior where the other three boards aren't yet exposed.
_REAL_LABS = [
    dict(
        name="Cyclone 10 Lab",
        description="Access an FPGA board with a Cyclone 10 FPGA for image processing",
        image_url="/labs/EduPow_CX.jpg",
        backend_url="http://10.30.70.23:5000",
        keywords=["fpga", "electronics", "image processing", "cyclone10"],
        features=["feature1", "feature2"],
        is_public=False,
    ),
    dict(
        name="Cyclone IV Lab",
        description="Access an FPGA board with a Cyclone IV FPGA for image processing",
        image_url="/labs/EduPow_CIV.jpg",
        backend_url="http://10.30.70.23:5001",
        keywords=["fpga", "electronics", "image processing", "cyclone4"],
        features=["feature1", "feature2"],
        is_public=False,
    ),
    dict(
        name="Cyclone V Lab",
        description="Access an FPGA board with a Cyclone V FPGA for image processing",
        image_url="/labs/EduPow_CV.jpg",
        backend_url="http://10.30.70.23:5002",
        keywords=["fpga", "electronics", "image processing", "cyclone5"],
        features=["feature1", "feature2"],
        is_public=False,
    ),
    dict(
        name="Arty Z7 Lab",
        description="Access an FPGA board with a Xilinx Zynq-7020 FPGA for image processing",
        image_url="/labs/EduPow_Z7.png",
        backend_url="http://10.30.70.23:5003",
        keywords=["fpga", "electronics", "image processing", "xilinx", "zynq"],
        features=["feature1", "feature2"],
        is_public=True,
    ),
]


def _seed_labs():
    db = SessionLocal()
    try:
        if db.query(Lab).count() == 0:
            db.add_all(Lab(**lab_kwargs) for lab_kwargs in _REAL_LABS)
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _seed_labs()
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
app.include_router(users.router, prefix="/api")


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
