from datetime import date

from custom_components.lawn_growth.model import config, season

T = config.Tunables()  # dormant_gp_threshold=0.1, dormant_days=10


def test_dormancy_streak_increments_on_low_gp():
    streak, dormant = season.update_dormancy(3, 0.05, T)
    assert streak == 4 and dormant is False


def test_dormancy_resets_on_growth():
    streak, dormant = season.update_dormancy(7, 0.5, T)
    assert streak == 0 and dormant is False


def test_dormant_when_streak_reaches_threshold():
    streak, dormant = season.update_dormancy(9, 0.05, T)
    assert streak == 10 and dormant is True
