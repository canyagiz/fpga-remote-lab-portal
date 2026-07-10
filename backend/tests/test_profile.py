from tests.helpers import login, register


def test_new_user_has_an_empty_profile(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json() == {
        "full_name": None,
        "school": None,
        "department": None,
        "age": None,
        "bio": None,
        "social_links": None,
    }


def test_update_profile_persists_fields(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    payload = {
        "full_name": "Ali Yagiz",
        "school": "H-BRS",
        "department": "Electrical Engineering",
        "age": 22,
        "bio": "FPGA enthusiast",
        "social_links": {"github": "https://github.com/example", "linkedin": "https://linkedin.com/in/example"},
    }
    response = client.put("/api/profile", json=payload)
    assert response.status_code == 200
    assert response.json() == payload

    # Persisted, not just echoed back - a fresh GET must see the same data.
    response = client.get("/api/profile")
    assert response.json() == payload


def test_update_profile_can_clear_fields(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.put("/api/profile", json={"full_name": "Ali Yagiz"})

    response = client.put("/api/profile", json={})
    assert response.status_code == 200
    assert response.json()["full_name"] is None


def test_profile_requires_authentication(client):
    response = client.get("/api/profile")
    assert response.status_code == 401


def test_profile_is_private_per_user(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.put("/api/profile", json={"full_name": "User One"})

    register(client, "user2", "user2@example.com")
    login(client, "user2")

    response = client.get("/api/profile")
    assert response.json()["full_name"] is None
