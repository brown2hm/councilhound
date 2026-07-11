"""Alembic environment — reuses the app's engine resolution (DATABASE_URL or
embedded dev Postgres) and targets the SQLAlchemy models' metadata."""
from alembic import context

from fairfax_kb.db.models import Base
from fairfax_kb.db.session import get_engine

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    from fairfax_kb.db.session import _resolve_database_url

    context.configure(
        url=_resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
