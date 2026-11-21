"""Add phone accounts and farms."""
from alembic import op
import sqlalchemy as sa

revision = "a127d9b47c01"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user") as batch:
        batch.alter_column("email", existing_type=sa.String(255), nullable=True)
    op.add_column("user", sa.Column("phone_number", sa.String(16), nullable=True))
    op.create_index("ix_user_phone_number", "user", ["phone_number"], unique=True)
    op.create_table(
        "farm",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("county", sa.String(100), nullable=False),
        sa.Column("farm_type", sa.String(100), nullable=False),
        sa.Column("community", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_farm_owner_id", "farm", ["owner_id"])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM "user" WHERE email IS NULL')).scalar():
        raise RuntimeError("Assign emails to phone-only users before downgrading")
    op.drop_table("farm")
    op.drop_index("ix_user_phone_number", table_name="user")
    with op.batch_alter_table("user") as batch:
        batch.drop_column("phone_number")
        batch.alter_column("email", existing_type=sa.String(255), nullable=False)
