"""Database models (SQLAlchemy 2.x). Works on SQLite and PostgreSQL/PostGIS.

Geometry is stored as GeoJSON (WGS84) in ``features.geometry`` so the model is
portable. On PostgreSQL the migration ``0002_postgis`` additionally maintains a
``geom geometry(Geometry, 4326)`` column (filled by a trigger) with a GiST
index for spatial queries and for publishing layers through GeoServer.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    origin_lon: Mapped[float] = mapped_column(Float)
    origin_lat: Mapped[float] = mapped_column(Float)
    basemap: Mapped[str] = mapped_column(String(50), default="osm")
    tileset_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    terrain: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    provenance: Mapped[dict] = mapped_column(JSONType, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    features: Mapped[list[Feature]] = relationship(back_populates="site", cascade="all, delete-orphan")
    datasets: Mapped[list[Dataset]] = relationship(back_populates="site", cascade="all, delete-orphan")


class Dataset(Base):
    """Provenance of every imported file."""

    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="vector")  # vector | dem
    format: Mapped[str] = mapped_column(String(50))
    layer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    source_crs: Mapped[str | None] = mapped_column(String(500), nullable=True)
    license: Mapped[str] = mapped_column(String(300), default="unknown")
    attribution: Mapped[str] = mapped_column(String(500), default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    is_surveyed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    site: Mapped[Site] = relationship(back_populates="datasets")


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("site_id", "fid", name="uq_feature_site_fid"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    fid: Mapped[str] = mapped_column(String(100))
    pk_type: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    properties: Mapped[dict] = mapped_column(JSONType, default=dict)
    geometry: Mapped[dict] = mapped_column(JSONType)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="drawn")  # synthetic | imported | drawn
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    site: Mapped[Site] = relationship(back_populates="features")

    def to_geojson(self) -> dict:
        props = {**(self.properties or {}), "pk_type": self.pk_type, "name": self.name, "source": self.source}
        if self.dataset_id:
            props["dataset_id"] = self.dataset_id
        return {"type": "Feature", "id": self.fid, "geometry": self.geometry, "properties": props}


class ThresholdProfile(Base):
    __tablename__ = "threshold_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    values: Mapped[dict] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | retired
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_on: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    preset: Mapped[str | None] = mapped_column(String(50), nullable=True)
    config: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(30))
    engine_version: Mapped[str] = mapped_column(String(100), default="")
    method: Mapped[str] = mapped_column(String(300), default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSONType)
    site_version: Mapped[int] = mapped_column(Integer, default=1)
    features_hash: Mapped[str] = mapped_column(String(64), default="")
    features_snapshot: Mapped[list] = mapped_column(JSONType, default=list)
    threshold_profile: Mapped[dict] = mapped_column(JSONType, default=dict)
    summary: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_version: Mapped[str] = mapped_column(String(30), default="")
    review: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Observation(Base):
    """Measured or forecast counts. Never mixed with simulated values."""

    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    zone_fid: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="observed")  # observed | forecast
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    t_offset_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    count: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(100), default="manual")  # manual | cctv | counter | sensor
    notes: Mapped[str] = mapped_column(Text, default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
