"""Scenario configuration schema.

A scenario is fully described by a ``ScenarioConfig`` plus the site features it
refers to. Every run stores a snapshot of both (plus the random seed and engine
version) so it can be reproduced.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SpeedDistribution(BaseModel):
    """Desired free walking speed, truncated normal (m/s).

    Default mean 1.34 m/s, sd 0.26 m/s follow Weidmann (1993). Pilgrim crowds with
    elderly persons, children and luggage are usually slower - calibrate locally.
    """

    mean: float = Field(1.34, gt=0.1, le=3.0)
    sd: float = Field(0.26, ge=0.0, le=1.0)
    min: float = Field(0.5, gt=0.0)
    max: float = Field(2.0, gt=0.0)

    @model_validator(mode="after")
    def _bounds(self):
        if not self.min <= self.mean <= self.max:
            raise ValueError("walking speed must satisfy min <= mean <= max")
        return self


class EntryDemand(BaseModel):
    gate_id: str
    rate_per_min: float = Field(..., ge=0, le=5000, description="Arrival rate (persons/min)")
    start_s: float = Field(0, ge=0)
    end_s: float | None = Field(None, ge=0)


class EntryRestriction(BaseModel):
    """Scheduled reduction (0<multiplier<1) or closure (multiplier=0) of an entry."""

    gate_id: str
    start_s: float = Field(..., ge=0)
    end_s: float | None = None
    rate_multiplier: float = Field(0.0, ge=0, le=1)


class Destination(BaseModel):
    target_id: str = Field(..., description="Feature id of a bathing area, ghat, holding area ...")
    share: float = Field(..., gt=0)
    dwell_s: float = Field(120, ge=0, le=6 * 3600)


class HoldingStop(BaseModel):
    """Optional intermediate stop in a holding area before the destination."""

    holding_id: str
    share: float = Field(1.0, gt=0, description="Share of arrivals routed through this holding area")
    dwell_s: float = Field(60, ge=0, le=6 * 3600)


class InitialPopulation(BaseModel):
    zone_id: str = Field(..., description="Walkable polygon feature where pedestrians start")
    count: int = Field(..., ge=0)
    dwell_s: float = Field(60, ge=0, description="Remaining dwell before they leave (normal mode)")


class CorridorOverride(BaseModel):
    corridor_id: str
    enabled: bool | None = None
    width_m: float | None = Field(None, gt=0.3, le=200)
    direction: Literal["both", "forward", "backward"] | None = None
    capacity_factor: float | None = Field(None, gt=0, le=1)


class GateOverride(BaseModel):
    gate_id: str
    enabled: bool | None = None
    role: Literal["entry", "exit", "both"] | None = None
    width_m: float | None = Field(None, gt=0.3, le=200)


class HoldingOverride(BaseModel):
    holding_id: str
    capacity_persons: int | None = Field(None, ge=0)


class Diversion(BaseModel):
    """At ``activation_s`` new arrivals use the diversion destinations, and the
    listed corridors are closed; pedestrians whose remaining route uses a closed
    corridor are re-routed (route failure / alternative route)."""

    activation_s: float = Field(..., ge=0)
    destinations: list[Destination] = Field(default_factory=list)
    close_corridors: list[str] = Field(default_factory=list)
    reroute_existing: bool = True


class EvacAssignment(BaseModel):
    zone_id: str
    exit_gate_id: str


class Evacuation(BaseModel):
    trigger_s: float = Field(..., ge=0)
    affected_zone_ids: list[str] = Field(default_factory=list, description="Empty = whole site")
    exit_gate_ids: list[str] = Field(default_factory=list, description="Empty = all enabled exits")
    assembly_point_ids: list[str] = Field(default_factory=list)
    strategy: Literal["nearest", "capacity_aware", "assigned"] = "nearest"
    assignments: list[EvacAssignment] = Field(default_factory=list)
    close_corridors: list[str] = Field(default_factory=list)
    capacity_reductions: list[CorridorOverride] = Field(default_factory=list)
    stop_arrivals: bool = True
    use_emergency_corridors: bool = True


class RouteChoice(BaseModel):
    strategy: Literal["shortest_time", "k_shortest_logit"] = "shortest_time"
    k: int = Field(3, ge=1, le=8)
    logit_theta: float = Field(0.05, gt=0, le=5, description="1/s; higher = more deterministic")


class ScenarioConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    engine: Literal["jupedsim", "macro_ctm"] = "jupedsim"
    pedestrian_model: Literal["CollisionFreeSpeedModel", "SocialForceModel"] = "CollisionFreeSpeedModel"
    duration_s: float = Field(600, gt=0)
    time_step_s: float = Field(0.05, gt=0, le=5)
    output_interval_s: float = Field(1.0, gt=0, le=60)
    seed: int = Field(42, ge=0)
    agent_radius_m: float = Field(0.2, gt=0.05, le=0.5)
    walking_speed: SpeedDistribution = Field(default_factory=SpeedDistribution)
    route_choice: RouteChoice = Field(default_factory=RouteChoice)
    initial_population: list[InitialPopulation] = Field(default_factory=list)
    demand: list[EntryDemand] = Field(default_factory=list)
    destinations: list[Destination] = Field(default_factory=list)
    holding_stops: list[HoldingStop] = Field(default_factory=list)
    exit_gate_ids: list[str] = Field(default_factory=list, description="Exits used after the visit; empty = nearest enabled exit")
    corridor_overrides: list[CorridorOverride] = Field(default_factory=list)
    gate_overrides: list[GateOverride] = Field(default_factory=list)
    holding_overrides: list[HoldingOverride] = Field(default_factory=list)
    entry_restrictions: list[EntryRestriction] = Field(default_factory=list)
    diversion: Diversion | None = None
    evacuation: Evacuation | None = None
    density_grid_cell_m: float = Field(4.0, ge=1.0, le=50.0)
    threshold_profile_id: int | None = None

    @model_validator(mode="after")
    def _consistency(self):
        if self.engine == "jupedsim" and self.time_step_s > 0.1:
            raise ValueError("time_step_s must be <= 0.1 s for the agent-based engine")
        if self.engine == "macro_ctm" and self.time_step_s < 0.25:
            raise ValueError("time_step_s should be >= 0.25 s for the macroscopic model")
        if self.output_interval_s < self.time_step_s:
            raise ValueError("output_interval_s must be >= time_step_s")
        if self.demand and not self.destinations and not self.evacuation:
            raise ValueError("arrivals are defined but no destinations are given")
        if self.evacuation and self.evacuation.trigger_s > self.duration_s:
            raise ValueError("evacuation trigger is after the end of the simulation")
        if self.diversion and self.diversion.activation_s > self.duration_s:
            raise ValueError("diversion activation is after the end of the simulation")
        if self.evacuation and self.evacuation.strategy == "assigned" and not self.evacuation.assignments:
            raise ValueError("strategy 'assigned' requires at least one zone-to-exit assignment")
        for d in self.demand:
            if d.end_s is not None and d.end_s < d.start_s:
                raise ValueError(f"demand at {d.gate_id}: end_s < start_s")
        return self
