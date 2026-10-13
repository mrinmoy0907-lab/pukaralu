import pytest

from app.geo.site_model import build_site_model
from app.sim.config import ScenarioConfig
from app.sim.ctm_engine import CTMEngine
from app.sim.planning import TripPlanner
from app.sim.presets import PRESETS, build_presets
from app.sim.thresholds import DEFAULT_PROFILE

from .conftest import ORIGIN


def test_all_ten_presets_are_generated_and_valid(demo_features):
    presets = build_presets(demo_features, ORIGIN)
    assert set(presets) == {k for k, _ in PRESETS}
    for key, cfg in presets.items():
        c = ScenarioConfig.model_validate(cfg)
        m = build_site_model(demo_features, ORIGIN, corridor_overrides=c.corridor_overrides,
                             gate_overrides=c.gate_overrides, holding_overrides=c.holding_overrides)
        TripPlanner(m, c)  # raises on any inconsistency
        assert c.description


@pytest.mark.parametrize("key", ["blocked_corridor", "one_way", "evacuation", "route_failure", "holding_overcrowded"])
def test_presets_run_macroscopic(demo_features, key):
    cfg = dict(build_presets(demo_features, ORIGIN)[key])
    cfg.update(engine="macro_ctm", time_step_s=1.0, duration_s=600)
    c = ScenarioConfig.model_validate(cfg)
    m = build_site_model(demo_features, ORIGIN, corridor_overrides=c.corridor_overrides,
                         gate_overrides=c.gate_overrides, holding_overrides=c.holding_overrides)
    r = CTMEngine().run(m, c, DEFAULT_PROFILE)
    assert max(r["rec"].total) > 0
    if key == "evacuation":
        assert r["evacuation"]["evacuees"] > 1000
