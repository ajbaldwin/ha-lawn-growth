import math

from custom_components.lawn_growth.model import growth


def test_gp_peaks_at_optimum():
    assert growth.growth_potential(68.0) == 1.0


def test_gp_reference_points():
    assert math.isclose(growth.growth_potential(78.0), math.exp(-0.5), rel_tol=1e-9)
    assert math.isclose(growth.growth_potential(88.0), math.exp(-2.0), rel_tol=1e-9)


def test_gp_symmetric_about_optimum():
    assert math.isclose(
        growth.growth_potential(58.0), growth.growth_potential(78.0), rel_tol=1e-12
    )


def test_gp_rejects_nonpositive_spread():
    try:
        growth.growth_potential(68.0, spread_f=0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_predicted_growth_multiplies_factors():
    assert growth.predicted_growth_mm(6.0, 0.5, 0.5, 2.0) == 3.0


def test_predicted_growth_zero_when_any_factor_zero():
    assert growth.predicted_growth_mm(6.0, 0.0, 1.0, 1.0) == 0.0
