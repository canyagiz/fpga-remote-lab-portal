"""Fleet inventory: enrolment, agent authentication, and ingest.

conftest.py sets ADMIN_EMAILS=["root@example.com"], so registering with
that address auto-promotes.

The reports below are shaped exactly like real scanner output measured on
pc-3vrl07 - a USB-Blaster and a Magewell with their genuine serials, and
the Arty's two-device JTAG chain (an ARM core alongside the fabric). Using
the real shapes is deliberate: the two bugs this file guards against
(collapsing a chain to one device, and losing a capture card's signal
state to its second /dev node) both came from assuming simpler data than
the hardware actually produces.
"""

from tests.helpers import login, make_admin, register


def _enrol(client, name="Shuttle A", role="worker"):
    response = client.post("/api/admin/fleet/shuttles", json={"name": name, "role": role})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["shuttle"]["id"], body["token"]


def _report(**overrides):
    report = {
        "schema_version": "0.1",
        "agent_version": "0.1.0",
        "hostname": "docker",
        "scanned_at": "2026-07-21T14:00:00+00:00",
        "machine_id": "abc123",
        "devices": [
            {
                "kind": "programmer",
                "usb_vendor_id": "09fb",
                "usb_product_id": "6001",
                "usb_serial": "91d28408",
                "product": "USB-Blaster",
                "manufacturer": "Altera",
                "sysfs_path": "1-5.1",
                "signature": "altera-usb-blaster",
                "jtag": None,
            },
            {
                "kind": "video_capture",
                "usb_vendor_id": "2935",
                "usb_product_id": "0006",
                "usb_serial": "D206240701386",
                "product": "USB Capture HDMI",
                "manufacturer": "Magewell",
                "sysfs_path": "2-3.4",
                "signature": "magewell-usb-capture-hdmi",
                "jtag": None,
            },
        ],
        "video": [
            {
                "dev_node": "/dev/v4l/by-id/usb-Magewell_..._D206240701386-video-index0",
                "card": "USB Capture HDMI",
                "driver": "uvcvideo",
                "usb_serial": "D206240701386",
                "has_signal": True,
            },
            {
                "dev_node": "/dev/v4l/by-id/usb-Magewell_..._D206240701386-video-index1",
                "card": "USB Capture HDMI",
                "driver": "uvcvideo",
                "usb_serial": "D206240701386",
                "has_signal": None,
            },
        ],
        "warnings": [],
    }
    report.update(overrides)
    return report


def _post(client, token, report):
    return client.post(
        "/api/inventory/report",
        json=report,
        headers={"Authorization": f"Bearer {token}"},
    )


# ---- enrolment -------------------------------------------------------

