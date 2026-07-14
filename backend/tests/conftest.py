import os

# CRITICAL: force the test suite onto an isolated throwaway sqlite database
# BEFORE any app module is imported. app.database builds its engine from
# settings at import time, and on the deployed server the real .env points
# DATABASE_URL at the *production* Postgres - without this override, the
# drop_all below wipes production on every test run (this happened: running
# pytest on CT210 silently destroyed the live database each time, masked
# only by the app's old startup create_all recreating empty tables). Setting
# the env var here wins over .env in pydantic-settings.
os.environ["DATABASE_URL"] = "sqlite:///./test_fpga_remote_lab.db"
# Registration's email deliverability check (see schemas.py) does a real
# DNS MX lookup - tests register with @example.com, a domain IANA
# reserves specifically to never accept mail, so it would always fail
# that check. Off here; still on by default everywhere else.
os.environ["VERIFY_EMAIL_DELIVERABILITY"] = "false"
# Deterministic root-admin allowlist for the tests, so they don't depend on
# the real Andrea/Yagiz addresses baked into config.py's defaults. Anyone
# registering with root@example.com is auto-promoted (see
# services/admin.py). Parsed as a JSON list by pydantic-settings.
os.environ["ADMIN_EMAILS"] = '["root@example.com"]'

import pytest

from app.database import Base, engine
from app.main import app

# Hard safety net: never let the suite run against anything but the
# throwaway sqlite file, even if the override above ever fails to take
# effect. drop_all against the wrong database is unrecoverable.
assert engine.url.get_backend_name() == "sqlite", (
    f"Refusing to run tests against a non-sqlite database: {engine.url!r}"
)


@pytest.fixture()
def client():
    """Fresh, empty database for every test.

    Tests build the schema straight from the models with create_all - fast,
    isolated, and independent of Alembic (production's schema is owned by
    migrations instead; see backend/alembic/). The app's lifespan only
    seeds the lab catalog now, not the schema, so tables must exist before
    the TestClient starts its lifespan. Dropping everything first
    guarantees each test starts from a clean slate regardless of order.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
