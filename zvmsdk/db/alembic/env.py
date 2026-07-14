#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

from alembic import context
from sqlalchemy import engine_from_config, pool

# The alembic Config object — grants access to values in alembic.ini.
config = context.config

# target_metadata = None because we manage migrations manually via op.*
# calls instead of using alembic autogenerate / --autogenerate.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script).

    The URL must be provided in alembic.ini or injected via
    cfg.set_main_option('sqlalchemy.url', ...) before calling alembic.
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


def run_migrations_online() -> None:
    """Run migrations against a live DB connection.

    migration.py::ensure_schema_current() injects sqlalchemy.url into
    the alembic Config object before calling command.upgrade(), so this
    function never needs to import zvmsdk.config directly.
    """
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
