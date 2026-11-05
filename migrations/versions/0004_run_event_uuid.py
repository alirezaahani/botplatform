"""Make the run event ID a UUID, like the other tables, and order the timeline by `at`

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("run_events_run_id", table_name="run_events")
    op.drop_column("run_events", "id")  # also drops the primary key
    op.add_column(
        "run_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.create_primary_key("run_events_pkey", "run_events", ["id"])
    op.alter_column("run_events", "id", server_default=None)  # the app generates IDs
    op.create_index("run_events_run_id", "run_events", ["run_id", "at"])


def downgrade() -> None:
    op.drop_index("run_events_run_id", table_name="run_events")
    op.drop_column("run_events", "id")
    op.add_column("run_events", sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False))
    # The column is added in no particular order, so renumber in timeline order.
    op.execute(
        "UPDATE run_events SET id = numbered.n FROM ("
        "SELECT ctid AS row_id, row_number() OVER (ORDER BY at) AS n FROM run_events"
        ") AS numbered WHERE run_events.ctid = numbered.row_id"
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('run_events', 'id'), "
        "greatest((SELECT max(id) FROM run_events), 1), (SELECT count(*) > 0 FROM run_events))"
    )
    op.create_primary_key("run_events_pkey", "run_events", ["id"])
    op.create_index("run_events_run_id", "run_events", ["run_id", "id"])
