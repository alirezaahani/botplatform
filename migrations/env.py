from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from botplatform.config import Settings
from botplatform.db import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

engine = create_engine(Settings().database_url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
