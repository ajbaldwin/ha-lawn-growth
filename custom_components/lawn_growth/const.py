"""Constants for the Lawn Growth integration (no Home Assistant imports)."""
DOMAIN = "lawn_growth"
STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 2      # 1.2: application log, windows

# entry.options — lawn level
CONF_WEATHER = "weather_entity"
CONF_SEASON = "season_entity"
CONF_NOTIFY = "notify_service"
CONF_RUN_TIME = "run_time"
CONF_MOWER = "mower"
CONF_AREAS = "areas"
CONF_OUTDOOR_TEMP = "outdoor_temp_entity"
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
AREA_SOIL_DEPTH = "soil_temp_depth"

# GeoDrops temperature depths: d1 = 1.5", d2 = 2.5", d3 = 3.5"
SOIL_DEPTHS = ("d1", "d2", "d3")
DEFAULT_SOIL_DEPTH = "d2"

MOW_MODE_INCREASES = "number_increases"
MOW_MODE_ANY = "any_change"
