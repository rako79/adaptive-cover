"""Budowa danych geometrii, klimatu i ustawień koordynatora."""

from __future__ import annotations

from math import isfinite

import datetime as dt

import numpy as np
from homeassistant.util import dt as dt_util

from .climate import ClimateCoverData, ClimateCoverState
from .decision import (
    COLD_PROTECTION_HYSTERESIS,
    inverse_state,
    position_requires_move,
    resolve_cold_protection,
    wind_speed_to_kmh,
)
from .geometry import AdaptiveHorizontalCover, AdaptiveTiltCover, AdaptiveVerticalCover
from .helpers import get_domain, get_safe_state

from .const import (
    CONF_AWNING_ANGLE,
    CONF_AZIMUTH,
    CONF_BLIND_SPOT_ELEVATION,
    CONF_BLIND_SPOT_LEFT,
    CONF_BLIND_SPOT_RIGHT,
    CONF_CLOSE_SUNSET_OFFSET,
    CONF_DEFAULT_HEIGHT,
    CONF_DELTA_POSITION,
    CONF_DELTA_TIME,
    CONF_DISTANCE,
    CONF_ENABLE_BLIND_SPOT,
    CONF_ENABLE_MAX_POSITION,
    CONF_ENABLE_MIN_POSITION,
    CONF_END_ENTITY,
    CONF_END_TIME,
    CONF_ENTITIES,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_HEIGHT_WIN,
    CONF_WINDOW_DEPTH,
    CONF_SILL_HEIGHT,
    CONF_INTERP_END,
    CONF_INTERP_LIST,
    CONF_INTERP_LIST_NEW,
    CONF_INTERP_START,
    CONF_IRRADIANCE_ENTITY,
    CONF_IRRADIANCE_THRESHOLD,
    CONF_IRRADIANCE_THRESHOLD_OFF,
    CONF_IRRADIANCE_THRESHOLD_ON,
    CONF_LENGTH_AWNING,
    CONF_LUX_ENTITY,
    CONF_LUX_THRESHOLD,
    CONF_LUX_THRESHOLD_OFF,
    CONF_LUX_THRESHOLD_ON,
    CONF_MANUAL_OVERRIDE_DURATION,
    CONF_MANUAL_OVERRIDE_RESET,
    CONF_MANUAL_THRESHOLD,
    CONF_GLOBAL_COOLDOWN,
    CONF_MAX_MOVES_PER_DAY,
    CONF_MAX_MOVES_PER_HOUR,
    CONF_MAX_ELEVATION,
    CONF_MAX_POSITION,
    CONF_MIN_ELEVATION,
    CONF_MIN_POSITION,
    CONF_NIGHT_PURGE_ENABLED,
    CONF_NIGHT_PURGE_END_TIME,
    CONF_OUTSIDE_THRESHOLD,
    CONF_OUTSIDETEMP_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_START_ENTITY,
    CONF_START_TIME,
    CONF_START_TIME_WEEKEND,
    CONF_START_TIME_WORKDAY,
    CONF_SUNRISE_OFFSET,
    CONF_SUNSET_OFFSET,
    CONF_SUNSET_POS,
    CONF_TEMP_ENTITY,
    CONF_TEMP_HIGH,
    CONF_TEMP_LOW,
    CONF_TILT_DEPTH,
    CONF_TILT_DISTANCE,
    CONF_TILT_MODE,
    CONF_TRANSPARENT_BLIND,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_FORECAST_TEMP,
    CONF_WEATHER_STATE,
    CONF_WINDOW_ENTITY,
    CONF_WINDOW_OPEN_ACTION,
    CONF_WINDOW_OPEN_POSITION,
    CONF_WORKDAY_ENTITY,
    CONF_RAIN_ENTITY,
    CONF_RAIN_POSITION,
    CONF_WIND_ENTITY,
    CONF_WIND_POSITION,
    CONF_DAWN_MONTH_START,
    CONF_DAWN_MONTH_END,
    CONF_DAWN_DURATION,
    CONF_COLD_THRESHOLD,
    CONF_WIND_THRESHOLD,
    CONF_PURGE_POS,
    CONF_RAIN_NIGHT_ONLY,
    CONF_THERMAL_HOLD_AFTER_SUN,
    CONF_THERMAL_HOLD_DURATION,
    CONF_THERMAL_HOLD_POSITION,
    CONF_THERMAL_HOLD_RELEASE_DELTA,
    WINDOW_ACTION_PAUSE,
)


