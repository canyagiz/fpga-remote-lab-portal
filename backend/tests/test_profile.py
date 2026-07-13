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
        "is_public": True,
        "hidden_fields": None,
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
        "is_public": True,
        "hidden_fields": None,
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


def test_profile_rejects_an_unreasonable_age(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.put("/api/profile", json={"age": 4})
    assert response.status_code == 422

    response = client.put("/api/profile", json={"age": 200})
    assert response.status_code == 422


def test_social_link_must_point_to_its_own_platform(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.put("/api/profile", json={"social_links": {"linkedin": "https://github.com/someone"}})
    assert response.status_code == 422


def test_social_link_rejects_a_non_url(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.put("/api/profile", json={"social_links": {"github": "not-a-url"}})
    assert response.status_code == 422


def test_social_link_accepts_the_matching_platform(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.put(
        "/api/profile",
        json={"social_links": {"linkedin": "https://www.linkedin.com/in/someone", "x": "https://x.com/someone"}},
    )
    assert response.status_code == 200


def test_website_link_has_no_domain_restriction(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.put("/api/profile", json={"social_links": {"website": "https://my-own-site.example"}})
    assert response.status_code == 200


def test_private_profile_hides_everything_from_other_users(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.put("/api/profile", json={"full_name": "User One", "bio": "hi", "is_public": False})

    register(client, "user2", "user2@example.com")
    login(client, "user2")

    response = client.get("/api/profile/user1")
    assert response.status_code == 200
    body = response.json()
    assert body["is_public"] is False
    assert body["full_name"] is None
    assert body["bio"] is None


def test_hidden_fields_are_omitted_from_the_public_view_but_kept_for_the_owner(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.put(
        "/api/profile",
        json={
            "full_name": "User One",
            "age": 22,
            "bio": "secret bio",
            "hidden_fields": ["age", "bio"],
        },
    )

    # The owner still sees their own real data when editing.
    mine = client.get("/api/profile").json()
    assert mine["age"] == 22
    assert mine["bio"] == "secret bio"
    assert mine["hidden_fields"] == ["age", "bio"]

    register(client, "user2", "user2@example.com")
    login(client, "user2")
    public = client.get("/api/profile/user1").json()
    assert public["full_name"] == "User One"
    assert public["age"] is None
    assert public["bio"] is None


def test_hiding_a_single_social_link_leaves_the_others_visible(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.put(
        "/api/profile",
        json={
            "social_links": {"github": "https://github.com/someone", "x": "https://x.com/someone"},
            "hidden_fields": ["social:github"],
        },
    )

    register(client, "user2", "user2@example.com")
    login(client, "user2")
    public = client.get("/api/profile/user1").json()
    assert public["social_links"] == {"x": "https://x.com/someone"}


def test_public_profile_is_viewable_by_any_signed_in_user(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.put(
        "/api/profile",
        json={"full_name": "User One", "school": "H-BRS", "department": None, "age": None, "bio": None,
              "social_links": None},
    )

    register(client, "user2", "user2@example.com")
    login(client, "user2")

    response = client.get("/api/profile/user1")
    assert response.status_code == 200
    assert response.json()["username"] == "user1"
    assert response.json()["full_name"] == "User One"


def test_public_profile_lookup_is_case_insensitive(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.get("/api/profile/USER1")
    assert response.status_code == 200
    assert response.json()["username"] == "user1"


def test_public_profile_404s_for_an_unknown_username(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.get("/api/profile/nobody-here")
    assert response.status_code == 404


def test_public_profile_requires_authentication(client):
    response = client.get("/api/profile/user1")
    assert response.status_code == 401


def test_profile_is_private_per_user(client):
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.put("/api/profile", json={"full_name": "User One"})

    register(client, "user2", "user2@example.com")
    login(client, "user2")

    response = client.get("/api/profile")
    assert response.json()["full_name"] is None
