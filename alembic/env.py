import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from voiceobs.db import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# env-only config (PLAN.md §5): VOICEOBS_DATABASE_URL wins over alembic.ini.
_env_url = os.getenv("VOICEOBS_DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# VO's schema metadata — drives autogenerate and upgrade.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _org_schemas(connection) -> list[str]:
    """Existing org schemas on Postgres (`t_*`), always including the default `t_default`."""
    from sqlalchemy import text

    rows = connection.execute(text(
        r"SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 't\_%'"
    )).scalars().all()
    return sorted({"t_default", *rows})


def _run_for_schema(connection, schema: str | None) -> None:
    """Run migrations against one schema (its own version table), or the flat DB when schema=None."""
    from sqlalchemy import text

    if schema is not None:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}"'))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=schema,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Schema-per-tenant: on Postgres, run the migrations once per org schema (search_path pinned to
    each, its own alembic_version table). On SQLite there is a single flat schema."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            for schema in _org_schemas(connection):
                _run_for_schema(connection, schema)
        else:
            _run_for_schema(connection, None)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