def state_attr(hass, entity_id: str, attr_name: str):
    """Zwróć bezpiecznie atrybut stanu Home Assistant."""
    state = hass.states.get(entity_id)
    return state.attributes.get(attr_name) if state is not None else None


def _as_float(value, default=None):
    """Zamień wartość Home Assistant na liczbę, gdy jest dostępna."""
    try:
        result = float(value)
        return result if isfinite(result) else default
    except (TypeError, ValueError):
        return default


class CoordinatorDataMixin:
    """Twórz snapshot wejść domenowych bez obsługi zdarzeń i usług."""

    def _update_options(self, options):
        """Update options."""
        self.entities = options.get(CONF_ENTITIES, [])
        self.window_entity = options.get(CONF_WINDOW_ENTITY)
        self.min_change = options.get(CONF_DELTA_POSITION, 1)
        self.time_threshold = options.get(CONF_DELTA_TIME, 2)
        self.global_cooldown = options.get(CONF_GLOBAL_COOLDOWN, 5)
        self.max_moves_per_hour = options.get(CONF_MAX_MOVES_PER_HOUR, 8)
        self.max_moves_per_day = options.get(CONF_MAX_MOVES_PER_DAY, 40)
        self.window_open_action = options.get(
            CONF_WINDOW_OPEN_ACTION, WINDOW_ACTION_PAUSE
        )
        self.window_open_position = options.get(CONF_WINDOW_OPEN_POSITION, 100)
        self.start_time = options.get(CONF_START_TIME)
        self.start_time_entity = options.get(CONF_START_ENTITY)
        self.end_time = options.get(CONF_END_TIME)
        self.end_time_entity = options.get(CONF_END_ENTITY)
        self.manual_reset = options.get(CONF_MANUAL_OVERRIDE_RESET, False)
        self.manual_duration = options.get(
            CONF_MANUAL_OVERRIDE_DURATION, {"minutes": 15}
        )
        if hasattr(self, "manager"):
            self.manager.reset_duration = dt.timedelta(**self.manual_duration)
        self.manual_threshold = options.get(CONF_MANUAL_THRESHOLD)
        self.start_value = options.get(CONF_INTERP_START)
        self.end_value = options.get(CONF_INTERP_END)
        self.normal_list = options.get(CONF_INTERP_LIST)
        self.new_list = options.get(CONF_INTERP_LIST_NEW)

    def _update_manager_and_covers(self):
        self.manager.add_covers(self.entities)
        if not self._manual_toggle:
            for entity in self.manager.manual_controlled:
                self.manager.reset(entity)

    def get_blind_data(self, options):
        """Assign correct class for type of blind."""
        if self._cover_type == "cover_blind":
            cover_data = AdaptiveVerticalCover(
                self.hass,
                self.logger,
                *self.pos_sun,
                *self.common_data(options),
                *self.vertical_data(options),
            )
        if self._cover_type == "cover_awning":
            cover_data = AdaptiveHorizontalCover(
                self.hass,
                self.logger,
                *self.pos_sun,
                *self.common_data(options),
                *self.vertical_data(options),
                *self.horizontal_data(options),
            )
        if self._cover_type == "cover_tilt":
            cover_data = AdaptiveTiltCover(
                self.hass,
                self.logger,
                *self.pos_sun,
                *self.common_data(options),
                *self.tilt_data(options),
            )
        return cover_data

    @property
    def check_adaptive_time(self):
        """Sprawdź gotowy wynik wspólnego resolvera harmonogramu."""
        if self._resolved_schedule is None:
            return True
        return self._resolved_schedule.active(dt_util.now())

    @property
    def climate_night_control_active(self) -> bool:
        """Zezwalaj trybowi klimatycznemu reagować przez całą noc."""
        return bool(
            self._switch_mode
            and getattr(self, "normal_cover_state", None)
            and self.normal_cover_state.cover.sunset_valid
        )

    @property
    def adaptive_movement_allowed(self) -> bool:
        """Uwzględnij nocne sterowanie klimatyczne poza dziennym harmonogramem."""
        return self.check_adaptive_time or self.climate_night_control_active

    @property
    def after_start_time(self):
        """Sprawdź start wyznaczony przez wspólny resolver."""
        start = self._start_time
        return start is None or dt_util.utcnow() >= start

    def _manual_override_deadline(self, reference: dt.datetime) -> dt.datetime:
        """Deleguj termin ręcznego przejęcia do wspólnego resolvera."""
        cover = getattr(getattr(self, "normal_cover_state", None), "cover", None)
        local_reference = dt_util.as_local(reference)
        sunset_today = (
            cover.sun_data.sunset(local_reference.date()) if cover is not None else None
        )
        sunset_tomorrow = (
            cover.sun_data.sunset(local_reference.date() + dt.timedelta(days=1))
            if cover is not None
            else None
        )
        deadline = self.schedule_resolver.manual_override_deadline(
            reference=local_reference,
            duration=self.manual_duration,
            sunset_today=sunset_today,
            sunset_tomorrow=sunset_tomorrow,
            sunset_offset_minutes=self._active_options.get(CONF_SUNSET_OFFSET, 0),
        )
        return dt_util.as_utc(deadline)

    @property
    def _end_time(self) -> dt.datetime | None:
        """Zwróć koniec z ostatniego wspólnego rozstrzygnięcia."""
        if self._resolved_schedule is None:
            return None
        value = self._resolved_schedule.end.value
        return dt_util.as_utc(value) if value is not None else None

    @property
    def before_end_time(self):
        """Sprawdź koniec wyznaczony przez wspólny resolver."""
        end = self._end_time
        return end is None or dt_util.utcnow() < end

    def resolve_schedule(self, options, cover_data) -> None:
        """Pobierz wartości HA i utwórz jeden snapshot harmonogramu."""
        workday_entity = options.get(CONF_WORKDAY_ENTITY)
        self._resolved_schedule = self.schedule_resolver.resolve(
            local_now=dt_util.now(),
            start_entity_configured=self.start_time_entity is not None,
            start_entity_value=get_safe_state(self.hass, self.start_time_entity),
            workday_configured=workday_entity is not None,
            workday_state=get_safe_state(self.hass, workday_entity),
            explicit_start_time=self.start_time,
            workday_start_time=options.get(CONF_START_TIME_WORKDAY, "07:00:00"),
            weekend_start_time=options.get(CONF_START_TIME_WEEKEND, "09:00:00"),
            end_entity_configured=self.end_time_entity is not None,
            end_entity_value=get_safe_state(self.hass, self.end_time_entity),
            explicit_end_time=self.end_time,
            sunset=cover_data.sunset_at,
            sunset_offset_minutes=options.get(CONF_CLOSE_SUNSET_OFFSET, 0),
        )
        self._start_time = (
            dt_util.as_utc(self._resolved_schedule.start.value)
            if self._resolved_schedule.start.value is not None
            else None
        )
        self._last_start_time_resolution = self._resolved_schedule.start
        self._last_end_time_resolution = self._resolved_schedule.end

    def _get_current_position(self, entity) -> int | None:
        """Get current position of cover."""
        cover_state = self.hass.states.get(entity)
        if cover_state is None or cover_state.state in {"unknown", "unavailable"}:
            return None
        if self._cover_type == "cover_tilt":
            position = _as_float(cover_state.attributes.get("current_tilt_position"))
        else:
            position = _as_float(cover_state.attributes.get("current_position"))
        return position if position is not None and 0 <= position <= 100 else None

    def check_position(self, entity, state):
        """Check if position is different as state."""
        position = self._get_current_position(entity)
        if position is not None:
            return position_requires_move(position, state, self.min_change)
        self.logger.debug("No current position available for %s", entity)
        return False

    @property
    def is_window_open(self):
        """Check if the physical window/door is open."""
        if getattr(self, "window_entity", None):
            state = self.hass.states.get(self.window_entity)
            # W Home Assistant kontaktrony (binary_sensor) mają stan 'on', gdy magnes jest oddalony (okno otwarte)
            if state and state.state == "on":
                return True
        return False

    def check_position_delta(self, entity, state: int, options):
        """Check cover positions to reduce calls."""
        position = self._get_current_position(entity)
        if position is not None:
            condition = position_requires_move(position, state, self.min_change)
            self.logger.debug(
                "Entity: %s,  position: %s, state: %s, delta position: %s, min_change: %s, condition: %s",
                entity,
                position,
                state,
                abs(position - state),
                self.min_change,
                condition,
            )
            return condition
        return True

    def check_time_delta(self, entity):
        """Check if time delta is passed."""
        now = dt.datetime.now(dt.UTC)
        movement_history = self.manager.movement_history.get(entity, [])
        if movement_history:
            last_movement = max(movement_history)
            condition = now - last_movement >= dt.timedelta(
                minutes=float(self.time_threshold)
            )
            self.logger.debug(
                "Entity: %s, time delta: %s, threshold: %s, condition: %s",
                entity,
                now - last_movement,
                self.time_threshold,
                condition,
            )
            return condition
        return True

    @property
    def pos_sun(self):
        """Fetch information for sun position."""
        return [
            state_attr(self.hass, "sun.sun", "azimuth"),
            state_attr(self.hass, "sun.sun", "elevation"),
        ]

    def common_data(self, options):
        """Update shared parameters."""
        default_pos = options.get(CONF_DEFAULT_HEIGHT)

        return [
            options.get(CONF_SUNSET_POS),
            options.get(CONF_SUNSET_OFFSET),
            options.get(CONF_SUNRISE_OFFSET, options.get(CONF_SUNSET_OFFSET)),
            self.hass.config.time_zone,
            options.get(CONF_FOV_LEFT),
            options.get(CONF_FOV_RIGHT),
            options.get(CONF_AZIMUTH),
            default_pos,
            options.get(CONF_MAX_POSITION),
            options.get(CONF_MIN_POSITION),
            options.get(CONF_ENABLE_MAX_POSITION, False),
            options.get(CONF_ENABLE_MIN_POSITION, False),
            options.get(CONF_BLIND_SPOT_LEFT),
            options.get(CONF_BLIND_SPOT_RIGHT),
            options.get(CONF_BLIND_SPOT_ELEVATION),
            options.get(CONF_ENABLE_BLIND_SPOT, False),
            options.get(CONF_MIN_ELEVATION, None),
            options.get(CONF_MAX_ELEVATION, None),
        ]

    def _low_light_hysteresis(
        self,
        entity_id: str | None,
        threshold_on: float | None,
        threshold_off: float | None,
        previous: bool | None,
    ) -> bool | None:
        """Return a stable low-light state using separate on/off thresholds."""
        if not entity_id or threshold_on is None or threshold_off is None:
            return previous

        value = _as_float(get_safe_state(self.hass, entity_id))
        if value is None:
            return previous

        low_on = float(threshold_off)
        low_off = float(threshold_on)
        if value <= low_on:
            return True
        if value >= low_off:
            return False
        return previous

    def _temperature_snapshot(self, options) -> tuple[float | None, float | None]:
        """Pobierz temperatury wewnętrzną i zewnętrzną jeden raz."""
        inside_entity = options.get(CONF_TEMP_ENTITY)
        inside = (
            state_attr(self.hass, inside_entity, "current_temperature")
            if inside_entity and get_domain(inside_entity) == "climate"
            else get_safe_state(self.hass, inside_entity)
        )
        outside_entity = options.get(CONF_OUTSIDETEMP_ENTITY)
        outside = get_safe_state(self.hass, outside_entity)
        weather_reference = state_attr(
            self.hass,
            options.get(CONF_WEATHER_ENTITY),
            "temperature",
        )
        if outside_entity is None:
            outside = weather_reference
        raw_outside = _as_float(outside)
        reference = _as_float(weather_reference)
        self._outside_temperature_raw = raw_outside
        self._outside_temperature_reference = reference
        filtered_outside = self._outside_temperature_filter.update(
            raw_outside,
            now=dt_util.utcnow(),
            reference_value=reference,
        )
        return _as_float(inside), filtered_outside

    def _presence_snapshot(self, entity_id: str | None) -> bool:
        """Znormalizuj obecność przed wejściem do silnika domenowego."""
        if not entity_id:
            return True
        value = get_safe_state(self.hass, entity_id)
        if value is None:
            return True
        domain = get_domain(entity_id)
        if domain == "device_tracker":
            return value == "home"
        if domain == "zone":
            return (_as_float(value, 0.0) or 0.0) > 0
        if domain in {"binary_sensor", "input_boolean"}:
            return value == "on"
        return True

    def _wind_snapshot(self, options) -> float:
        """Pobierz wiatr i przelicz go do km/h przed decyzją."""
        wind_entity = options.get(CONF_WIND_ENTITY)
        weather_entity = options.get(CONF_WEATHER_ENTITY)
        if wind_entity:
            value = _as_float(get_safe_state(self.hass, wind_entity), 0.0)
            unit = state_attr(self.hass, wind_entity, "unit_of_measurement")
        else:
            value = _as_float(
                state_attr(self.hass, weather_entity, "wind_speed"),
                0.0,
            )
            unit = state_attr(self.hass, weather_entity, "wind_speed_unit")
        return wind_speed_to_kmh(value or 0.0, unit)

    def _update_light_snapshots(self, options) -> None:
        """Odśwież oba stabilne stany światła z jednego zestawu wartości."""
        self._lux_low_light_state = self._low_light_hysteresis(
            options.get(CONF_LUX_ENTITY),
            options.get(CONF_LUX_THRESHOLD_ON, options.get(CONF_LUX_THRESHOLD)),
            options.get(CONF_LUX_THRESHOLD_OFF, options.get(CONF_LUX_THRESHOLD)),
            self._lux_low_light_state,
        )
        self._irradiance_low_light_state = self._low_light_hysteresis(
            options.get(CONF_IRRADIANCE_ENTITY),
            options.get(
                CONF_IRRADIANCE_THRESHOLD_ON,
                options.get(CONF_IRRADIANCE_THRESHOLD),
            ),
            options.get(
                CONF_IRRADIANCE_THRESHOLD_OFF,
                options.get(CONF_IRRADIANCE_THRESHOLD),
            ),
            self._irradiance_low_light_state,
        )

    def _climate_thresholds(self, options, temp_high) -> dict:
        """Zbuduj część snapshota odpowiadającą za progi komfortu."""
        return {
            "temp_low": options.get(CONF_TEMP_LOW),
            "temp_high": temp_high,
            "temp_switch": self._temp_toggle,
            "transparent_blind": options.get(CONF_TRANSPARENT_BLIND),
            "weather_condition": options.get(CONF_WEATHER_STATE),
            "temp_summer_outside": options.get(CONF_OUTSIDE_THRESHOLD),
            "use_lux": self._lux_toggle,
            "use_irradiance": self._irradiance_toggle,
            "lux_threshold": options.get(CONF_LUX_THRESHOLD),
            "irradiance_threshold": options.get(CONF_IRRADIANCE_THRESHOLD),
            "lux_threshold_on": options.get(
                CONF_LUX_THRESHOLD_ON,
                options.get(CONF_LUX_THRESHOLD),
            ),
            "lux_threshold_off": options.get(
                CONF_LUX_THRESHOLD_OFF,
                options.get(CONF_LUX_THRESHOLD),
            ),
            "irradiance_threshold_on": options.get(
                CONF_IRRADIANCE_THRESHOLD_ON,
                options.get(CONF_IRRADIANCE_THRESHOLD),
            ),
            "irradiance_threshold_off": options.get(
                CONF_IRRADIANCE_THRESHOLD_OFF,
                options.get(CONF_IRRADIANCE_THRESHOLD),
            ),
        }

    def _climate_protection_options(self, options) -> dict:
        """Zbuduj część snapshota odpowiadającą za ochronę."""
        return {
            "dawn_start_month": options.get(CONF_DAWN_MONTH_START, 5),
            "dawn_end_month": options.get(CONF_DAWN_MONTH_END, 10),
            "dawn_duration_min": options.get(CONF_DAWN_DURATION, 60),
            "cold_threshold": options.get(CONF_COLD_THRESHOLD, 16),
            "cold_hysteresis": COLD_PROTECTION_HYSTERESIS,
            "wind_threshold": options.get(CONF_WIND_THRESHOLD, 40),
            "purge_pos": options.get(CONF_PURGE_POS, 15),
            "rain_night_only": options.get(CONF_RAIN_NIGHT_ONLY, False),
            "rain_position": options.get(CONF_RAIN_POSITION, 0),
            "wind_position": options.get(CONF_WIND_POSITION, 0),
            "strict_sun_block_toggle": self._strict_sun_block_toggle,
            "thermal_hold_after_sun": options.get(
                CONF_THERMAL_HOLD_AFTER_SUN,
                False,
            ),
            "thermal_hold_position": options.get(CONF_THERMAL_HOLD_POSITION, 30),
            "thermal_hold_duration": options.get(CONF_THERMAL_HOLD_DURATION, 120),
            "thermal_hold_release_delta": options.get(
                CONF_THERMAL_HOLD_RELEASE_DELTA,
                1.0,
            ),
            "night_purge_enabled": options.get(CONF_NIGHT_PURGE_ENABLED, True),
            "night_purge_end_time": options.get(
                CONF_NIGHT_PURGE_END_TIME,
                "07:00:00",
            ),
        }

    def get_climate_data(self, options, cover_data) -> ClimateCoverData:
        """Zbuduj jeden kompletny snapshot wejść dla silnika klimatu."""
        temp_high = options.get(CONF_TEMP_HIGH)
        if self.entities and temp_high is not None:
            offsets = [self.learner.get_temp_offset(entity) for entity in self.entities]
            temp_high += sum(offsets) / len(offsets)
        self._update_light_snapshots(options)
        inside, outside = self._temperature_snapshot(options)
        cold_threshold = float(options.get(CONF_COLD_THRESHOLD, 16))
        self._cold_protection_active = resolve_cold_protection(
            outside_temperature=outside,
            threshold=cold_threshold,
            night_active=bool(cover_data.sunset_valid),
            previous_active=self._cold_protection_active,
            hysteresis=COLD_PROTECTION_HYSTERESIS,
        )
        weather_entity = options.get(CONF_WEATHER_ENTITY)
        rain_entity = options.get(CONF_RAIN_ENTITY)
        rain_state = self.hass.states.get(rain_entity) if rain_entity else None
        return ClimateCoverData(
            logger=self.logger,
            now=dt_util.as_local(cover_data.snapshot_time),
            sunrise=cover_data.sunrise_at,
            sunset=cover_data.sunset_at,
            blind_type=self._cover_type,
            forecast_temperature=options.get(CONF_WEATHER_FORECAST_TEMP),
            direct_sun_valid=cover_data.direct_sun_valid,
            last_direct_sun_at=self._last_direct_sun_at,
            inside_temperature_value=inside,
            outside_temperature_value=outside,
            cold_protection_active=self._cold_protection_active,
            inside_temperature_entity=options.get(CONF_TEMP_ENTITY),
            outside_temperature_entity=options.get(CONF_OUTSIDETEMP_ENTITY),
            presence=self._presence_snapshot(options.get(CONF_PRESENCE_ENTITY)),
            weather_state=get_safe_state(self.hass, weather_entity),
            cloud_coverage=_as_float(
                state_attr(self.hass, weather_entity, "cloud_coverage")
            ),
            rain_value=get_safe_state(self.hass, rain_entity),
            rain_sensor_configured=rain_entity is not None,
            rain_sensor_available=bool(
                rain_state and rain_state.state not in {"unknown", "unavailable"}
            ),
            sun_above_horizon=get_safe_state(self.hass, "sun.sun") == "above_horizon",
            wind_speed_kmh=self._wind_snapshot(options),
            lux_value=_as_float(
                get_safe_state(self.hass, options.get(CONF_LUX_ENTITY))
            ),
            irradiance_value=_as_float(
                get_safe_state(self.hass, options.get(CONF_IRRADIANCE_ENTITY))
            ),
            lux_low_light_state=self._lux_low_light_state,
            irradiance_low_light_state=self._irradiance_low_light_state,
            lux_entity=options.get(CONF_LUX_ENTITY),
            irradiance_entity=options.get(CONF_IRRADIANCE_ENTITY),
            weather_entity=weather_entity,
            rain_entity=rain_entity,
            wind_entity=options.get(CONF_WIND_ENTITY),
            **self._climate_thresholds(options, temp_high),
            **self._climate_protection_options(options),
        )

    def climate_mode_data(self, options, cover_data):
        """Update climate mode data and control method."""
        climate = self.get_climate_data(options, cover_data)
        climate.night_purge_previous_active = self._night_purge_active
        has_direct_sun = cover_data.direct_sun_valid and not climate.is_raining
        if climate.irradiance_entity:
            irradiance = climate.irradiance_value
            direct_sun_threshold = (
                climate.irradiance_threshold_off
                if climate.irradiance_threshold_off is not None
                else climate.irradiance_threshold
            )
            has_direct_sun = bool(
                has_direct_sun
                and irradiance is not None
                and direct_sun_threshold is not None
                and irradiance > float(direct_sun_threshold)
            )
        elif climate.weather_entity:
            has_direct_sun = has_direct_sun and climate.is_sunny

        if has_direct_sun:
            self._last_direct_sun_at = dt_util.utcnow()
            self.learner.remember_direct_sun(self._last_direct_sun_at)
        elif self._direct_sun_was_active and self._last_direct_sun_at is not None:
            self.learner.remember_direct_sun(self._last_direct_sun_at, force=True)
        self._direct_sun_was_active = has_direct_sun

        climate.last_direct_sun_at = self._last_direct_sun_at
        climate_state = ClimateCoverState(cover_data, climate)
        decision = climate_state.get_decision()
        self._night_purge_active = self._switch_mode and decision.code == "night_purge"
        self._calculated_decision = decision
        self.climate_state = round(decision.target_position)
        self.last_decision_trace = list(climate_state.decision_trace)
        climate_data = climate_state.climate_data
        self.last_climate_data = climate_data
        self.control_method = "intermediate"
        if climate_data.is_summer and self.switch_mode:
            self.control_method = "summer"
        elif climate_data.is_winter and self.switch_mode:
            self.control_method = "winter"
        self.logger.debug(
            "Climate mode control method was set to %s", self.control_method
        )

    def vertical_data(self, options):
        """Update data for vertical blinds."""
        return [
            options.get(CONF_DISTANCE),
            options.get(CONF_HEIGHT_WIN),
            options.get(CONF_WINDOW_DEPTH)
            if options.get(CONF_WINDOW_DEPTH) is not None
            else 0.0,
            options.get(CONF_SILL_HEIGHT)
            if options.get(CONF_SILL_HEIGHT) is not None
            else 0.0,
        ]

    def horizontal_data(self, options):
        """Update data for horizontal blinds."""
        return [
            options.get(CONF_LENGTH_AWNING),
            options.get(CONF_AWNING_ANGLE),
        ]

    def tilt_data(self, options):
        """Update data for tilted blinds."""
        return [
            options.get(CONF_TILT_DISTANCE),
            options.get(CONF_TILT_DEPTH),
            options.get(CONF_TILT_MODE),
        ]

    @property
    def state(self) -> int:
        """Handle the output of the state based on mode."""
        self.logger.debug(
            "Basic position: %s; Climate position: %s; Using climate position? %s",
            self.default_state,
            self.climate_state,
            self._switch_mode,
        )
        if self._switch_mode:
            state = self.climate_state
        else:
            state = self.default_state

        if self._use_interpolation:
            self.logger.debug("Interpolating position: %s", state)
            state = self.interpolate_states(state)

        if self._inverse_state and self._use_interpolation:
            self.logger.info(
                "Inverse state is not supported with interpolation, you can inverse the state by arranging the list from high to low"
            )

        if self._inverse_state and not self._use_interpolation:
            state = inverse_state(state)
            self.logger.debug("Inversed position: %s", state)

        if not np.isfinite(state):
            self.logger.error(
                "Calculated position is not finite; using default position"
            )
            state = self.default_state
        state = int(np.clip(round(state), 0, 100))
        self.logger.debug("Final position to use: %s", state)
        return state

    def interpolate_states(self, state):
        """Interpolate states."""
        normal_range = [0, 100]
        new_range = []
        if self.start_value is not None and self.end_value is not None:
            new_range = [self.start_value, self.end_value]
        if self.normal_list and self.new_list:
            normal_range = list(map(int, self.normal_list))
            new_range = list(map(int, self.new_list))
        if new_range:
            state = np.interp(state, normal_range, new_range)
            if state == new_range[0]:
                state = 0
            if state == new_range[-1]:
                state = 100
        return state

    @property
    def switch_mode(self):
        """Let switch toggle climate mode."""
        return self._switch_mode

    @switch_mode.setter
    def switch_mode(self, value):
        self._switch_mode = value

    @property
    def temp_toggle(self):
        """Let switch toggle between inside or outside temperature."""
        return self._temp_toggle

    @temp_toggle.setter
    def temp_toggle(self, value):
        self._temp_toggle = value

    @property
    def control_toggle(self):
        """Toggle automation."""
        return self._control_toggle

    @control_toggle.setter
    def control_toggle(self, value):
        self._control_toggle = value

    @property
    def manual_toggle(self):
        """Toggle automation."""
        return self._manual_toggle

    @manual_toggle.setter
    def manual_toggle(self, value):
        self._manual_toggle = value

    @property
    def lux_toggle(self):
        """Toggle automation."""
        return self._lux_toggle

    @lux_toggle.setter
    def lux_toggle(self, value):
        self._lux_toggle = value

    @property
    def irradiance_toggle(self):
        """Toggle automation."""
        return self._irradiance_toggle

    @irradiance_toggle.setter
    def irradiance_toggle(self, value):
        self._irradiance_toggle = value

    @property
    def strict_sun_block_toggle(self):
        """Toggle strict sun block."""
        return self._strict_sun_block_toggle

    @strict_sun_block_toggle.setter
    def strict_sun_block_toggle(self, value):
        self._strict_sun_block_toggle = value

    @property
    def dry_run_toggle(self):
        """Toggle dry-run mode."""
        return self._dry_run_toggle

    @dry_run_toggle.setter
    def dry_run_toggle(self, value):
        self._dry_run_toggle = value
