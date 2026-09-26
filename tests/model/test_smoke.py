from datetime import date, timedelta

from custom_components.lawn_growth.model import config, evaluate, presets
from custom_components.lawn_growth.model.state import AreaState

TODAY = date(2026, 8, 9)


def _run(cfg, mean):
    inp = evaluate.DayInputs(
        today=TODAY, in_season=True, high_f=mean + 4, low_f=mean - 4,
        horizon=[(TODAY + timedelta(days=i), mean) for i in range(1, 11)],
        moisture=70.0, moisture_source="sensors", events=[])
    return evaluate.evaluate_area(cfg, config.Tunables(), AreaState(), inp, accrue=True)[0]


def test_august_heat_stretches_the_interval():
    cfg = presets.area_from_options({"key": "a", "name": "A", "grass": "tttf_kbg",
                                     "curve": "cool", "cut_min_in": 3.0, "cut_max_in": 3.9})
    hot, ideal = _run(cfg, 88.0), _run(cfg, 68.0)
    assert hot.growth_today_mm < ideal.growth_today_mm
    assert (hot.days_until_due or 999) > (ideal.days_until_due or 0)
