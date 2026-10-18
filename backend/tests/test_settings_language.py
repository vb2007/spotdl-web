"""v46: the per-user interface language, and its adoption from /login."""

from app.routers import auth


def _mock_upstream_login(monkeypatch) -> None:
    async def fake_login(email: str, password: str) -> tuple[bool, str | None]:
        return True, None

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)


def _login(client, monkeypatch, **extra):
    _mock_upstream_login(monkeypatch)
    return client.post(
        "/api/auth/login",
        json={"email": "allowed@example.com", "password": "correct", **extra},
    )


def test_language_defaults_to_no_preference(authenticated_client, db_session):
    response = authenticated_client.get("/api/settings/language")

    assert response.status_code == 200
    assert response.json() == {"language": None}
    assert authenticated_client.get("/api/auth/me").json()["language"] is None


def test_update_language_persists_and_reaches_me(authenticated_client, db_session):
    updated = authenticated_client.patch("/api/settings/language", json={"language": "hu"})

    assert updated.status_code == 200
    assert updated.json() == {"language": "hu"}
    assert authenticated_client.get("/api/settings/language").json() == {"language": "hu"}
    assert authenticated_client.get("/api/auth/me").json()["language"] == "hu"

    authenticated_client.patch("/api/settings/language", json={"language": "en"})
    assert authenticated_client.get("/api/auth/me").json()["language"] == "en"


def test_me_reports_no_language_without_creating_a_settings_row(authenticated_client, db_session):
    from app.models import UserSettings

    assert authenticated_client.get("/api/auth/me").json()["language"] is None
    assert db_session.query(UserSettings).count() == 0


def test_update_language_rejects_an_unknown_language(authenticated_client, db_session):
    for bad in ("de", "HU", "", None, 1):
        response = authenticated_client.patch("/api/settings/language", json={"language": bad})
        assert response.status_code == 422, bad
    assert authenticated_client.patch("/api/settings/language", json={}).status_code == 422
    assert authenticated_client.get("/api/settings/language").json() == {"language": None}


def test_language_leaves_the_other_preferences_alone(authenticated_client, db_session):
    authenticated_client.patch("/api/settings/retention", json={"retention_days": 9})
    authenticated_client.patch("/api/settings/keyboard", json={"keyboard_shortcuts": False})
    authenticated_client.patch("/api/settings/language", json={"language": "hu"})

    assert authenticated_client.get("/api/settings/retention").json() == {"retention_days": 9}
    assert authenticated_client.get("/api/settings/keyboard").json() == {"keyboard_shortcuts": False}


def test_language_settings_endpoints_require_session(client):
    assert client.get("/api/settings/language").status_code == 401
    assert client.patch("/api/settings/language", json={"language": "hu"}).status_code == 401


def test_login_adopts_the_login_page_choice_into_a_profile_without_one(client, monkeypatch):
    assert _login(client, monkeypatch, language="hu").status_code == 200

    assert client.get("/api/auth/me").json()["language"] == "hu"


def test_login_never_overrides_a_saved_language(client, monkeypatch):
    _login(client, monkeypatch, language="hu")
    client.post("/api/auth/logout")

    # A later sign-in from a browser where /login was left on English keeps the profile's.
    assert _login(client, monkeypatch, language="en").status_code == 200
    assert client.get("/api/auth/me").json()["language"] == "hu"


def test_login_without_a_choice_saves_nothing(client, monkeypatch, db_session):
    from app.models import UserSettings

    assert _login(client, monkeypatch).status_code == 200
    assert client.get("/api/auth/me").json()["language"] is None
    assert db_session.query(UserSettings).count() == 0


def test_login_ignores_a_language_it_does_not_ship(client, monkeypatch, db_session):
    """An optional preference never blocks a sign-in: an unknown value is dropped, not 422."""
    from app.models import UserSettings

    for value in ("de", "HU", ""):
        assert _login(client, monkeypatch, language=value).status_code == 200, value
        assert client.get("/api/auth/me").json()["language"] is None
    assert db_session.query(UserSettings).count() == 0


def test_adopting_never_fails_a_sign_in_that_loses_a_race(db_session, make_user, monkeypatch):
    """Two first sign-ins at once both insert the settings row; the second one's adopt must
    swallow the conflict (its savepoint rolls back), not fail the sign-in's transaction."""
    from sqlalchemy.exc import IntegrityError

    from app.services import user_settings

    user = make_user("racer@example.com")
    db_session.commit()

    def lose_the_race(db, user_id, language):
        raise IntegrityError("insert into user_settings", {}, Exception("duplicate key"))

    monkeypatch.setattr(user_settings, "update_language", lose_the_race)
    user_settings.adopt_language(db_session, user.id, "hu")
    # The outer transaction is still usable.
    db_session.commit()
    assert user_settings.language_preference(db_session, user.id) is None
