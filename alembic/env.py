"""Alembic environment configuration.

Reads the actual database URL from nexus.config at runtime,
overriding the placeholder in alembic.ini.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Import our models so Alembic sees them for autogenerate
from nexus.database import Base
from nexus.models import (  # noqa: F401 — force registration
    Workflow, Approval, SLAEvent,
    AuditLog, AgentHealth, FailedTrigger,
    Meeting, MeetingAction,
)
from nexus.config import get_settings

# Alembic Config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with our actual config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

# MetaData for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL script."""
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
    """Run migrations in 'online' mode — connects to the DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
