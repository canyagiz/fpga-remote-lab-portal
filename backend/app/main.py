import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Lab
from app.routers import auth, labs, reservations
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


def _seed_demo_lab():
    db = SessionLocal()
    try:
        if db.query(Lab).count() == 0:
            db.add(Lab(name="Demo Lab", description="Placeholder lab for testing auth and queue flows."))
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _seed_demo_lab()
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
)

app.include_router(auth.router)
app.include_router(labs.router)
app.include_router(reservations.router)


@app.get("/health")
def health():
    return {"status": "ok"}
