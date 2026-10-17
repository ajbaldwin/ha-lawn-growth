from datetime import date

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
