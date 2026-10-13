"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

J = sa.JSON().with_variant(JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("is_synthetic", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("origin_lon", sa.Float, nullable=False),
        sa.Column("origin_lat", sa.Float, nullable=False),
        sa.Column("basemap", sa.String(50), nullable=False, server_default="osm"),
        sa.Column("tileset_url", sa.String(500)),
        sa.Column("terrain", J),
        sa.Column("provenance", J, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="vector"),
        sa.Column("format", sa.String(50), nullable=False),
        sa.Column("layer", sa.String(200)),
        sa.Column("feature_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_crs", sa.String(500)),
        sa.Column("license", sa.String(300), nullable=False, server_default="unknown"),
        sa.Column("attribution", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_synthetic", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_surveyed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64)),
        sa.Column("imported_at", TS, nullable=False),
    )
    op.create_table(
        "features",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("fid", sa.String(100), nullable=False),
        sa.Column("pk_type", sa.String(50), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("properties", J, nullable=False),
        sa.Column("geometry", J, nullable=False),
        sa.Column("dataset_id", sa.Integer, sa.ForeignKey("datasets.id", ondelete="SET NULL")),
        sa.Column("source", sa.String(30), nullable=False, server_default="drawn"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("site_id", "fid", name="uq_feature_site_fid"),
    )
    op.create_table(
        "threshold_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("values", J, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("approved_by", sa.String(200)),
        sa.Column("approved_on", sa.String(30)),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("preset", sa.String(50)),
        sa.Column("config", J, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("scenario_id", sa.Integer, sa.ForeignKey("scenarios.id", ondelete="SET NULL"), index=True),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("engine", sa.String(30), nullable=False),
        sa.Column("engine_version", sa.String(100), nullable=False, server_default=""),
        sa.Column("method", sa.String(300), nullable=False, server_default=""),
        sa.Column("seed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("config", J, nullable=False),
        sa.Column("site_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("features_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("features_snapshot", J, nullable=False),
        sa.Column("threshold_profile", J, nullable=False),
        sa.Column("summary", J),
        sa.Column("error", sa.Text),
        sa.Column("app_version", sa.String(30), nullable=False, server_default=""),
        sa.Column("review", J, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
    )
    op.create_table(
        "observations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("zone_fid", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="observed"),
        sa.Column("observed_at", TS),
        sa.Column("t_offset_s", sa.Float),
        sa.Column("count", sa.Float, nullable=False),
        sa.Column("source", sa.String(100), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("uploaded_at", TS, nullable=False),
    )


def downgrade() -> None:
    for t in ("observations", "runs", "scenarios", "threshold_profiles", "features", "datasets", "sites"):
        op.drop_table(t)
