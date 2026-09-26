import pytest

from custom_components.lawn_growth.model import config, presets


def test_tunable_defaults():
    t = config.Tunables()
    assert t.budget_fraction == pytest.approx(1 / 3)
    assert (t.heat_temp_f, t.heat_extreme_f, t.warm_heat_offset_f) == (88.0, 95.0, 10.0)
    assert (t.germination_days, t.min_establishment_days, t.first_mow_ratio) == (10, 21, 1.5)
    assert (t.target_min_change_in, t.target_hold_days) == (0.25, 7)
    assert t.forecast_horizon_days == 10 and t.history_days == 45 and t.max_catchup_days == 10


def test_presets_cover_spec_table():
    p = presets.PRESETS
    assert set(p) == {"tttf_kbg", "kbg", "ryegrass", "fine_fescue",
                      "bermuda_zoysia", "st_augustine", "custom"}
    assert (p["tttf_kbg"].cut_min_in, p["tttf_kbg"].cut_max_in,
            p["tttf_kbg"].overseed_target_in) == (3.0, 4.0, 2.5)
    assert p["bermuda_zoysia"].curve == "warm" and p["bermuda_zoysia"].overseed_target_in is None
    assert presets.CURVES == {"cool": (68.0, 10.0), "warm": (88.0, 12.0)}
    assert presets.DEFAULT_PRESET == "tttf_kbg"


def _opts(**over):
    base = {"key": "back", "name": "Back", "grass": "tttf_kbg", "curve": "cool",
            "cut_min_in": 3.0, "cut_max_in": 3.9, "overseed_target_in": 2.5,
            "moisture_sensors": ["sensor.m"], "wilting_moisture": 40,
            "comfortable_moisture": 67, "max_growth_rate_mm": 6.5}
    base.update(over)
    return base


def test_area_from_options_cool():
    a = presets.area_from_options(_opts())
    assert a == config.AreaConfig(
        key="back", name="Back", grass="tttf_kbg", curve="cool", opt_temp_f=68.0,
        temp_spread_f=10.0, cut_min_in=3.0, cut_max_in=3.9, overseed_target_in=2.5,
        wilting_moisture=40.0, comfortable_moisture=67.0, max_growth_rate_mm=6.5)


def test_area_from_options_warm_drops_overseed_and_uses_warm_curve():
    a = presets.area_from_options(_opts(grass="bermuda_zoysia", curve="warm",
                                        cut_min_in=1.0, cut_max_in=2.0))
    assert (a.opt_temp_f, a.temp_spread_f, a.overseed_target_in) == (88.0, 12.0, None)


def test_area_from_options_defaults_optional_fields():
    raw = _opts()
    for k in ("wilting_moisture", "comfortable_moisture", "max_growth_rate_mm",
              "overseed_target_in"):
        raw.pop(k)
    a = presets.area_from_options(raw)
    assert (a.wilting_moisture, a.comfortable_moisture, a.max_growth_rate_mm,
            a.overseed_target_in) == (40.0, 67.0, 6.5, None)
