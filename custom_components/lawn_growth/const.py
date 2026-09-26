"""Constants for the Lawn Growth integration (no Home Assistant imports)."""
DOMAIN = "lawn_growth"
STORAGE_VERSION = 1

# entry.options — lawn level
CONF_WEATHER = "weather_entity"
CONF_SEASON = "season_entity"
CONF_NOTIFY = "notify_service"
CONF_RUN_TIME = "run_time"
CONF_MOWER = "mower"
CONF_AREAS = "areas"
DEFAULT_RUN_TIME = "05:00:00"

# entry.options[CONF_MOWER]
MOWER_ACTIVITY = "activity_entity"
MOWER_WORKING = "working_states"
MOWER_BLADE = "blade_entity"
MOWER_LOCATION = "location_entity"
MOWER_GRACE = "grace_minutes"
MOWER_MIN_AREA = "min_area_minutes"
DEFAULT_GRACE_MINUTES = 15
DEFAULT_MIN_AREA_MINUTES = 10

# entry.options[CONF_AREAS][i] — one dict per mowing area
AREA_KEY = "key"
AREA_NAME = "name"
AREA_GRASS = "grass"
AREA_CURVE = "curve"
AREA_CUT_MIN = "cut_min_in"
AREA_CUT_MAX = "cut_max_in"
AREA_OVERSEED_TARGET = "overseed_target_in"
AREA_MOISTURE = "moisture_sensors"
AREA_WILTING = "wilting_moisture"
AREA_COMFORTABLE = "comfortable_moisture"
AREA_MOW_SOURCE = "mow_source_entity"
AREA_MOW_MODE = "mow_source_mode"
AREA_LOCATIONS = "mower_locations"
AREA_MAX_RATE = "max_growth_rate_mm"

MOW_MODE_INCREASES = "number_increases"
MOW_MODE_ANY = "any_change"
