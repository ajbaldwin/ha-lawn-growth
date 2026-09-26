from datetime import datetime, timezone

from custom_components.lawn_growth.model import session


def t(hm: str) -> datetime:
    return datetime(2026, 9, 17, int(hm[:2]), int(hm[3:]), tzinfo=timezone.utc)


def _replay_0917():
    """A recorded robot-mower run (both Backyard locations -> 'back')."""
    s = session.start(t("12:25"), area="back", height_in=3.54)
    session.update(s, t("12:27"), working=True)          # MODE_PAUSE is a working state
    session.update(s, t("12:36"), height_in=2.95)        # blade lowered mid-job
    session.update(s, t("13:30"), area="back")           # Backyard -> Backyard - Slope
    session.update(s, t("14:42"), working=False)         # MODE_READY
    session.update(s, t("14:43"), working=True)          # back to work within grace
    session.update(s, t("14:54"), area=None)             # "path" is not mapped
    session.update(s, t("14:58"), working=False)         # MODE_RETURNING
    return s


def test_time_weighted_height_for_the_0917_run():
    s = _replay_0917()
    assert s.area_seconds["back"] == 148 * 60
    # (3.54 * 11 min + 2.95 * 137 min) / 148 min = 2.994
    assert session.results(s, 600) == [("back", 2.99)]


def test_grace_period():
    s = _replay_0917()
    assert session.ready_to_close(s, t("15:12"), 900) is False
    assert session.ready_to_close(s, t("15:13"), 900) is True


def test_short_areas_dropped_and_missing_height_is_none():
    s = session.start(t("10:00"), area="front", height_in=None)
    session.update(s, t("10:30"), area="side")
    session.update(s, t("10:35"), working=False)
    assert session.results(s, 600) == [("front", None)]


def test_round_trip():
    s = _replay_0917()
    assert session.MowerSession.from_dict(s.to_dict()) == s
