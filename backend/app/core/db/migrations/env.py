"""Alembic migration environment.

Uses SYNC psycopg driver for migrations (Alembic doesn't support async natively).
The app uses async asyncpg for all runtime operations.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from dotenv import load_dotenv

load_dotenv()  # Load .env so DATABASE_URL_SYNC is available

from alembic import context
from sqlalchemy import create_engine, pool, text

from app.core.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Resolve sync database URL for migrations."""
    return os.getenv(
        "DATABASE_URL_SYNC",
        config.get_main_option("sqlalchemy.url", ""),
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    url = _get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Enable TimescaleDB extension before running migrations
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
        connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        connection.commit()

        # Ensure alembic_version table uses varchar(128) for version_num.
        # Default is varchar(32), but our revision IDs can exceed that
        # (e.g. '0049_wealth_continuous_aggregates' is 33 chars).
        # On fresh databases (CI), pre-create the table so Alembic doesn't
        # create it with the narrow default. On existing databases, widen it.
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(128) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
        """))
        connection.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'alembic_version'
                      AND column_name = 'version_num'
                      AND character_maximum_length < 128
                ) THEN
                    ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(128);
                END IF;
            END $$;
        """))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=target_metadata.schema,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
