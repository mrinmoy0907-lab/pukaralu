import networkx as nx
import pytest

from app.geo.routing import RoutingError, ccrp, k_shortest, shortest_path
from app.geo.site_model import build_site_model

from .conftest import ORIGIN


def test_shortest_and_alternatives(toy_features):
    m = build_site_model(toy_features, ORIGIN)
    g = m.graph()
    src, dst = m.gates["g_in"].node, m.areas["room_e"].node
    p = shortest_path(g, src, dst)
    assert "c_a" in {m.link_between(u, v).corridor_id for u, v in zip(p[:-1], p[1:])}
    alts = k_shortest(g, src, dst, 3)
    assert len(alts) >= 2 and alts[0] != alts[1]


def test_unreachable_raises(toy_features):
    m = build_site_model(toy_features, ORIGIN)
    g = m.graph(closed_corridors={"c_a", "c_b"})
    with pytest.raises(RoutingError):
        shortest_path(g, m.gates["g_in"].node, m.areas["room_e"].node)


def test_one_way_is_respected(toy_features):
    from app.sim.config import CorridorOverride

    m = build_site_model(toy_features, ORIGIN, corridor_overrides=[CorridorOverride(corridor_id="c_a", direction="backward")])
    g = m.graph()
    p = shortest_path(g, m.gates["g_in"].node, m.areas["room_e"].node)
    assert "c_a" not in {m.link_between(u, v).corridor_id for u, v in zip(p[:-1], p[1:])}


def test_ccrp_uses_second_exit_when_first_saturates(toy_features):
    m = build_site_model(toy_features, ORIGIN)
    g = m.graph()
    room = m.areas["room_e"].node
    exits = [m.gates["g_out"].node, m.gates["g_ne"].node]
    small = ccrp(m, g, {room: 10}, exits)
    big = ccrp(m, g, {room: 3000}, exits)
    assert sum(small.sink_load.values()) == pytest.approx(10)
    assert sum(big.sink_load.values()) == pytest.approx(3000)
    # with a large crowd both exits are used
    assert len([v for v in big.sink_load.values() if v > 1]) == 2
    assert big.clearance_time_s > small.clearance_time_s
    # clearance can never be shorter than the capacity bound of the two gate links
    exit_nodes = {m.gates["g_out"].node, m.gates["g_ne"].node}
    cap = sum(lk.capacity_pps for lk in m.links.values() if lk.v in exit_nodes)
    assert big.clearance_time_s >= 3000 / cap * 0.95


def test_ccrp_reports_unreachable(toy_features):
    m = build_site_model(toy_features, ORIGIN)
    g = m.graph(closed_corridors={"c_exit", "c_ne"})
    res = ccrp(m, g, {m.areas["room_e"].node: 50}, [m.gates["g_out"].node, m.gates["g_ne"].node])
    assert res.unreachable and sum(res.unreachable.values()) == 50
    assert nx.is_directed(g)
