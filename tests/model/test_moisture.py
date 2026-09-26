from custom_components.lawn_growth.model import moisture


def test_usable_when_dominant_numeric_and_quality_ok():
    assert moisture.usable_moisture("55.0", ("Good", "Good", "Poor")) == 55.0


def test_poor_counts_as_usable():
    # Poor is accepted (GeoDrops reports it routinely); 2 usable of 3 -> ok.
    assert moisture.usable_moisture("40", ("Poor", "Poor", "Bad")) == 40.0


def test_training_excluded_when_too_few_usable():
    # Only 1 depth usable (Good) -> below MIN_USABLE_DEPTHS -> None.
    assert moisture.usable_moisture("40", ("Training", "Training", "Good")) is None


def test_unavailable_or_empty_dominant_is_none():
    assert moisture.usable_moisture("unavailable", ("Good", "Good", "Good")) is None
    assert moisture.usable_moisture("", ("Good", "Good", "Good")) is None


def test_nonnumeric_dominant_is_none():
    assert moisture.usable_moisture("Dry", ("Good", "Good", "Good")) is None


def test_average_uses_only_trusted_readings():
    readings = [
        ("50", ("Good", "Good", "Good")),           # trusted -> 50
        ("70", ("Training", "Training", "Good")),   # excluded (1 usable)
        ("unavailable", ("Good", "Good", "Good")),  # excluded (dominant)
        ("60", ("Good", "Poor", "Bad")),            # trusted -> 60
    ]
    assert moisture.average_usable(readings) == 55.0


def test_average_none_when_nothing_trusted():
    readings = [
        ("unavailable", ("Good", "Good", "Good")),
        ("40", ("Training", "Bad", "Unknown")),
    ]
    assert moisture.average_usable(readings) is None


def test_quality_compare_is_case_insensitive():
    # GeoDrops 0.6+ reports lowercase enum states; older releases report "Good".
    assert moisture.usable_moisture("55", ("good", "poor", "bad")) == 55.0
    assert moisture.usable_moisture("55", ("GOOD", "Training", "training")) is None


def test_no_quality_sensors_means_trusted_when_numeric():
    # Non-GeoDrops sensors have no depth qualities: a numeric reading is used as-is.
    assert moisture.usable_moisture("31.5", ()) == 31.5
    assert moisture.usable_moisture("unavailable", ()) is None
