"""Admin allowlist + admin-panel management.

conftest.py sets ADMIN_EMAILS=["root@example.com"], so registering with
that address auto-promotes; everyone else starts as a plain user.
"""

from tests.helpers import login, make_admin, register


def _role_of(username):
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == username).first().role.value
    finally:
        db.close()


def test_root_email_is_auto_admin_on_register(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    assert _role_of("root") == "admin"
    # and can actually reach the admin API
    assert client.get("/api/admin/users").status_code == 200


def test_plain_user_is_not_admin(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")
    assert _role_of("alice") == "user"
    assert client.get("/api/admin/users").status_code == 403


def test_admin_grants_existing_user(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    register(client, "alice", "alice@example.com")

    resp = client.post("/api/admin/admins", json={"email": "alice@example.com"})
    assert resp.status_code == 200, resp.text
    assert _role_of("alice") == "admin"

    # alice can now use the admin API, and stays admin across a fresh login
    login(client, "alice")
    assert _role_of("alice") == "admin"
    assert client.get("/api/admin/users").status_code == 200


def test_grant_pending_email_promotes_on_register(client):
    register(client, "root", "root@example.com")
    login(client, "root")

    # grant an address nobody has registered with yet
    resp = client.post("/api/admin/admins", json={"email": "future@example.com"})
    assert resp.status_code == 200, resp.text

    # when they register + log in, they come up as admin automatically
    register(client, "future", "future@example.com")
    login(client, "future")
    assert _role_of("future") == "admin"


def test_revoke_demotes_immediately(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    register(client, "alice", "alice@example.com")
    client.post("/api/admin/admins", json={"email": "alice@example.com"})
    assert _role_of("alice") == "admin"

    resp = client.delete("/api/admin/admins/alice@example.com")
    assert resp.status_code == 200, resp.text
    assert _role_of("alice") == "user"

    # alice's still-valid session no longer passes require_admin
    login(client, "alice")
    assert client.get("/api/admin/users").status_code == 403


def test_cannot_revoke_root_admin(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    resp = client.delete("/api/admin/admins/root@example.com")
    assert resp.status_code == 403


def test_cannot_delete_root_admin(client):
    register(client, "root", "root@example.com")
    root_id = login(client, "root")
    # even another admin can't delete the root
    register(client, "alice", "alice@example.com")
    client.post("/api/admin/admins", json={"email": "alice@example.com"})
    login(client, "alice")
    resp = client.delete(f"/api/admin/users/{root_id}")
    assert resp.status_code == 403


def test_member_detail_exposes_profile_and_history(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    lab_id = client.post("/api/labs", json={"name": "Arty Z7", "description": "board"}).json()["id"]

    register(client, "bob", "bob@example.com")
    bob_id = login(client, "bob")
    client.put("/api/profile", json={"full_name": "Bob Builder", "is_public": False})
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    login(client, "root")
    detail = client.get(f"/api/admin/users/{bob_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # admin sees the profile even though bob set it private
    assert body["profile"]["full_name"] == "Bob Builder"
    assert len(body["reservations"]) == 1
    assert body["reservations"][0]["lab_name"] == "Arty Z7"


def test_grant_requires_admin(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")
    assert client.post("/api/admin/admins", json={"email": "x@example.com"}).status_code == 403


def test_list_admins_includes_root_and_granted(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    register(client, "alice", "alice@example.com")
    client.post("/api/admin/admins", json={"email": "alice@example.com"})

    admins = client.get("/api/admin/admins").json()
    by_email = {a["email"].lower(): a for a in admins}
    assert by_email["root@example.com"]["is_root_admin"] is True
    assert by_email["alice@example.com"]["is_root_admin"] is False
    assert by_email["alice@example.com"]["is_registered"] is True
