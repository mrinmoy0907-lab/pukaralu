import networkx as nx
import pytest
from shapely.geometry import box

from app.geo.site_model import Grid, SiteModelError, build_site_model
from app.sim.config import CorridorOverride, GateOverride

from .conftest import ORIGIN, to_features


def test_demo_site_builds_connected_network(demo_features):
    m = build_site_model(demo_features, ORIGIN)
    assert m.walkable.geom_type == "Polygon", "demo walkable area should be one connected polygon"
    assert not m.warnings
    assert all(g.node is not None for g in m.gates.values())
    assert nx.is_strongly_connected(m.graph(allow_emergency=True))
    # without emergency links, the emergency exit is unreachable from the entries
    g = m.graph()
    assert not nx.has_path(g, m.gates["g_bus"].node, m.gates["g_emerg"].node)
    assert nx.has_path(g, m.gates["g_bus"].node, m.gates["g_exit_e"].node)


def test_usable_area_excludes_obstacles():
    feats = to_features([
        ("h", "holding_area", box(0, 0, 50, 40), {"capacity_persons": 1000}),
        ("bld", "building", box(10, 10, 20, 20), {"height_m": 5}),
        ("c", "corridor", __import__("shapely.geometry", fromlist=["LineString"]).LineString([(50.5, 20), (80, 20)]), {"width_m": 3}),
    ])
    m = build_site_model(feats, ORIGIN)
    assert m.areas["h"].usable_area == pytest.approx(2000 - 100, rel=0.01)


def test_overrides_block_and_one_way(toy_features):
    base = build_site_model(toy_features, ORIGIN)
    n_a = sum(1 for lk in base.links.values() if lk.corridor_id == "c_a")
    assert n_a == 2  # two directions
    oneway = build_site_model(toy_features, ORIGIN, corridor_overrides=[CorridorOverride(corridor_id="c_a", direction="forward")])
    links = [lk for lk in oneway.links.values() if lk.corridor_id == "c_a"]
    assert len(links) == 1
    # the remaining link points west -> east (as digitised)
    assert links[0].geom.coords[0][0] < links[0].geom.coords[-1][0]
    blocked = build_site_model(toy_features, ORIGIN, corridor_overrides=[CorridorOverride(corridor_id="c_a", enabled=False)])
    assert blocked.walkable.area < base.walkable.area
    g = blocked.graph()
    path = nx.dijkstra_path(g, blocked.gates["g_in"].node, blocked.areas["room_e"].node, weight="time")
    used = {blocked.link_between(u, v).corridor_id for u, v in zip(path[:-1], path[1:])}
    assert "c_b" in used and "c_a" not in used


def test_gate_override_closes_exit(toy_features):
    m = build_site_model(toy_features, ORIGIN, gate_overrides=[GateOverride(gate_id="g_out", enabled=False)])
    assert [g.id for g in m.exit_gates()] == ["g_ne"]


def test_empty_site_raises():
    with pytest.raises(SiteModelError):
        build_site_model([], ORIGIN)


def test_density_grid_counts(toy_features):
    m = build_site_model(toy_features, ORIGIN)
    grid = Grid.for_model(m, 5.0)
    counts = grid.counts([2.5, 2.6, 7.5], [2.5, 2.4, 2.5])
    dens = grid.density(counts)
    # two people in a fully walkable 25 m2 cell
    iy = int((2.5 - grid.y0) // 5)
    ix = int((2.5 - grid.x0) // 5)
    assert counts[iy, ix] == 2
    assert dens[iy, ix] == pytest.approx(2 / grid.walk_area[iy, ix])
