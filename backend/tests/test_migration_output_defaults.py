"""v54.2's data migration (alembic revision a7c4e1b9d2f5): the stored output defaults become
opus/best when either is something the app no longer offers, run against the test
database's real Postgres schema."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import AppSettings
from app.services import output_options

_MIGRATION = next((Path(__file__).parents[1] / "alembic" / "versions").glob("a7c4e1b9d2f5_*.py"))
_spec = importlib.util.spec_from_file_location("output_defaults_best_quality", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _row(db_session, fmt, rate):
    db_session.add(
        AppSettings(
            id=1,
            default_format=fmt,
            default_bitrate=rate,
            output_template="{title}.{output-ext}",
            library_target_dir="/mnt/raid1/media/music",
            library_folder_template="{artist}",
            library_quarantine_enabled=True,
            library_quarantine_dir="/downloads/quarantine",
        )
    )
    db_session.commit()


def _upgrade(db_session):
    with Operations.context(MigrationContext.configure(db_session.connection())):
        migration.upgrade()
    db_session.commit()
    db_session.expire_all()


@pytest.mark.parametrize(
    "fmt,rate",
    [
        ("mp3", "320k"),  # production's row
        ("mp3", "auto"),
        ("flac", "disable"),
        ("opus", "256k"),
        ("wav", "128k"),
    ],
)
def test_defaults_the_app_no_longer_offers_become_opus_best(db_session, fmt, rate):
    _row(db_session, fmt, rate)

    _upgrade(db_session)

    row = db_session.get(AppSettings, 1)
    assert (row.default_format, row.default_bitrate) == ("opus", "best")
    assert row.output_template == "{title}.{output-ext}"


@pytest.mark.parametrize("fmt,rate", [("m4a", "128k"), ("mp3", "best"), ("opus", "64k")])
def test_an_offered_pair_is_left_alone(db_session, fmt, rate):
    _row(db_session, fmt, rate)

    _upgrade(db_session)

    row = db_session.get(AppSettings, 1)
    assert (row.default_format, row.default_bitrate) == (fmt, rate)


def test_no_row_is_a_no_op(db_session):
    _upgrade(db_session)

    assert db_session.get(AppSettings, 1) is None


def test_the_migration_copies_the_offered_lists_of_its_day():
    """Copied, not imported, so it keeps meaning what it meant. Today they match."""
    assert migration._FORMATS == output_options.FORMATS
    assert migration._BITRATES == output_options.BITRATES
