"""Boards, lab templates, and the gap report.

This is the feature the fleet system exists for: say once what a lab
needs, and have the system keep answering where it can run and what is
stopping it elsewhere.

The scenarios use the real lab's shapes - a Cyclone IV behind an
Altera USB-Blaster with a Magewell capture card, an Arty Z7 behind a
Digilent FTDI programmer - because the interesting failures are the ones
the hardware actually produces, not the ones a tidy fixture would.
"""

from tests.helpers import login, register


def _admin(client):
    register(client, "root", "root@example.com")
    login(client, "root")


def _enrol(client, name="Shuttle A"):
    response = client.post("/api/admin/fleet/shuttles", json={"name": name})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["shuttle"]["id"], body["token"]


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
FTDI = {
    "kind": "programmer",
    "usb_vendor_id": "0403",
    "usb_product_id": "6010",
    "usb_serial": "003017A6FDC3",
    "product": "Digilent Adept USB Device",
    "manufacturer": "Digilent",
    "sysfs_path": "1-5.2",
    "signature": "ftdi-ft2232",
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


def _report(devices, video=None):
    return {
        "schema_version": "0.1",
        "agent_version": "0.1.0",
        "hostname": "docker",
        "scanned_at": "2026-07-21T14:00:00+00:00",
        "devices": devices,
        "video": video or [],
        "warnings": [],
    }


def _signal(serial, has_signal):
    return [
        {
            "dev_node": f"/dev/v4l/by-id/usb-Magewell_{serial}-video-index0",
            "card": "USB Capture HDMI",
            "driver": "uvcvideo",
            "usb_serial": serial,
            "has_signal": has_signal,
        }
    ]


def _post(client, token, report):
    response = client.post(
        "/api/inventory/report", json=report, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text


def _register_board(client, **overrides):
    payload = {
        "label": "EduPow CIV #10",
        "family": "cyclone_iv",
        "programmer_serial": "91d28408",
    }
    payload.update(overrides)
    return client.post("/api/admin/fleet/boards", json=payload)


def _template(client, name="Cyclone IV Vision Lab", requirements=None):
    if requirements is None:
        requirements = [
            {"type": "fpga", "family": "cyclone_iv"},
            {"type": "video_capture", "require_signal": True},
        ]
    response = client.post(
        "/api/admin/fleet/templates",
        json={"name": name, "requirements": requirements},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---- boards ----------------------------------------------------------

def test_unclaimed_queue_lists_programmers_no_board_owns(client):
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER, FTDI, MAGEWELL]))

    unclaimed = client.get("/api/admin/fleet/boards/unclaimed").json()
    serials = {d["usb_serial"] for d in unclaimed}
    # Both programmers await a human; the capture card is not a board.
    assert serials == {"91d28408", "003017A6FDC3"}

    _register_board(client)
    remaining = client.get("/api/admin/fleet/boards/unclaimed").json()
    assert {d["usb_serial"] for d in remaining} == {"003017A6FDC3"}


def test_a_board_cannot_claim_a_serial_nothing_reported(client):
    _admin(client)
    _enrol(client)
    response = _register_board(client, programmer_serial="typo-serial")
    assert response.status_code == 400
    assert "No shuttle has reported" in response.json()["detail"]


def test_one_board_per_programmer(client):
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER]))
    assert _register_board(client).status_code == 201
    duplicate = _register_board(client, label="Another label")
    assert duplicate.status_code == 409


def test_a_board_follows_its_programmer_between_shuttles(client):
    """The point of binding identity to the serial: moving hardware needs
    no edit anywhere."""
    _admin(client)
    first_id, first_token = _enrol(client, "Shuttle A")
    second_id, second_token = _enrol(client, "Shuttle B")
    _post(client, first_token, _report([BLASTER]))
    _register_board(client)

    board = client.get("/api/admin/fleet/boards").json()[0]
    assert board["shuttle_id"] == first_id

    # The cable is unplugged from A and plugged into B.
    _post(client, first_token, _report([]))
    _post(client, second_token, _report([BLASTER]))

    board = client.get("/api/admin/fleet/boards").json()[0]
    assert board["shuttle_id"] == second_id
    assert board["shuttle_name"] == "Shuttle B"


# ---- templates -------------------------------------------------------

def test_a_template_with_an_unknown_requirement_is_refused(client):
    """Storing a shape the engine cannot parse would fail later, at
    evaluation time, with no clue where it came from."""
    _admin(client)
    response = client.post(
        "/api/admin/fleet/templates",
        json={"name": "Broken", "requirements": [{"type": "teleporter"}]},
    )
    assert response.status_code == 422


# ---- the gap report --------------------------------------------------

def test_a_fully_satisfied_lab_is_deployable(client):
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER, MAGEWELL], _signal("D206240701386", True)))
    _register_board(client)
    template_id = _template(client)

    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    assert report["deployable"] is True
    assert report["missing_count"] == 0
    assert all(r["status"] == "satisfied" for r in report["results"])


def test_missing_hardware_is_named(client):
    _admin(client)
    _, token = _enrol(client)
    # Board present, capture card absent.
    _post(client, token, _report([BLASTER]))
    _register_board(client)
    template_id = _template(client)

    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    assert report["deployable"] is False
    assert report["missing_count"] == 1
    video = next(r for r in report["results"] if r["type"] == "video_capture")
    assert video["status"] == "missing"
    assert "capture" in video["message"].lower()


