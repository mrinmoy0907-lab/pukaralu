"""Catalogue of site feature types (the ``pk_type`` property of every feature).

The catalogue defines how each feature type participates in the Digital Twin:

* ``walkable``  - polygon that pedestrians may occupy (part of the simulation geometry)
* ``obstacle``  - polygon/line that is removed from the walkable area
* ``corridor``  - line that becomes part of the pedestrian network (buffered by width_m)
* ``area_node`` - walkable polygon that also becomes a node of the network
* ``point``     - point asset (gates, first aid, ...)
* ``reference`` - displayed only; not used by the simulation
"""
from __future__ import annotations

FEATURE_TYPES: dict[str, dict] = {
    # Water and river front
    "river": {"label": "River / water body", "geom": "Polygon", "roles": ["obstacle"]},
    "bathing_area": {"label": "Bathing area", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    "ghat": {"label": "Ghat", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    "steps": {"label": "Ghat steps", "geom": "Polygon", "roles": ["walkable"]},
    "ramp": {"label": "Ramp", "geom": "Polygon", "roles": ["walkable"]},
    # Built environment
    "temple": {"label": "Temple", "geom": "Polygon", "roles": ["obstacle"]},
    "building": {"label": "Building", "geom": "Polygon", "roles": ["obstacle"]},
    "wall": {"label": "Wall", "geom": "LineString", "roles": ["obstacle"]},
    "barricade": {"label": "Barricade", "geom": "LineString", "roles": ["obstacle"]},
    "obstacle": {"label": "Other obstacle", "geom": "Polygon", "roles": ["obstacle"]},
    # Movement
    "road": {"label": "Approach road (vehicular)", "geom": "LineString", "roles": ["reference"]},
    "corridor": {"label": "Pedestrian corridor", "geom": "LineString", "roles": ["corridor"]},
    "emergency_corridor": {"label": "Emergency access corridor", "geom": "LineString", "roles": ["corridor"]},
    "queue_lane": {"label": "Queue lane", "geom": "Polygon", "roles": ["walkable"]},
    "plaza": {"label": "Open walkable area", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    "gate": {"label": "Entry / exit gate", "geom": "Point", "roles": ["point"]},
    # Holding, assembly and transport
    "holding_area": {"label": "Holding area", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    "assembly_point": {"label": "Assembly point", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    "transit_hub": {"label": "Transit hub", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    "bus_terminal": {"label": "Bus terminal", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    "parking": {"label": "Parking area", "geom": "Polygon", "roles": ["walkable", "area_node"]},
    # Services
    "hospital": {"label": "Hospital", "geom": "Point", "roles": ["point"]},
    "first_aid": {"label": "First-aid post", "geom": "Point", "roles": ["point"]},
    "control_point": {"label": "Control point / police post", "geom": "Point", "roles": ["point"]},
    "speaker": {"label": "PA speaker", "geom": "Point", "roles": ["point"]},
    # Analysis
    "zone": {"label": "Analysis zone", "geom": "Polygon", "roles": ["reference"]},
    "terrain_extent": {"label": "Terrain extent", "geom": "Polygon", "roles": ["reference"]},
}

AREA_NODE_TYPES = {k for k, v in FEATURE_TYPES.items() if "area_node" in v["roles"]}
WALKABLE_TYPES = {k for k, v in FEATURE_TYPES.items() if "walkable" in v["roles"]}
OBSTACLE_TYPES = {k for k, v in FEATURE_TYPES.items() if "obstacle" in v["roles"]}
CORRIDOR_TYPES = {k for k, v in FEATURE_TYPES.items() if "corridor" in v["roles"]}
# Destinations a scenario may send pedestrians to (they dwell there).
DESTINATION_TYPES = {"bathing_area", "ghat", "holding_area", "assembly_point", "plaza", "transit_hub", "bus_terminal", "parking"}
# Line obstacles are buffered by this half-thickness (metres) unless thickness_m is given.
DEFAULT_LINE_OBSTACLE_THICKNESS = 0.4

CORRIDOR_DEFAULTS = {"width_m": 4.0, "direction": "both", "surface": "path", "enabled": True, "emergency_only": False}
GATE_DEFAULTS = {"role": "both", "width_m": 4.0, "enabled": True, "emergency_exit": False}

# Relative free walking speed by surface (applied to each pedestrian's desired speed in
# the macroscopic model and used for free-flow routing times). Values follow the
# ratios commonly used for stair descent/ascent vs level walking (e.g. Fruin 1971,
# Weidmann 1993); they are defaults and must be validated locally.
SURFACE_SPEED_FACTOR = {"path": 1.0, "ramp": 0.9, "stairs": 0.6, "steps": 0.6}


def is_known(pk_type: str) -> bool:
    return pk_type in FEATURE_TYPES
