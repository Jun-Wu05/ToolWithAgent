from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config


def run_migrations_online():
    engine = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("PRAGMA busy_timeout=5000")
        connection.commit()
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
    engine.dispose()

run_migrations_online()