def test_enrolment_requires_admin(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")
    assert client.post("/api/admin/fleet/shuttles", json={"name": "X"}).status_code == 403
    assert client.get("/api/admin/fleet/shuttles").status_code == 403


def test_enrolment_returns_a_token_only_once(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    shuttle_id, token = _enrol(client)

    assert token.startswith(f"frl_{shuttle_id}_")
    # The plaintext must never be retrievable afterwards - only its hash
    # is stored, so a database read cannot yield a working credential.
    listing = client.get("/api/admin/fleet/shuttles").json()
    assert token not in str(listing)


def test_shuttle_names_are_unique_case_insensitively(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    _enrol(client, "Shuttle A")
    duplicate = client.post("/api/admin/fleet/shuttles", json={"name": "shuttle a"})
    assert duplicate.status_code == 409


# ---- agent authentication -------------------------------------------

def test_report_rejects_missing_and_bogus_tokens(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    shuttle_id, token = _enrol(client)

    assert client.post("/api/inventory/report", json=_report()).status_code == 401
    for bad in ["nonsense", "frl_1_wrong", f"frl_999_{token.split('_', 2)[2]}"]:
        response = client.post(
            "/api/inventory/report",
            json=_report(),
            headers={"Authorization": f"Bearer {bad}"},
        )
        assert response.status_code == 401, bad


def test_agent_token_cannot_reach_anything_else(client):
    """A stolen agent token must buy exactly one endpoint."""
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)
    client.cookies.clear()

    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/admin/fleet/shuttles", headers=headers).status_code == 401
    assert client.get("/api/admin/users", headers=headers).status_code == 401
    assert client.get("/api/labs", headers=headers).status_code == 401


def test_rotating_a_token_invalidates_the_old_one(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    shuttle_id, old_token = _enrol(client)
    assert _post(client, old_token, _report()).status_code == 200

    new_token = client.post(
        f"/api/admin/fleet/shuttles/{shuttle_id}/rotate-token"
    ).json()["token"]
    assert new_token != old_token
    assert _post(client, old_token, _report()).status_code == 401
    assert _post(client, new_token, _report()).status_code == 200


def test_identity_comes_from_the_token_not_the_body(client):
    """Two shuttles, and one cannot overwrite the other's inventory."""
    register(client, "root", "root@example.com")
    login(client, "root")
    first_id, first_token = _enrol(client, "Shuttle A")
    second_id, second_token = _enrol(client, "Shuttle B")

    _post(client, first_token, _report())
    # B reports nothing at all, while claiming A's hostname.
    _post(client, second_token, _report(hostname="docker", devices=[], video=[]))

    a_devices = client.get(f"/api/admin/fleet/devices?shuttle_id={first_id}").json()
    b_devices = client.get(f"/api/admin/fleet/devices?shuttle_id={second_id}").json()
    assert len(a_devices) == 2
    assert b_devices == []


# ---- ingest ----------------------------------------------------------

def test_report_records_devices_and_marks_shuttle_online(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    shuttle_id, token = _enrol(client)

    response = _post(client, token, _report())
    assert response.status_code == 200, response.text
    assert response.json()["devices_recorded"] == 2

    shuttle = client.get("/api/admin/fleet/shuttles").json()[0]
    assert shuttle["status"] == "online"
    assert shuttle["agent_version"] == "0.1.0"
    assert shuttle["device_count"] == 2


def test_video_signal_binds_to_the_capture_device_by_serial(client):
    """The card exposes two /dev nodes and only the first answers.

    Taking the last node's answer would report a working capture card as
    unknown, so a positive answer from any node has to win.
    """
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)
    _post(client, token, _report())

    devices = client.get("/api/admin/fleet/devices").json()
    capture = next(d for d in devices if d["kind"] == "video_capture")
    programmer = next(d for d in devices if d["kind"] == "programmer")
    assert capture["has_video_signal"] is True
    # A programmer has no video state at all - not False, which would
    # read as a fault.
    assert programmer["has_video_signal"] is None


def test_a_whole_jtag_chain_is_kept(client):
    """A Zynq puts its ARM core on the chain next to the fabric."""
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)

    arty = {
        "kind": "programmer",
        "usb_vendor_id": "0403",
        "usb_product_id": "6010",
        "usb_serial": "003017A6FDC3",
        "product": "Digilent Adept USB Device",
        "manufacturer": "Digilent",
        "sysfs_path": "1-5.2",
        "signature": "ftdi-ft2232",
        "jtag": {
            "tool": "openfpgaloader",
            "ok": True,
            "devices": [
                {"idcode": "0x4ba00477", "name": None, "kind": "ARM cortex A9"},
                {"idcode": "0x3727093", "name": "xc7z020", "kind": "zynq"},
            ],
            "error": None,
        },
    }
    _post(client, token, _report(devices=[arty], video=[]))

    device = client.get("/api/admin/fleet/devices").json()[0]
    assert [d["idcode"] for d in device["jtag_chain"]] == ["0x4ba00477", "0x3727093"]


def test_a_passive_rescan_does_not_erase_a_known_chain(client):
    """Probing is disruptive and rare, so its results have to survive the
    ordinary passive scans that carry jtag=None."""
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)

    probed = {
        "kind": "programmer",
        "usb_vendor_id": "09fb",
        "usb_product_id": "6001",
        "usb_serial": "91d28408",
        "product": "USB-Blaster",
        "manufacturer": "Altera",
        "sysfs_path": "1-5.1",
        "signature": "altera-usb-blaster",
        "jtag": {
            "tool": "quartus",
            "ok": True,
            "devices": [{"idcode": "0x020F30DD", "name": "EP4CE22", "kind": None}],
            "error": None,
        },
    }
    _post(client, token, _report(devices=[probed], video=[]))
    passive = {**probed, "jtag": None}
    _post(client, token, _report(devices=[passive], video=[]))

    device = client.get("/api/admin/fleet/devices").json()[0]
    assert device["jtag_chain"][0]["idcode"] == "0x020F30DD"


def test_unplugged_hardware_is_marked_absent_not_deleted(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)
    _post(client, token, _report())

    # The capture card is pulled; only the programmer is still reported.
    only_programmer = [_report()["devices"][0]]
    _post(client, token, _report(devices=only_programmer, video=[]))

    assert len(client.get("/api/admin/fleet/devices").json()) == 1
    history = client.get("/api/admin/fleet/devices?include_absent=true").json()
    assert len(history) == 2
    absent = next(d for d in history if not d["is_present"])
    assert absent["usb_serial"] == "D206240701386"


def test_a_device_keeps_its_row_when_moved_to_another_port(client):
    """Identity is the serial, not the port path - that is the whole
    reason it is bound to the serial."""
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)
    _post(client, token, _report())
    original = client.get("/api/admin/fleet/devices").json()
    original_id = next(d for d in original if d["usb_serial"] == "91d28408")["id"]

    moved = _report()
    moved["devices"][0]["sysfs_path"] = "1-6.4"
    _post(client, token, moved)

    devices = client.get("/api/admin/fleet/devices").json()
    blaster = next(d for d in devices if d["usb_serial"] == "91d28408")
    assert blaster["id"] == original_id
    assert blaster["sysfs_path"] == "1-6.4"
    assert len(devices) == 2


def test_a_schema_skew_is_a_notice_not_a_rejection(client):
    """Agents are deployed per shuttle and will run ahead of the master."""
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)

    response = _post(client, token, _report(schema_version="0.2"))
    assert response.status_code == 200
    assert any("schema" in notice for notice in response.json()["notices"])


def test_oversized_reports_are_refused(client):
    """A compromised agent must not be able to push unbounded data."""
    register(client, "root", "root@example.com")
    login(client, "root")
    _, token = _enrol(client)

    flood = [dict(_report()["devices"][0], usb_serial=f"s{n}") for n in range(200)]
    assert _post(client, token, _report(devices=flood, video=[])).status_code == 422

    long_serial = _report()
    long_serial["devices"][0]["usb_serial"] = "x" * 500
    assert _post(client, token, long_serial).status_code == 422


def test_removing_a_shuttle_takes_its_devices(client):
    register(client, "root", "root@example.com")
    login(client, "root")
    shuttle_id, token = _enrol(client)
    _post(client, token, _report())

    assert client.delete(f"/api/admin/fleet/shuttles/{shuttle_id}").status_code == 200
    assert client.get("/api/admin/fleet/devices").json() == []
    assert _post(client, token, _report()).status_code == 401
