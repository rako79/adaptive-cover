"""Normalizacja i walidacja opcji Adaptive Cover."""

from __future__ import annotations

from copy import deepcopy
from datetime import time, timedelta

from . import const as c

DEFAULT_OPTIONS = {
    c.CONF_MODE: c.STRATEGY_MODE_BASIC,
    c.CONF_AZIMUTH: 180,
    c.CONF_HEIGHT_WIN: None,
    c.CONF_DISTANCE: None,
    c.CONF_WINDOW_DEPTH: 0.0,
    c.CONF_SILL_HEIGHT: 0.0,
    c.CONF_SHADED_HEIGHT_DELTA: 0.0,
    c.CONF_DEFAULT_HEIGHT: 60,
    c.CONF_DEFAULT_HEIGHT_SUMMER: None,
    c.CONF_DEFAULT_HEIGHT_WINTER: None,
    c.CONF_MAX_POSITION: None,
    c.CONF_MIN_POSITION: None,
    c.CONF_ENABLE_MAX_POSITION: False,
    c.CONF_ENABLE_MIN_POSITION: False,
    c.CONF_FOV_LEFT: 90,
    c.CONF_FOV_RIGHT: 90,
    c.CONF_ENTITIES: [],
    c.CONF_INVERSE_STATE: False,
    c.CONF_SUNSET_POS: 0,
    c.CONF_SUNSET_OFFSET: 0,
    c.CONF_SUNRISE_OFFSET: 0,
    c.CONF_LENGTH_AWNING: None,
    c.CONF_AWNING_ANGLE: None,
    c.CONF_TILT_DISTANCE: None,
    c.CONF_TILT_DEPTH: None,
    c.CONF_TILT_MODE: None,
    c.CONF_TEMP_ENTITY: None,
    c.CONF_PRESENCE_ENTITY: None,
    c.CONF_WEATHER_ENTITY: None,
    c.CONF_TEMP_LOW: 21,
    c.CONF_TEMP_HIGH: 25,
    c.CONF_OUTSIDETEMP_ENTITY: None,
    c.CONF_CLIMATE_MODE: False,
    c.CONF_WEATHER_STATE: ["sunny", "partlycloudy", "cloudy", "clear"],
    c.CONF_DELTA_POSITION: 1,
    c.CONF_DELTA_TIME: 2,
    c.CONF_GLOBAL_COOLDOWN: 5,
    c.CONF_MAX_MOVES_PER_HOUR: 8,
    c.CONF_MAX_MOVES_PER_DAY: 40,
    c.CONF_START_TIME: "00:00:00",
    c.CONF_START_ENTITY: None,
    c.CONF_END_TIME: "00:00:00",
    c.CONF_END_ENTITY: None,
    c.CONF_RETURN_SUNSET: False,
    c.CONF_MANUAL_OVERRIDE_DURATION: {"minutes": 15},
    c.CONF_MANUAL_OVERRIDE_RESET: False,
    c.CONF_MANUAL_THRESHOLD: None,
    c.CONF_MANUAL_IGNORE_INTERMEDIATE: False,
    c.CONF_BLIND_SPOT_RIGHT: None,
    c.CONF_BLIND_SPOT_LEFT: None,
    c.CONF_BLIND_SPOT_ELEVATION: None,
    c.CONF_ENABLE_BLIND_SPOT: False,
    c.CONF_MIN_ELEVATION: None,
    c.CONF_MAX_ELEVATION: None,
    c.CONF_TRANSPARENT_BLIND: False,
    c.CONF_INTERP: False,
    c.CONF_INTERP_START: None,
    c.CONF_INTERP_END: None,
    c.CONF_INTERP_LIST: [],
    c.CONF_INTERP_LIST_NEW: [],
    c.CONF_LUX_ENTITY: None,
    c.CONF_LUX_THRESHOLD: 1000,
    c.CONF_LUX_THRESHOLD_ON: 1200,
    c.CONF_LUX_THRESHOLD_OFF: 800,
    c.CONF_IRRADIANCE_ENTITY: None,
    c.CONF_IRRADIANCE_THRESHOLD: 300,
    c.CONF_IRRADIANCE_THRESHOLD_ON: 350,
    c.CONF_IRRADIANCE_THRESHOLD_OFF: 250,
    c.CONF_OUTSIDE_THRESHOLD: 0,
    c.CONF_RAIN_ENTITY: None,
    c.CONF_WIND_ENTITY: None,
    c.CONF_RAIN_POSITION: 0,
    c.CONF_WIND_POSITION: 0,
    c.CONF_DAWN_MONTH_START: 5,
    c.CONF_DAWN_MONTH_END: 10,
    c.CONF_DAWN_DURATION: 60,
    c.CONF_COLD_THRESHOLD: 16,
    c.CONF_WIND_THRESHOLD: 40,
    c.CONF_WIND_CONFIRMATION_SAMPLES: 1,
    c.CONF_NIGHT_PURGE_ENABLED: True,
    c.CONF_NIGHT_PURGE_END_TIME: "07:00:00",
    c.CONF_PURGE_POS: 15,
    c.CONF_THERMAL_HOLD_AFTER_SUN: False,
    c.CONF_THERMAL_HOLD_POSITION: 30,
    c.CONF_THERMAL_HOLD_DURATION: 120,
    c.CONF_THERMAL_HOLD_RELEASE_DELTA: 1.0,
    c.CONF_RAIN_NIGHT_ONLY: False,
    c.CONF_WINDOW_ENTITY: None,
    c.CONF_WINDOW_OPEN_ACTION: c.WINDOW_ACTION_PAUSE,
    c.CONF_WINDOW_OPEN_POSITION: 100,
    c.CONF_WORKDAY_ENTITY: None,
    c.CONF_START_TIME_WORKDAY: "07:00:00",
    c.CONF_START_TIME_WEEKEND: "09:00:00",
    c.CONF_CLOSE_SUNSET_OFFSET: 0,
}


