"""Constants for integration_blueprint."""

import logging

DOMAIN = "adaptive_cover"
LOGGER = logging.getLogger(__package__)
_LOGGER = logging.getLogger(__name__)

ATTR_POSITION = "position"
ATTR_TILT_POSITION = "tilt_position"

CONF_AZIMUTH = "set_azimuth"
CONF_BLUEPRINT = "blueprint"
CONF_HEIGHT_WIN = "window_height"
CONF_DISTANCE = "distance_shaded_area"
CONF_WINDOW_DEPTH = "window_depth"
CONF_SILL_HEIGHT = "sill_height"
CONF_DEFAULT_HEIGHT = "default_percentage"
CONF_FOV_LEFT = "fov_left"
CONF_FOV_RIGHT = "fov_right"
CONF_ENTITIES = "group"
CONF_HEIGHT_AWNING = "height_awning"
CONF_LENGTH_AWNING = "length_awning"
CONF_AWNING_ANGLE = "angle"
CONF_SENSOR_TYPE = "sensor_type"
CONF_INVERSE_STATE = "inverse_state"
CONF_SUNSET_POS = "sunset_position"
CONF_SUNSET_OFFSET = "sunset_offset"
CONF_TILT_DEPTH = "slat_depth"
CONF_TILT_DISTANCE = "slat_distance"
CONF_TILT_MODE = "tilt_mode"
CONF_SUNSET_POS = "sunset_position"
CONF_SUNSET_OFFSET = "sunset_offset"
CONF_SUNRISE_OFFSET = "sunrise_offset"
CONF_TEMP_ENTITY = "temp_entity"
CONF_PRESENCE_ENTITY = "presence_entity"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_TEMP_LOW = "temp_low"
CONF_TEMP_HIGH = "temp_high"
CONF_MODE = "mode"
CONF_CLIMATE_MODE = "climate_mode"
CONF_WEATHER_STATE = "weather_state"
CONF_MAX_POSITION = "max_position"
CONF_MIN_POSITION = "min_position"
CONF_ENABLE_MAX_POSITION = "enable_max_position"
CONF_ENABLE_MIN_POSITION = "enable_min_position"
CONF_OUTSIDETEMP_ENTITY = "outside_temp"
CONF_ENABLE_BLIND_SPOT = "blind_spot"
CONF_BLIND_SPOT_RIGHT = "blind_spot_right"
CONF_BLIND_SPOT_LEFT = "blind_spot_left"
CONF_BLIND_SPOT_ELEVATION = "blind_spot_elevation"
CONF_MIN_ELEVATION = "min_elevation"
CONF_MAX_ELEVATION = "max_elevation"
CONF_TRANSPARENT_BLIND = "transparent_blind"
CONF_INTERP_START = "interp_start"
CONF_INTERP_END = "interp_end"
CONF_INTERP_LIST = "interp_list"
CONF_INTERP_LIST_NEW = "interp_list_new"
CONF_INTERP = "interp"
CONF_LUX_ENTITY = "lux_entity"
CONF_LUX_THRESHOLD = "lux_threshold"
CONF_IRRADIANCE_ENTITY = "irradiance_entity"
CONF_IRRADIANCE_THRESHOLD = "irradiance_threshold"
CONF_OUTSIDE_THRESHOLD = "outside_threshold"
CONF_DAWN_MONTH_START = "dawn_month_start"
CONF_DAWN_MONTH_END = "dawn_month_end"
CONF_DAWN_DURATION = "dawn_duration"
CONF_COLD_THRESHOLD = "cold_threshold"
CONF_WIND_THRESHOLD = "wind_threshold"
CONF_PURGE_POS = "purge_pos"
CONF_WORKDAY_ENTITY = "workday_entity"
CONF_START_TIME_WORKDAY = "start_time_workday"
CONF_START_TIME_WEEKEND = "start_time_weekend"
CONF_CLOSE_SUNSET_OFFSET = "close_sunset_offset"
CONF_RAIN_NIGHT_ONLY = "rain_night_only"
CONF_WEATHER_FORECAST_TEMP = "weather_forecast_temp"
CONF_RAIN_POSITION = "rain_position"
CONF_WIND_POSITION = "wind_position"
CONF_LUX_THRESHOLD_ON = "lux_threshold_on"
CONF_LUX_THRESHOLD_OFF = "lux_threshold_off"
CONF_IRRADIANCE_THRESHOLD_ON = "irradiance_threshold_on"
CONF_IRRADIANCE_THRESHOLD_OFF = "irradiance_threshold_off"

CONF_DELTA_POSITION = "delta_position"
CONF_DELTA_TIME = "delta_time"
CONF_GLOBAL_COOLDOWN = "global_cooldown"
CONF_MAX_MOVES_PER_HOUR = "max_moves_per_hour"
CONF_MAX_MOVES_PER_DAY = "max_moves_per_day"
CONF_START_TIME = "start_time"
CONF_START_ENTITY = "start_entity"
CONF_END_TIME = "end_time"
CONF_END_ENTITY = "end_entity"
CONF_RETURN_SUNSET = "return_sunset"
CONF_MANUAL_OVERRIDE_DURATION = "manual_override_duration"
CONF_MANUAL_OVERRIDE_RESET = "manual_override_reset"
CONF_MANUAL_THRESHOLD = "manual_threshold"
CONF_MANUAL_IGNORE_INTERMEDIATE = "manual_ignore_intermediate"

CONF_WINDOW_ENTITY = "window_entity"
CONF_WINDOW_OPEN_ACTION = "window_open_action"
CONF_WINDOW_OPEN_POSITION = "window_open_position"
CONF_RAIN_ENTITY = "rain_entity"
CONF_WIND_ENTITY = "wind_entity"

WINDOW_ACTION_PAUSE = "pause"
WINDOW_ACTION_MOVE_TO_POSITION = "move_to_position"
WINDOW_ACTION_BLOCK_CLOSING_ONLY = "block_closing_only"
WINDOW_ACTION_RETURN_AFTER_CLOSE = "return_after_close"
WINDOW_OPEN_ACTIONS = [
    WINDOW_ACTION_PAUSE,
    WINDOW_ACTION_MOVE_TO_POSITION,
    WINDOW_ACTION_BLOCK_CLOSING_ONLY,
    WINDOW_ACTION_RETURN_AFTER_CLOSE,
]

STRATEGY_MODE_BASIC = "basic"
STRATEGY_MODE_CLIMATE = "climate"
STRATEGY_MODES = [
    STRATEGY_MODE_BASIC,
    STRATEGY_MODE_CLIMATE,
]


class SensorType:
    """Possible modes for a number selector."""

    BLIND = "cover_blind"
    AWNING = "cover_awning"
    TILT = "cover_tilt"
