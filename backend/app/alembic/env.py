"""Run migrations against the configured AgTrack database."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.models import SQLModel

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing app.models registers User, Item, and Farm for autogeneration.
target_metadata = SQLModel.metadata


def run_migrations_offline():
    context.configure(
        url=str(settings.DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # Pass the URL directly so percent-encoded passwords bypass INI interpolation.
    connectable = create_engine(str(settings.DATABASE_URL), poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
