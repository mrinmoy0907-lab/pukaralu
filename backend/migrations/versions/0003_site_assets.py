"""site assets (3D Tiles, glTF models, imagery, terrain) loaded from the data folder

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sites") as b:
        b.add_column(sa.Column("assets", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sites") as b:
        b.drop_column("assets")
