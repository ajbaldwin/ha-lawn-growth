from custom_components.lawn_growth.model import water


def test_zero_at_or_below_wilting():
    assert water.water_factor(15.0, 15.0, 35.0) == 0.0
    assert water.water_factor(10.0, 15.0, 35.0) == 0.0


def test_one_at_or_above_comfortable():
    assert water.water_factor(35.0, 15.0, 35.0) == 1.0
    assert water.water_factor(50.0, 15.0, 35.0) == 1.0


def test_linear_between():
    assert water.water_factor(25.0, 15.0, 35.0) == 0.5


def test_rejects_bad_bounds():
    try:
        water.water_factor(20.0, 35.0, 15.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
