import os

# Tests call drop_all() on every run (see the fixture below), so they must
# never point at a real database. app.config.Settings reads DATABASE_URL
# from .env at import time, and CT210's .env holds the production Postgres
# URL - without this override, importing app.database/app.main below would
# wipe the live users/reservations/labs tables on every `pytest` run. This
# is exactly what happened during development: real registered accounts
# were being deleted every time the suite ran to verify a change.
os.environ["DATABASE_URL"] = "sqlite:///./test_fpga_remote_lab.db"

import pytest

from app.config import settings
from app.database import Base, engine
from app.main import app

assert not settings.database_url.startswith("postgresql"), (
    "Refusing to run tests: DATABASE_URL resolved to a Postgres database. "
    "Tests drop all tables on every run and must only ever target the "
    "dedicated SQLite test database set at the top of this file."
)


@pytest.fixture()
def client():
    """Fresh, empty database for every test.

    The app's lifespan handler re-creates tables and seeds the real lab
    catalog (see app/main.py::_seed_labs) on each TestClient startup, so
    dropping everything first guarantees each test starts from a clean
    slate regardless of test order.
    """
    Base.metadata.drop_all(bind=engine)

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
