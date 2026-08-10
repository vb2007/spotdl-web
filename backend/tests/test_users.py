from app.config import get_settings
from app.models import User
from app.services.users import get_or_create_user, normalize_email


def test_normalize_email_strips_and_lowercases():
    assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_get_or_create_user_creates_row_on_first_login(db_session):
    user = get_or_create_user(db_session, "allowed@example.com")
    db_session.commit()

    assert user.email == "allowed@example.com"
    assert user.is_admin is False
    row = db_session.query(User).filter(User.email == "allowed@example.com").one()
    assert row.id == user.id


def test_get_or_create_user_is_case_insensitive_and_reuses_the_row(db_session):
    first = get_or_create_user(db_session, "Allowed@Example.com")
    db_session.commit()

    second = get_or_create_user(db_session, "  allowed@example.com  ")
    db_session.commit()

    assert first.id == second.id
    assert db_session.query(User).count() == 1


def test_get_or_create_user_grants_admin_from_admin_email(db_session):
    # conftest.py sets ADMIN_EMAIL=admin@example.com for the whole suite.
    user = get_or_create_user(db_session, "admin@example.com")
    db_session.commit()
    assert user.is_admin is True


def test_get_or_create_user_reconciles_admin_flag_on_every_login(db_session, monkeypatch):
    """Changing ADMIN_EMAIL must take effect on the next login, not need manual SQL --
    and exactly one admin must ever exist, so a stale admin who hasn't logged in since
    the change is demoted by the *other* identity's login, not just their own."""
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_email", "first-admin@example.com", raising=False)

    first_admin = get_or_create_user(db_session, "first-admin@example.com")
    db_session.commit()
    assert first_admin.is_admin is True

    monkeypatch.setattr(settings, "admin_email", "second-admin@example.com", raising=False)
    second_admin = get_or_create_user(db_session, "second-admin@example.com")
    db_session.commit()

    assert second_admin.is_admin is True
    stale = db_session.query(User).filter(User.email == "first-admin@example.com").one()
    assert stale.is_admin is False
    assert db_session.query(User).filter(User.is_admin.is_(True)).count() == 1


def test_get_or_create_user_bumps_last_login_at(db_session):
    user = get_or_create_user(db_session, "allowed@example.com")
    db_session.commit()
    first_login_at = user.last_login_at

    second = get_or_create_user(db_session, "allowed@example.com")
    db_session.commit()

    assert second.last_login_at >= first_login_at
