from custom_components.lawn_growth.model import config, heat

T = config.Tunables()   # 88 / 95, warm offset 10; midpoint of 40..67 = 53.5


def test_mild_no_hold():
    assert heat.heat_hold(80.0, 30.0, 40, 67, T) is False


def test_hot_and_dry_holds():
    assert heat.heat_hold(90.0, 53.5, 40, 67, T) is True


def test_hot_but_moist_does_not_hold():
    # the old heat_moisture=20 never fired on the GeoDrops index; midpoint does
    assert heat.heat_hold(90.0, 54.0, 40, 67, T) is False


def test_extreme_always_holds():
    assert heat.heat_hold(95.0, 90.0, 40, 67, T) is True


def test_warm_season_thresholds_shift_up():
    assert heat.heat_hold(95.0, 90.0, 40, 67, T, warm=True) is False
    assert heat.heat_hold(98.0, 50.0, 40, 67, T, warm=True) is True
    assert heat.heat_hold(105.0, 90.0, 40, 67, T, warm=True) is True
