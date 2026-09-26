from datetime import date

from custom_components.lawn_growth.model import config, management

T = config.Tunables()


def ev(kind, applied):
    return management.ManagementEvent(kind=kind, applied=applied)


def test_no_events_is_neutral():
    assert management.management_factor([], date(2026, 8, 9), T) == 1.0


def test_fert_peak_at_peak_day():
    e = ev("fert", date(2026, 8, 1))
    today = date(2026, 8, 1 + int(T.fert_peak_days))  # peak day
    assert management.management_factor([e], today, T) == T.fert_peak_factor


def test_fert_expired_is_neutral():
    e = ev("fert", date(2026, 7, 1))
    assert management.management_factor([e], date(2026, 8, 9), T) == 1.0


def test_pgr_suppresses_at_application():
    e = ev("pgr", date(2026, 8, 9))
    assert management.management_factor([e], date(2026, 8, 9), T) == T.pgr_suppression


def test_pgr_recovers_to_neutral_at_end():
    e = ev("pgr", date(2026, 8, 1))
    today = date(2026, 8, 1 + int(T.pgr_duration_days))
    assert management.management_factor([e], today, T) == 1.0


def test_events_combine_multiplicatively():
    fert = ev("fert", date(2026, 8, 1))
    pgr = ev("pgr", date(2026, 8, 9))
    today = date(2026, 8, 1 + int(T.fert_peak_days))
    expected = T.fert_peak_factor * management._pgr_factor(
        (today - pgr.applied).days, T
    )
    assert management.management_factor([fert, pgr], today, T) == expected
