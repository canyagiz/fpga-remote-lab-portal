import pytest

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    """Fresh, empty database for every test.

    The app's lifespan handler re-creates tables and seeds the demo lab on
    each TestClient startup, so dropping everything first guarantees each
    test starts from a clean slate regardless of test order.
    """
    Base.metadata.drop_all(bind=engine)

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
