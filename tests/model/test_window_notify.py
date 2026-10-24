from datetime import date, timedelta

from custom_components.lawn_growth.model import notify
from custom_components.lawn_growth.model.applications import Application, SeedingBlock
from custom_components.lawn_growth.model.config import Tunables
from custom_components.lawn_growth.model.windows import Window

TUN = Tunables()
TODAY = date(2027, 4, 12)
NAMES = {"front": "Front & Side", "back": "Back"}


def _reached(*stages, source="gdd", value=130.0, area="", on=TODAY):
    return {s: {"date": on.isoformat(), "source": source, "value": value, "area": area}
            for s in stages}


def _decide(windows, apps=(), blocks=None, today=TODAY):
    return notify.decide_windows({w.key: w for w in windows}, NAMES, apps=list(apps),
                                 tun=TUN, today=today, blocks=blocks)


def test_open_once_per_window_with_the_air_note():
    w = Window("pre_emergent", 2027, status="open", reached=_reached("heads_up", "open"))
    msgs, out = _decide([w])
    assert [m.title for m in msgs] == ["Lawn Growth — pre-emergent"]
    assert msgs[0].message == (
        "Apply pre-emergent now: 130 growing degree days. Crabgrass germination is "
        "expected around 200 GDD.\n" + notify.AIR_NOTE)
    assert out[w.key].notified == ["heads_up", "open"]   # heads-up is not sent late
    assert _decide(out.values())[0] == []


def test_soil_alert_names_the_area_and_has_no_air_note():
    w = Window("pre_emergent", 2027, status="tentative",
               reached=_reached("heads_up", source="geodrops", value=47.3, area="back"))
    [msg], _ = _decide([w])
    assert msg.message == ("Pre-emergent heads-up: soil 47.3 °F in Back. Time to buy "
                           "product — the window opens at 50 °F.")


def test_germination_suggests_dithiopyr():
    w = Window("pre_emergent", 2027, status="open", expected_close=date(2027, 4, 26),
               reached=_reached("heads_up", "open", "late", "germination", value=201.0))
    [msg], _ = _decide([w])
    assert "Dithiopyr still controls very young crabgrass — apply by Apr 26" in msg.message


def test_missed_pre_emergent():
    w = Window("pre_emergent", 2027, status="missed", closed=date(2027, 5, 10),
               reached=_reached("open", "missed"), notified=["open"])
    [msg], _ = _decide([w])
    assert msg.message == "Pre-emergent window missed: nothing logged by May 10."


def test_done_and_skipped_windows_stay_quiet():
    done = Window("pre_emergent", 2027, status="done", done=TODAY,
                  reached=_reached("open"))
    skipped = Window("winterizer", 2026, "back", status="skipped",
                     reached=_reached("open", source="air"))
    msgs, out = _decide([done, skipped])
    assert msgs == []
    assert out[skipped.key].notified == ["open"]


def test_split_reminder_once():
    w = Window("pre_emergent", 2027, status="done", done=date(2027, 4, 1),
               product="prodiamine")
    apps = [Application("herbicide", date(2027, 4, 1), ("front", "back"), "prodiamine")]
    assert _decide([w], apps, today=date(2027, 5, 19))[0] == []
    [msg], out = _decide([w], apps, today=date(2027, 5, 20))
    assert msg.message.startswith("Second pre-emergent due: Prodiamine went down Apr 1.")
    assert _decide(out.values(), apps, today=date(2027, 5, 21))[0] == []


def test_areas_crossing_together_share_one_message():
    ws = [Window("winterizer", 2026, k, status="open",
                 reached=_reached("open", source="air", value=None, area=k))
          for k in ("front", "back")]
    [msg], _ = _decide(ws)
    assert msg.title == "Lawn Growth — winterizer"
    assert msg.message.startswith("Winterizer window open — Front & Side, Back:")


def test_winterizer_missed_does_not_push():
    w = Window("winterizer", 2026, "back", status="missed",
               reached=_reached("open", "missed", source="air"), notified=["open"])
    assert _decide([w])[0] == []


def test_overseed_open_and_closing():
    w = Window("overseed", 2026, "back", status="open",
               reached=_reached("open", source="geodrops", value=68.2, area="back"))
    block = SeedingBlock("prodiamine", date(2026, 4, 8), date(2026, 7, 29))
    [msg], out = _decide([w], blocks={"back": block})
    assert msg.message == ("Overseed window open — Back (soil 68.2 °F). Best while soil "
                           "is 60–70 °F.\nBack: Prodiamine applied Apr 8 — seeding blocked "
                           "until Jul 29.")
    w = out[w.key]
    w.reached.update(_reached("closing", source="geodrops", value=57.0))
    w.expected_close = date(2026, 10, 2)
    [msg], _ = _decide([w])
    assert msg.message == "Overseed window closing in about a week — Back (around Oct 2)."


def test_overseed_air_source_gets_the_note():
    w = Window("overseed", 2026, "back", status="open",
               reached=_reached("open", source="air", value=70.4))
    [msg], _ = _decide([w])
    assert "Back (7-day air mean 70.4 °F)" in msg.message
    assert msg.message.endswith(notify.AIR_NOTE)


# --- post-emergent -----------------------------------------------------------------

def _post_open(kind, area, source="geodrops", value=55.3, **kw):
    return Window(kind, 2027, area, status="open",
                  reached={"open": {"date": TODAY.isoformat(), "source": source,
                                    "value": value, "area": area}}, **kw)


