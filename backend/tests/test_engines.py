"""Engine tests on the small toy site: these run real simulations."""
import numpy as np
import pytest

from app.geo.site_model import build_site_model
from app.sim.analytics import analyse
from app.sim.config import ScenarioConfig
from app.sim.ctm_engine import CTMEngine
from app.sim.jupedsim_engine import JuPedSimEngine
from app.sim.thresholds import DEFAULT_PROFILE

from .conftest import ORIGIN


def cfg(**kw):
    base = dict(name="t", duration_s=120, demand=[{"gate_id": "g_in", "rate_per_min": 60}],
                destinations=[{"target_id": "room_e", "share": 1, "dwell_s": 5}])
    base.update(kw)
    return ScenarioConfig.model_validate(base)


def _ctm(features, **kw):
    c = cfg(engine="macro_ctm", time_step_s=1.0, **kw)
    m = build_site_model(features, ORIGIN, corridor_overrides=c.corridor_overrides)
    return m, c, CTMEngine().run(m, c, DEFAULT_PROFILE)


def test_ctm_conserves_pedestrians(toy_features):
    m, c, r = _ctm(toy_features, duration_s=300, initial_population=[{"zone_id": "room_w", "count": 100, "dwell_s": 10}])
    arrived = sum(v[-1] for v in r["arrivals"].values())
    exited = sum(v[-1] for v in r["exits"].values())
    queued = sum(v[-1] for v in r["queues"].values())
    assert arrived == pytest.approx(300, rel=0.01)
    assert arrived + 100 == pytest.approx(r["remaining_count"] + exited + queued, abs=0.5)
    assert exited > 100


def test_ctm_respects_corridor_capacity(toy_features):
    # heavy demand through a 3 m corridor: flow is bounded by 1.22 p/(m s) * 3 m
    m, c, r = _ctm(toy_features, duration_s=300, demand=[{"gate_id": "g_in", "rate_per_min": 900}],
                   corridor_overrides=[{"corridor_id": "c_b", "enabled": False}])
    flow = r["rec"].section_flow["c_a"]
    cap_per_interval = 1.22 * 3 * c.output_interval_s
    assert max(flow) <= cap_per_interval + 1e-6
    assert max(flow) > 0.8 * cap_per_interval  # it actually saturates
    # and an entry queue builds up
    assert max(r["queues"]["g_in"]) > 100


def test_ctm_evacuation_and_analysis(toy_features):
    m, c, r = _ctm(toy_features, duration_s=400, initial_population=[{"zone_id": "room_e", "count": 400, "dwell_s": 600}],
                   demand=[], destinations=[], evacuation={"trigger_s": 10, "strategy": "capacity_aware"})
    a = analyse(r, m, c, DEFAULT_PROFILE)
    ev = a["evacuation"]
    assert ev["evacuees"] == pytest.approx(400, rel=0.01)
    assert ev["cleared_within_simulation"]
    assert ev["clearance_time_s"] > 0
    assert set(k for k, v in a["exits"].items() if v["count"] > 1) == {"g_out", "g_ne"}
    assert a["summary"]["method_type"] == "macroscopic"


def test_ctm_route_failure_reroutes(toy_features):
    m, c, r = _ctm(toy_features, duration_s=300, diversion={"activation_s": 60, "close_corridors": ["c_a"], "reroute_existing": True})
    assert any(e["type"] == "diversion" for e in r["events"])
    # after the closure arrivals use the long corridor c_b
    late = r["rec"].section_flow["c_b"][150:]
    assert sum(late) > 10


def test_jupedsim_agents_reach_destination_and_exit(toy_features):
    c = cfg(duration_s=150, demand=[{"gate_id": "g_in", "rate_per_min": 40}])
    m = build_site_model(toy_features, ORIGIN)
    r = JuPedSimEngine().run(m, c, DEFAULT_PROFILE)
    assert r["method_type"] == "agent_based"
    assert len(r["trips"]) > 20, "agents should complete the trip and leave"
    assert all(t["exit"] in ("g_out", "g_ne") for t in r["trips"])
    assert r["rec"].zone_counts["room_e"] and max(r["rec"].zone_counts["room_e"]) > 0
    # trip time cannot be shorter than walking ~40 m + 5 s dwell + ~25 m at <= 2 m/s
    assert min(t["exit_t"] - t["spawn_t"] for t in r["trips"]) > 30
    frames = r["rec"].agent_frames
    assert frames and len(frames[-1]["ids"]) == len(frames[-1]["x"])


def test_jupedsim_is_reproducible_with_seed(toy_features):
    c = cfg(duration_s=60, seed=7)
    m = build_site_model(toy_features, ORIGIN)
    r1 = JuPedSimEngine().run(m, c, DEFAULT_PROFILE)
    r2 = JuPedSimEngine().run(build_site_model(toy_features, ORIGIN), c, DEFAULT_PROFILE)
    assert r1["rec"].total == r2["rec"].total
    assert np.allclose(r1["rec"].agent_frames[-1]["x"], r2["rec"].agent_frames[-1]["x"])


def test_jupedsim_evacuation_reroutes_everyone(toy_features):
    c = cfg(duration_s=120, demand=[], destinations=[], initial_population=[{"zone_id": "room_e", "count": 120, "dwell_s": 999}],
            evacuation={"trigger_s": 5, "strategy": "nearest"})
    m = build_site_model(toy_features, ORIGIN)
    r = JuPedSimEngine().run(m, c, DEFAULT_PROFILE)
    a = analyse(r, m, c, DEFAULT_PROFILE)
    assert r["evacuation"]["evacuees"] == 120
    assert a["summary"]["total_exited"] > 60
    assert a["evacuation"]["ccrp_planning_estimate_s"] > 0


def test_invalid_scenario_is_rejected(toy_features):
    from app.sim.planning import PlanningError, TripPlanner

    m = build_site_model(toy_features, ORIGIN)
    with pytest.raises(PlanningError, match="unknown gate"):
        TripPlanner(m, cfg(demand=[{"gate_id": "nope", "rate_per_min": 10}]))
    with pytest.raises(PlanningError, match="not an enabled entry"):
        TripPlanner(m, cfg(demand=[{"gate_id": "g_out", "rate_per_min": 10}]))
    with pytest.raises(ValueError):
        ScenarioConfig.model_validate({"name": "x", "engine": "jupedsim", "time_step_s": 1.0})
