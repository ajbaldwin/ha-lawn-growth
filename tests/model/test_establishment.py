from datetime import date, timedelta

import pytest

from custom_components.lawn_growth.model import config, establishment
from custom_components.lawn_growth.model.state import AreaState, DayRecord, OverseedState

T = config.Tunables()


def test_log_seeding_resets_and_clears_overseed():
    s = AreaState(accumulated_mm=20.0, seedlings_ready=True, ready_notified=True,
                  overseed=OverseedState(date(2026, 9, 20), 2.5, 7, "arrived"))
    out = establishment.log_seeding(s, date(2026, 9, 20))
    assert out.seeding_date == date(2026, 9, 20)
    assert (out.accumulated_mm, out.seedlings_ready, out.ready_notified) == (0.0, False, False)
    assert out.overseed == OverseedState()


def test_mark_ready_requires_seeding():
    with pytest.raises(ValueError):
        establishment.mark_ready(AreaState())
    out = establishment.mark_ready(AreaState(seeding_date=date(2026, 9, 20)))
    assert out.seedlings_ready is True


def test_seedling_height_counts_growth_from_germination():
    seed = date(2026, 9, 20)
    hist = [DayRecord(seed + timedelta(days=i), 60.0, 0.8, 5.08) for i in range(0, 20)]
    # germination 10 days -> days 10..19 count = 10 days * 5.08 mm = 50.8 mm = 2.0 in
    assert establishment.seedling_height_in(hist, seed, 10) == pytest.approx(2.0)


def test_not_ready_before_floor_even_if_tall():
    s = AreaState(seeding_date=date(2026, 9, 20))
    assert establishment.looks_ready(s, today=date(2026, 10, 10), seedling_in=9.0,
                                     first_mow_target_in=3.0, tun=T) is False


def test_ready_after_floor_when_tall_enough():
    s = AreaState(seeding_date=date(2026, 9, 20))
    kw = dict(today=date(2026, 10, 11), first_mow_target_in=3.0, tun=T)
    assert establishment.looks_ready(s, seedling_in=4.49, **kw) is False
    assert establishment.looks_ready(s, seedling_in=4.5, **kw) is True


def test_no_seeding_never_ready():
    assert establishment.looks_ready(AreaState(), today=date(2026, 9, 25), seedling_in=9.0,
                                     first_mow_target_in=3.0, tun=T) is False
