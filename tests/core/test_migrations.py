"""The migrations build exactly the schema the models describe."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from botplatform.db import engine

ROOT = Path(__file__).parents[2]  # where alembic.ini is
# A database of its own: the other tests create their tables in the shared one without alembic.
CHECK_DATABASE = "migration_check"


def recreate(database: str, *, keep: bool) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {database}"))
        if keep:
            connection.execute(text(f"CREATE DATABASE {database}"))


def test_the_migrations_match_the_models():
    """A new column or table without a migration fails here, not at runtime."""
    recreate(CHECK_DATABASE, keep=True)
    url = engine.url.set(database=CHECK_DATABASE).render_as_string(hide_password=False)
    try:
        for command in (["upgrade", "head"], ["check"]):
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *command],
                cwd=ROOT,
                env={**os.environ, "DATABASE_URL": url},
                check=False,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
    finally:
        recreate(CHECK_DATABASE, keep=False)
