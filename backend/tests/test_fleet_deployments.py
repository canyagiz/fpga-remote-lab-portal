"""Binding a catalogue entry to a physical board.

This is the first part of the fleet work that touches what students see,
so the first thing proved here is that it changes nothing until an admin
opts a lab in. Everything after that covers the two behaviours a
deployment adds: the address comes from wherever the board actually is,
and a lab whose hardware is not fit to serve stops being offered.
"""

from tests.helpers import login, make_admin, register


def _admin(client):
    register(client, "root", "root@example.com")
    login(client, "root")


def _student(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")


BLASTER = {
    "kind": "programmer",
    "usb_vendor_id": "09fb",
    "usb_product_id": "6001",
    "usb_serial": "91d28408",
    "product": "USB-Blaster",
    "manufacturer": "Altera",
    "sysfs_path": "1-5.1",
    "signature": "altera-usb-blaster",
    "jtag": None,
}
MAGEWELL = {
    "kind": "video_capture",
    "usb_vendor_id": "2935",
    "usb_product_id": "0006",
    "usb_serial": "D206240701386",
    "product": "USB Capture HDMI",
    "manufacturer": "Magewell",
    "sysfs_path": "2-3.4",
    "signature": "magewell-usb-capture-hdmi",
    "jtag": None,
}


def _report(devices, signal=True):
    video = []
    if any(d["kind"] == "video_capture" for d in devices):
        video = [
            {
                "dev_node": "/dev/v4l/by-id/usb-Magewell_D206240701386-video-index0",
                "card": "USB Capture HDMI",
                "driver": "uvcvideo",
                "usb_serial": "D206240701386",
                "has_signal": signal,
            }
        ]
    return {
        "schema_version": "0.1",
        "agent_version": "0.1.0",
        "hostname": "docker",
        "scanned_at": "2026-07-21T14:00:00+00:00",
        "devices": devices,
        "video": video,
        "warnings": [],
    }


def _fleet(client, address="10.30.70.23", devices=None, signal=True):
    """Enrol a shuttle, give it an address, and report hardware."""
    body = client.post("/api/admin/fleet/shuttles", json={"name": "Shuttle A"}).json()
    shuttle_id, token = body["shuttle"]["id"], body["token"]
    if address:
        client.put(
            f"/api/admin/fleet/shuttles/{shuttle_id}/address", json={"address": address}
        )
    report = _report(devices if devices is not None else [BLASTER, MAGEWELL], signal)
    assert (
        client.post(
            "/api/inventory/report", json=report, headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 200
    )
    return shuttle_id, token


def _board(client, **overrides):
    payload = {
        "label": "EduPow CIV #10",
        "family": "cyclone_iv",
        "programmer_serial": "91d28408",
        # Which card watches this board, not merely that the shuttle has
        # one - a capture card serves a single board's HDMI output, so
        # the video check resolves through here.
        "video_capture_serial": "D206240701386",
    }
    payload.update(overrides)
    response = client.post("/api/admin/fleet/boards", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _template(client, requirements=None):
    if requirements is None:
        requirements = [
            {"type": "fpga", "family": "cyclone_iv"},
            {"type": "video_capture", "require_signal": True},
        ]
    response = client.post(
        "/api/admin/fleet/templates",
        json={"name": "Cyclone IV Vision Lab", "requirements": requirements},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _lab_id(client, name="Cyclone IV Lab"):
    return next(lab["id"] for lab in client.get("/api/labs").json() if lab["name"] == name)


def _deploy(client, lab_id, template_id, board_id, port=5001):
    return client.post(
        "/api/admin/fleet/deployments",
        json={
            "lab_id": lab_id,
            "template_id": template_id,
            "board_id": board_id,
            "port": port,
        },
    )


# ---- the safety property ---------------------------------------------

def test_labs_without_a_deployment_are_completely_unaffected(client):
    """The whole feature is opt-in. Until a lab is bound to a board it
    behaves exactly as it did before any of this existed."""
    _student(client)
    labs = client.get("/api/labs").json()
    assert len(labs) == 4
    for lab in labs:
        assert lab["deployment_status"] is None
        assert lab["unavailable_reason"] is None


def test_deleting_a_deployment_restores_the_previous_behaviour(client):
    _admin(client)
    _fleet(client)
    lab_id = _lab_id(client)
    deployment = _deploy(client, lab_id, _template(client), _board(client)).json()

    client.delete(f"/api/admin/fleet/deployments/{deployment['id']}")
    lab = next(lab for lab in client.get("/api/labs").json() if lab["id"] == lab_id)
    assert lab["deployment_status"] is None


# ---- address resolution ----------------------------------------------

def test_the_address_comes_from_the_shuttle_holding_the_board(client):
    _admin(client)
    _fleet(client, address="10.30.70.23")
    deployment = _deploy(client, _lab_id(client), _template(client), _board(client), port=5001).json()

    assert deployment["available"] is True
    assert deployment["backend_url"] == "http://10.30.70.23:5001"
    assert deployment["shuttle_name"] == "Shuttle A"


def test_a_shuttle_without_an_address_is_refused_not_guessed(client):
    """The address decides where a student's browser is sent, so it is
    admin-set; falling back to an agent-reported hostname would undo
    exactly that."""
    _admin(client)
    _fleet(client, address=None)
    deployment = _deploy(client, _lab_id(client), _template(client), _board(client)).json()

    assert deployment["available"] is False
    assert "no address configured" in deployment["reason"]


def test_an_unplugged_board_makes_the_lab_unavailable(client):
    _admin(client)
    _, token = _fleet(client)
    _deploy(client, _lab_id(client), _template(client), _board(client))

    # Everything is unplugged from the shuttle.
    client.post(
        "/api/inventory/report",
        json=_report([]),
        headers={"Authorization": f"Bearer {token}"},
    )
    deployment = client.get("/api/admin/fleet/deployments").json()[0]
    assert deployment["available"] is False
    assert "not attached to any shuttle" in deployment["reason"]


# ---- hiding an unhealthy lab -----------------------------------------

def test_a_lab_with_a_dark_capture_card_is_withdrawn_from_the_catalogue(client):
    """Today this failure is found by a student, mid-session, as a black
    video feed."""
    _admin(client)
    _fleet(client, signal=False)
    lab_id = _lab_id(client)
    _deploy(client, lab_id, _template(client), _board(client))

    # The admin still sees it, with the reason.
    admin_view = next(lab for lab in client.get("/api/labs").json() if lab["id"] == lab_id)
    assert admin_view["deployment_status"] == "unavailable"
    assert "no HDMI signal" in admin_view["unavailable_reason"]

    # The student does not see it at all.
    _student(client)
    assert all(lab["id"] != lab_id for lab in client.get("/api/labs").json())


def test_a_healthy_lab_stays_visible_to_students(client):
    _admin(client)
    _fleet(client, signal=True)
    lab_id = _lab_id(client)
    _deploy(client, lab_id, _template(client), _board(client))

    _student(client)
    visible = {lab["id"] for lab in client.get("/api/labs").json()}
    assert lab_id in visible


def test_access_is_refused_even_with_a_direct_link(client):
    """Hiding a lab from a list is not access control - a user who
    already had a reservation still holds a working link."""
    _admin(client)
    _fleet(client, signal=False)
    lab_id = _lab_id(client)
    _deploy(client, lab_id, _template(client), _board(client))

    _student(client)
    response = client.get(f"/api/labs/{lab_id}/access")
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_an_admin_can_take_a_lab_out_of_service_without_unbinding_it(client):
    _admin(client)
    _fleet(client)
    lab_id = _lab_id(client)
    deployment_id = _deploy(client, lab_id, _template(client), _board(client)).json()["id"]

    paused = client.post(
        f"/api/admin/fleet/deployments/{deployment_id}/enable?enabled=false"
    ).json()
    assert paused["available"] is False
    assert "administrator" in paused["reason"]

    _student(client)
    assert all(lab["id"] != lab_id for lab in client.get("/api/labs").json())


# ---- guards ----------------------------------------------------------

def test_a_lab_can_only_be_bound_once(client):
    _admin(client)
    _fleet(client)
    lab_id, template_id, board_id = _lab_id(client), _template(client), _board(client)
    assert _deploy(client, lab_id, template_id, board_id).status_code == 201
    assert _deploy(client, lab_id, template_id, board_id).status_code == 409


def test_deployment_management_is_admin_only(client):
    _student(client)
    assert client.get("/api/admin/fleet/deployments").status_code == 403
    assert (
        client.post(
            "/api/admin/fleet/deployments",
            json={"lab_id": 1, "template_id": 1, "board_id": 1, "port": 5001},
        ).status_code
        == 403
    )


# ---- strict policy: only bound + healthy labs are served ----------------
#
# conftest keeps require_deployment_for_access off for the suite at large
# (most tests access labs without binding). These turn it on explicitly to
# cover the option where an unbound lab is not offered at all.

def test_strict_policy_hides_unbound_labs_from_students(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "require_deployment_for_access", True)
    _admin(client)

    # Nothing bound yet: an admin still sees the catalogue, a student sees
    # none of it.
    admin_labs = client.get("/api/labs").json()
    assert len(admin_labs) == 4
    assert all(lab["deployment_status"] == "unavailable" for lab in admin_labs)

    _student(client)
    assert client.get("/api/labs").json() == []


def test_strict_policy_serves_a_bound_healthy_lab_only(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "require_deployment_for_access", True)
    _admin(client)
    _fleet(client, signal=True)
    lab_id = _lab_id(client)
    _deploy(client, lab_id, _template(client), _board(client))

    # The bound lab is served; the other three, unbound, are not.
    _student(client)
    visible = {lab["id"] for lab in client.get("/api/labs").json()}
    assert visible == {lab_id}


def test_strict_policy_refuses_access_to_an_unbound_lab(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "require_deployment_for_access", True)
    register(client, "root", "root@example.com")
    login(client, "root")
    # Any lab that has no deployment - access must be refused even with a
    # direct link, not just hidden from the list.
    some_lab = client.get("/api/labs").json()[0]["id"]
    response = client.get(f"/api/labs/{some_lab}/access")
    assert response.status_code in (403, 503)