def test_post_emergent_window_open_shares_one_message():
    ws = [_post_open("spring_broadleaf", "front"),
          _post_open("spring_broadleaf", "back", source="gdd", value=260.0)]
    msgs, out = _decide(ws)
    [m] = msgs
    assert m.title == "Lawn Growth — post-emergent"
    assert m.message.startswith(
        "Post-emergent window open (spring broadleaf) — Front & Side (soil 55.3 °F), "
        "Back (260 growing degree days): broadleaf weeds are actively growing.")
    assert m.message.endswith(notify.AIR_NOTE)
    assert all(w.notified == ["open"] for w in out.values())
    crab = _post_open("young_crabgrass", "front", expected_close=date(2027, 6, 25))
    [m], _ = _decide([crab])
    assert "Young crabgrass window open — Front & Side — until Jun 25" in m.message


def _verdict(good=True, mow_first=False, skipped=()):
    from custom_components.lawn_growth.model.postemergent import SprayDay
    return SprayDay(TODAY, good, () if good else ("mowing",), tuple(skipped), (), mow_first)


def test_good_spray_day_notice_at_most_every_three_days():
    w = _post_open("spring_broadleaf", "front", notified=["open"])
    windows = {w.key: w}
    msgs, windows = notify.decide_spray(windows, {"front": _verdict(skipped=("wind",))},
                                        NAMES, today=TODAY, tun=TUN)
    assert [m.message for m in msgs] == [
        "Good spray day tomorrow (Apr 13) — Front & Side. Spray in the morning, then "
        "don't mow for 2 days.\nNot checked: wind (no hourly wind in the forecast)."]
    for days, sent in ((1, 0), (2, 0), (3, 1)):
        msgs, _ = notify.decide_spray(windows, {"front": _verdict()}, NAMES,
                                      today=TODAY + timedelta(days=days), tun=TUN)
        assert len(msgs) == sent, days


def test_spray_notice_mow_first_and_none_after_a_log():
    w = _post_open("fall_broadleaf", "back")
    msgs, _ = notify.decide_spray({w.key: w}, {"back": _verdict(False, mow_first=True)},
                                  NAMES, today=TODAY, tun=TUN)
    assert msgs[0].message == ("Good spray weather tomorrow (Apr 13), but a mow is due — "
                               "Back: mow first, spray 2 days later.")
    sprayed = _post_open("fall_broadleaf", "back", done=TODAY)
    assert notify.decide_spray({w.key: sprayed}, {"back": _verdict()}, NAMES,
                               today=TODAY, tun=TUN)[0] == []
    assert notify.decide_spray({w.key: w}, {"back": _verdict(False)}, NAMES,
                               today=TODAY, tun=TUN)[0] == []


def test_follow_up_reminder_once_on_its_date():
    app = Application("herbicide", TODAY - timedelta(days=21), ("front",), "triclopyr_ester")
    msgs, sent = notify.decide_followups([app], NAMES, [], today=TODAY - timedelta(days=1),
                                         tun=TUN)
    assert msgs == [] and sent == []
    msgs, sent = notify.decide_followups([app], NAMES, [], today=TODAY, tun=TUN)
    assert msgs[0].message.startswith("Post-emergent follow-up — Front & Side: Triclopyr "
                                      "ester went down Mar 22.")
    assert notify.decide_followups([app], NAMES, sent, today=TODAY, tun=TUN)[0] == []
    old, sent = notify.decide_followups([app], NAMES, [], today=TODAY + timedelta(days=8),
                                        tun=TUN)
    assert old == [] and len(sent) == 1                     # flagged, not pushed


def test_dont_mow_text():
    assert notify.dont_mow_text(["Front & Side"], "mesotrione", date(2027, 5, 5), True) == (
        "Front & Side: Mesotrione logged — don't mow until May 5 so it can work. "
        "Mowing allowed stays off until then.")


# --- soil probes back online (spec §1.3) -------------------------------------------

def test_probes_back_online_once_per_switch_and_areas_share_one_message():
    [msg], recorded = notify.decide_probes({"front": "gdd", "back": "gdd"},
                                           {"front": "geodrops", "back": "geodrops"}, NAMES)
    assert msg.title == "Lawn Growth — soil probes"
    assert msg.message == ("Soil probes back online in Front & Side, Back — application "
                           "timing now uses soil temperature.")
    assert recorded == {"front": "geodrops", "back": "geodrops"}
    assert notify.decide_probes(recorded, recorded, NAMES)[0] == []


def test_probes_back_online_only_on_a_gdd_to_soil_switch():
    msgs, recorded = notify.decide_probes({"front": "geodrops", "back": "gdd"},
                                          {"front": "gdd", "back": "gdd"}, NAMES)
    assert msgs == [] and recorded == {"front": "gdd", "back": "gdd"}
    # a first run (or an upgrade) has nothing to compare with
    assert notify.decide_probes({}, {"front": "geodrops"}, NAMES) == (
        [], {"front": "geodrops"})
    # probes taken out of the area's settings forget their source
    assert notify.decide_probes({"front": "gdd"}, {"front": None}, NAMES) == (
        [], {"front": None})


def test_probes_never_online_are_not_back_online():
    """New probes start out training, so the area reads GDD first: it isn't tracked
    until the probes have been online once."""
    msgs, recorded = notify.decide_probes({"front": None}, {"front": "gdd"}, NAMES)
    assert msgs == [] and recorded == {"front": None}
    assert notify.decide_probes(recorded, {"front": "geodrops"}, NAMES) == (
        [], {"front": "geodrops"})