def test_present_but_dark_capture_card_is_degraded_not_missing(client):
    """"Buy one" and "check the cable" are different instructions."""
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER, MAGEWELL], _signal("D206240701386", False)))
    _register_board(client)
    template_id = _template(client)

    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    video = next(r for r in report["results"] if r["type"] == "video_capture")
    assert video["status"] == "degraded"
    assert "no HDMI signal" in video["message"]
    # Degraded still blocks deployment - a lab that looks fine in the
    # catalogue and fails once a student is inside it is worse than one
    # that is honestly unavailable.
    assert report["deployable"] is False


def test_unknown_signal_state_does_not_fail_a_lab(client):
    """A driver that will not answer is not a fault."""
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER, MAGEWELL], _signal("D206240701386", None)))
    _register_board(client)
    template_id = _template(client)

    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    assert report["deployable"] is True
    video = next(r for r in report["results"] if r["type"] == "video_capture")
    assert "unknown" in video["message"]


def test_an_unexpected_idcode_is_flagged_rather_than_reinterpreted(client):
    """Hardware may have been swapped behind the cable - a question for a
    human, not a decision for the system."""
    _admin(client)
    _, token = _enrol(client)
    probed = dict(
        BLASTER,
        jtag={
            "tool": "quartus",
            "ok": True,
            "devices": [{"idcode": "0x02B150DD", "name": "5CEBA4", "kind": None}],
            "error": None,
        },
    )
    _post(client, token, _report([probed, MAGEWELL], _signal("D206240701386", True)))
    _register_board(client, expected_idcode="0x020F30DD")
    template_id = _template(client)

    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    fpga = next(r for r in report["results"] if r["type"] == "fpga")
    assert fpga["status"] == "degraded"
    assert "hardware may have changed" in fpga["message"]


def test_the_same_lab_is_compared_against_every_shuttle(client):
    """The question is not "does this work" but "where does this work"."""
    _admin(client)
    _, a_token = _enrol(client, "Shuttle A")
    _, b_token = _enrol(client, "Shuttle B")
    # A has the board but no capture card; B has both.
    _post(client, a_token, _report([BLASTER]))
    _post(client, b_token, _report([FTDI, MAGEWELL], _signal("D206240701386", True)))
    _register_board(client)
    _register_board(client, label="Arty #1", family="zynq_7020", programmer_serial="003017A6FDC3")

    arty_template = _template(
        client,
        name="Arty Vision Lab",
        requirements=[
            {"type": "fpga", "family": "zynq_7020"},
            {"type": "programmer", "signature": "ftdi-ft2232"},
            {"type": "video_capture", "require_signal": True},
        ],
    )
    reports = client.get(f"/api/admin/fleet/templates/{arty_template}/gaps").json()
    by_shuttle = {r["shuttle_name"]: r for r in reports}
    assert by_shuttle["Shuttle A"]["deployable"] is False
    assert by_shuttle["Shuttle B"]["deployable"] is True


def test_a_programmer_requirement_distinguishes_toolchains(client):
    """A Xilinx lab needs an FTDI programmer, not just any cable."""
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER]))

    template_id = _template(
        client,
        name="Xilinx only",
        requirements=[{"type": "programmer", "signature": "ftdi-ft2232"}],
    )
    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    assert report["results"][0]["status"] == "missing"


def test_gpio_reports_configuration_and_says_it_is_unverified(client):
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER]))
    template_id = _template(client, name="Needs GPIO", requirements=[{"type": "gpio"}])

    _register_board(client)
    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    assert report["results"][0]["status"] == "missing"

    client.delete(f"/api/admin/fleet/boards/{client.get('/api/admin/fleet/boards').json()[0]['id']}")
    _register_board(client, gpio_endpoint="10.30.70.50:20000")
    report = client.get(f"/api/admin/fleet/templates/{template_id}/gaps").json()[0]
    assert report["results"][0]["status"] == "satisfied"
    # Honest about what was actually checked.
    assert "not probed" in report["results"][0]["message"]


# ---- the spare side --------------------------------------------------

def test_hardware_no_template_wants_is_reported_as_spare(client):
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER, FTDI, MAGEWELL], _signal("D206240701386", True)))
    _register_board(client)
    _register_board(client, label="Arty #1", family="zynq_7020", programmer_serial="003017A6FDC3")
    # Only the Cyclone lab exists, so the Arty is sitting idle.
    _template(client)

    spare = client.get("/api/admin/fleet/unused").json()
    assert {d["usb_serial"] for d in spare} == {"003017A6FDC3"}


def test_nothing_is_spare_before_any_template_exists(client):
    """With nothing declaring a need, every device would trivially count
    as unused - and a list of all the hardware under "no lab template
    asks for it" reads as a fault when the real state is just that no
    templates have been written yet."""
    _admin(client)
    _, token = _enrol(client)
    _post(client, token, _report([BLASTER, FTDI, MAGEWELL], _signal("D206240701386", True)))
    _register_board(client)

    assert client.get("/api/admin/fleet/unused").json() == []


def test_admin_only(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")
    for path in ["boards", "boards/unclaimed", "templates", "gaps", "unused"]:
        assert client.get(f"/api/admin/fleet/{path}").status_code == 403
