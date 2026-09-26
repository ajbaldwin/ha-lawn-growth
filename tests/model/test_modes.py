from custom_components.lawn_growth.model import modes


def test_precedence():
    assert modes.resolve_mode(False, True, True, True, True) == "out_of_season"
    assert modes.resolve_mode(True, True, False, True, True) == "establishment"
    assert modes.resolve_mode(True, False, True, True, True) == "first_mow_ready"
    assert modes.resolve_mode(True, False, False, True, True) == "dormant"
    assert modes.resolve_mode(True, False, False, False, True) == "heat_hold"
    assert modes.resolve_mode(True, False, False, False, False) == "normal"


def test_modes_list_includes_overlay():
    assert modes.MODES == ["out_of_season", "establishment", "first_mow_ready",
                           "dormant", "heat_hold", "overseed_prep", "normal"]
