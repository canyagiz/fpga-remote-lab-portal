from tests.helpers import login, make_admin, register


def _create_lab(client):
    register(client, "admin", "admin@example.com")
    login(client, "admin")
    make_admin("admin")
    lab_id = client.post("/api/labs", json={"name": "Arty Z7", "description": "FPGA board"}).json()["id"]
    return lab_id


def test_stats_require_authentication(client):
    assert client.get("/api/stats/me").status_code == 401


def test_fresh_user_has_empty_stats_except_their_own_login(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    stats = client.get("/api/stats/me").json()
    assert stats["labs_demoed"] == []
    assert stats["labs_completed"] == []
    assert stats["total_reservations"] == 0
    assert stats["upcoming_count"] == 0
    # The login that fetched these stats is itself already on record.
    assert len(stats["login_times"]) == 1


def test_each_successful_login_is_recorded(client):
    """First login goes through the 2FA verify path, the second through
    plain /login (2FA disables itself after first verification) - both
    must land in the login history."""
    register(client, "user1", "user1@example.com")

    login(client, "user1")
    assert len(client.get("/api/stats/me").json()["login_times"]) == 1

    login(client, "user1")
    assert len(client.get("/api/stats/me").json()["login_times"]) == 2


def test_started_and_completed_sessions_show_up_in_lab_stats(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()

    # Started (demoed) the moment the session is active - but not
    # completed yet.
    stats = client.get("/api/stats/me").json()
    assert [s["lab_id"] for s in stats["labs_demoed"]] == [lab_id]
    assert stats["labs_demoed"][0]["session_count"] == 1
    assert stats["labs_completed"] == []

    client.post(f"/api/reservations/{resv['id']}/complete")

    stats = client.get("/api/stats/me").json()
    assert [s["lab_id"] for s in stats["labs_completed"]] == [lab_id]
    assert stats["completed_count"] == 1
    assert stats["total_reservations"] == 1


def test_cancelled_sessions_count_as_demoed_but_not_completed(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    client.post(f"/api/reservations/{resv['id']}/cancel")

    stats = client.get("/api/stats/me").json()
    assert stats["cancelled_count"] == 1
    assert stats["completed_count"] == 0
    # The session did run, so the lab still counts as demoed.
    assert [s["lab_id"] for s in stats["labs_demoed"]] == [lab_id]
    assert stats["labs_completed"] == []


def test_stats_are_scoped_to_the_current_user(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    client.post(f"/api/reservations/{resv['id']}/complete")

    login(client, "user2")
    stats = client.get("/api/stats/me").json()
    assert stats["total_reservations"] == 0
    assert stats["labs_demoed"] == []
    assert len(stats["login_times"]) == 1
