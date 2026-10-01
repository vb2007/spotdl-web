from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import check_not_production_database, get_settings
from app.db import Base
import app.models  # noqa: F401 — registers models on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# v32: get_settings() already refuses a dev-marked process on the production database, but
# a migration run against production from a laptop is the worst version of that mistake --
# re-check the exact URL this run will connect to, so the guard still holds even if this
# file is later changed to take its URL from somewhere other than Settings.
check_not_production_database(config.get_main_option("sqlalchemy.url"), settings.spotdl_env)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
