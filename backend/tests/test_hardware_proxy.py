from unittest.mock import AsyncMock, MagicMock, patch

from tests.helpers import login, make_admin, register


def _create_lab(client):
    register(client, "admin", "admin@example.com")
    login(client, "admin")
    make_admin("admin")
    lab_id = client.post(
        "/api/labs", json={"name": "Arty Z7", "description": "FPGA board", "backend_url": "http://10.30.70.23:5003"}
    ).json()["id"]
    return lab_id


class _FakeUpstreamResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = {"content-type": "application/json"}

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def _mock_httpx_client(fake_response):
    """For the buffered logout path: `async with httpx.AsyncClient() as
    client: await client.request(...)`."""
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def test_successful_in_lab_logout_closes_the_reservation_immediately(client):
    """Regression test: closing a session used to only be noticed by the
    background sweep, up to expiry_sweep_interval_seconds later. A
    successful logout response proxied through /hw/{lab_id}/logout must
    close the reservation in the same request - no waiting.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    fake_response = _FakeUpstreamResponse(json_data={"error": False}, content=b'{"error": false}')
    with patch("app.routers.hardware_proxy.httpx.AsyncClient", return_value=_mock_httpx_client(fake_response)):
        response = client.post(f"/hw/{lab_id}/logout", data={"csrf": "whatever"})

    assert response.status_code == 200
    mine = client.get("/api/reservations/mine").json()
    assert mine == []


def test_failed_in_lab_logout_leaves_the_reservation_active(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    fake_response = _FakeUpstreamResponse(
        json_data={"error": True, "message": "Invalid CSRF"}, content=b'{"error": true}'
    )
    with patch("app.routers.hardware_proxy.httpx.AsyncClient", return_value=_mock_httpx_client(fake_response)):
        client.post(f"/hw/{lab_id}/logout", data={"csrf": "wrong"})

    mine = client.get("/api/reservations/mine").json()
    assert mine[0]["status"] == "active"