def normalize_options(options: dict | None) -> dict:
    """Zwróć kompletny i niezależny słownik opcji."""
    normalized = deepcopy(DEFAULT_OPTIONS)
    normalized.update(dict(options or {}))
    wind_samples = normalized[c.CONF_WIND_CONFIRMATION_SAMPLES]
    if (
        type(wind_samples) is not int
        or not 1 <= wind_samples <= c.MAX_WIND_CONFIRMATION_SAMPLES
    ):
        normalized[c.CONF_WIND_CONFIRMATION_SAMPLES] = 1
    if not isinstance(normalized.get(c.CONF_ENTITIES), list):
        normalized[c.CONF_ENTITIES] = []
    duration = normalized.get(c.CONF_MANUAL_OVERRIDE_DURATION)
    if not isinstance(duration, dict):
        normalized[c.CONF_MANUAL_OVERRIDE_DURATION] = deepcopy(
            DEFAULT_OPTIONS[c.CONF_MANUAL_OVERRIDE_DURATION]
        )
    else:
        try:
            total_minutes = max(
                0,
                round(
                    timedelta(
                        **{
                            key: float(value)
                            for key, value in duration.items()
                            if key
                            in {
                                "weeks",
                                "days",
                                "hours",
                                "minutes",
                                "seconds",
                                "milliseconds",
                            }
                        }
                    ).total_seconds()
                    / 60
                ),
            )
            normalized[c.CONF_MANUAL_OVERRIDE_DURATION] = {"minutes": total_minutes}
        except (TypeError, ValueError, OverflowError):
            normalized[c.CONF_MANUAL_OVERRIDE_DURATION] = deepcopy(
                DEFAULT_OPTIONS[c.CONF_MANUAL_OVERRIDE_DURATION]
            )
    if not normalized.get(c.CONF_NIGHT_PURGE_END_TIME):
        normalized[c.CONF_NIGHT_PURGE_END_TIME] = DEFAULT_OPTIONS[
            c.CONF_NIGHT_PURGE_END_TIME
        ]
    return normalized


def _validate_time(
    values: dict,
    key: str,
    error: str,
    errors: list[str],
) -> None:
    """Dodaj błąd, jeśli opcja nie zawiera poprawnej lokalnej godziny."""
    try:
        time.fromisoformat(values[key])
    except (TypeError, ValueError):
        errors.append(error)


def validate_options(options: dict | None) -> list[str]:
    """Zwróć błędy zależności pomiędzy zapisanymi opcjami."""
    values = normalize_options(options)
    errors: list[str] = []

    temp_low = values[c.CONF_TEMP_LOW]
    temp_high = values[c.CONF_TEMP_HIGH]
    if temp_low is not None and temp_high is not None and temp_low >= temp_high:
        errors.append("temp_low_must_be_lower_than_temp_high")

    lux_off = values[c.CONF_LUX_THRESHOLD_OFF]
    lux_on = values[c.CONF_LUX_THRESHOLD_ON]
    if lux_off is not None and lux_on is not None and lux_off > lux_on:
        errors.append("lux_off_must_not_exceed_on")

    irradiance_off = values[c.CONF_IRRADIANCE_THRESHOLD_OFF]
    irradiance_on = values[c.CONF_IRRADIANCE_THRESHOLD_ON]
    if (
        irradiance_off is not None
        and irradiance_on is not None
        and irradiance_off > irradiance_on
    ):
        errors.append("irradiance_off_must_not_exceed_on")

    min_position = values[c.CONF_MIN_POSITION]
    max_position = values[c.CONF_MAX_POSITION]
    if (
        min_position is not None
        and max_position is not None
        and min_position > max_position
    ):
        errors.append("min_position_must_not_exceed_max_position")

    _validate_time(
        values,
        c.CONF_START_TIME,
        "start_time_must_be_valid",
        errors,
    )
    _validate_time(
        values,
        c.CONF_END_TIME,
        "end_time_must_be_valid",
        errors,
    )
    _validate_time(
        values,
        c.CONF_NIGHT_PURGE_END_TIME,
        "night_purge_end_time_must_be_valid",
        errors,
    )
    if values.get(c.CONF_WORKDAY_ENTITY):
        _validate_time(
            values,
            c.CONF_START_TIME_WORKDAY,
            "start_time_workday_must_be_valid",
            errors,
        )
        _validate_time(
            values,
            c.CONF_START_TIME_WEEKEND,
            "start_time_weekend_must_be_valid",
            errors,
        )

    source = values[c.CONF_INTERP_LIST] or []
    target = values[c.CONF_INTERP_LIST_NEW] or []
    if values[c.CONF_INTERP] and len(source) != len(target):
        errors.append("interpolation_lists_must_have_equal_length")
    try:
        source_values = list(map(int, source))
        target_values = list(map(int, target))
        if source_values and any(
            current >= following
            for current, following in zip(source_values, source_values[1:])
        ):
            errors.append("interpolation_source_must_be_strictly_increasing")
        if any(value < 0 or value > 100 for value in source_values + target_values):
            errors.append("interpolation_values_must_be_between_0_and_100")
    except (TypeError, ValueError):
        errors.append("interpolation_values_must_be_integers")

    return errors
