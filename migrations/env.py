from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool, text

from academic_planner.database.config import settings
from academic_planner.database.session import Base
from academic_planner.database import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
if config.config_file_name: fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction(): context.run_migrations()

def run_migrations_online():
    connectable=engine_from_config(config.get_section(config.config_ini_section),prefix="sqlalchemy.",poolclass=pool.NullPool)
    with connectable.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # SQLite batch migrations recreate tables. Keeping enforcement on
            # during the temporary drop/rename window can reject a migration
            # whose final schema is fully consistent. Validate the final state
            # before re-enabling enforcement instead.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        context.configure(connection=connection, target_metadata=target_metadata,
                          transactional_ddl=True, transaction_per_migration=True)
        with context.begin_transaction(): context.run_migrations()
        # Python 3.14's sqlite driver uses explicit transaction control.
        # Persist both schema DDL and Alembic's revision marker.
        connection.commit()
        if sqlite:
            violations = connection.execute(text("PRAGMA foreign_key_check")).all()
            if violations:
                raise RuntimeError(
                    "Migration left foreign-key violations: " + repr(violations[:10])
                )
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
