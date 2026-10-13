"""PostGIS geometry column, trigger and spatial index (PostgreSQL only)

On PostgreSQL this adds ``features.geom geometry(Geometry, 4326)``, kept in sync
with the GeoJSON column by a trigger, plus a GiST index. GeoServer can publish
the ``features`` table (filtered by pk_type/site_id) as WMS/WFS layers.
On SQLite this migration is a no-op.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    available = bind.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'postgis'")).first()
    if not available:
        # Plain PostgreSQL: the application still works (GeoJSON columns, Shapely spatial filters).
        print("WARNING: PostGIS extension not available - spatial index and geom column not created")
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("ALTER TABLE features ADD COLUMN geom geometry(Geometry, 4326)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION features_set_geom() RETURNS trigger AS $$
        BEGIN
            NEW.geom := ST_SetSRID(ST_MakeValid(ST_GeomFromGeoJSON(NEW.geometry::text)), 4326);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_features_geom BEFORE INSERT OR UPDATE OF geometry ON features "
        "FOR EACH ROW EXECUTE FUNCTION features_set_geom()"
    )
    op.execute("UPDATE features SET geometry = geometry")
    op.execute("CREATE INDEX ix_features_geom ON features USING GIST (geom)")
    # convenience view for GeoServer: one layer per feature type via CQL filter on pk_type
    op.execute(
        "CREATE OR REPLACE VIEW v_site_features AS "
        "SELECT f.id, f.site_id, s.name AS site_name, s.is_synthetic, f.fid, f.pk_type, f.name, "
        "f.properties, f.source, f.geom FROM features f JOIN sites s ON s.id = f.site_id"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not bind.execute(sa.text("SELECT 1 FROM information_schema.columns WHERE table_name='features' AND column_name='geom'")).first():
        return
    op.execute("DROP VIEW IF EXISTS v_site_features")
    op.execute("DROP TRIGGER IF EXISTS trg_features_geom ON features")
    op.execute("DROP FUNCTION IF EXISTS features_set_geom()")
    op.execute("DROP INDEX IF EXISTS ix_features_geom")
    op.execute("ALTER TABLE features DROP COLUMN IF EXISTS geom")
