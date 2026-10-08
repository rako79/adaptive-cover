"""Czyste dane wejściowe i reguły decyzji klimatycznych Adaptive Cover."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from math import isfinite
from typing import Any

import numpy as np

from .decision import (
    DecisionArbiter,
    DecisionResult,
    decision_priority,
    is_night_purge_window_active,
    numeric_value_above_threshold,
    should_hold_thermal_protection,
)
from .geometry import NormalCoverState


def _as_float(value: Any, default: float | None = None) -> float | None:
    """Zamień wartość snapshota na liczbę."""
    with contextlib.suppress(TypeError, ValueError):
        result = float(value)
        return result if isfinite(result) else default
    return default


@dataclass(slots=True)
class TemperatureStabilityFilter:
    """Odrzucaj krótkie skoki temperatury nieosiągalne fizycznie."""

    max_step: float = 3.0
    confirmation_period: timedelta = timedelta(minutes=5)
    candidate_tolerance: float = 2.0
    accepted_value: float | None = None
    accepted_at: datetime | None = None
    accepted_source: str | None = None
    candidate_value: float | None = None
    candidate_since: datetime | None = None
    last_raw_value: float | None = None
    last_reference_value: float | None = None
    last_rejected_at: datetime | None = None
    rejected_count: int = 0

    def _accept(self, value: float, now: datetime, source: str) -> float:
        """Zapisz potwierdzoną wartość i wyczyść kandydata."""
        self.accepted_value = value
        self.accepted_at = now
        self.accepted_source = source
        self.candidate_value = None
        self.candidate_since = None
        return value

    def update(
        self,
        value: float | None,
        *,
        now: datetime,
        reference_value: float | None = None,
    ) -> float | None:
        """Zwróć stabilną wartość po potwierdzeniu dużej zmiany w czasie."""
        self.last_raw_value = value
        self.last_reference_value = reference_value
        if value is None:
            self.candidate_value = None
            self.candidate_since = None
            return None

        raw = float(value)
        reference = float(reference_value) if reference_value is not None else None
        if self.accepted_value is None:
            if reference is None or abs(raw - reference) <= self.max_step:
                return self._accept(raw, now, "sensor")
            self._accept(reference, now, "weather_reference")

        if abs(raw - float(self.accepted_value)) <= self.max_step:
            return self._accept(raw, now, "sensor")

        if self.candidate_value is None or (
            abs(raw - self.candidate_value) > self.candidate_tolerance
        ):
            self.candidate_value = raw
            self.candidate_since = now

        self.last_rejected_at = now
        self.rejected_count += 1
        if (
            self.candidate_since is not None
            and now - self.candidate_since >= self.confirmation_period
        ):
            return self._accept(raw, now, "confirmed_step")
        return self.accepted_value

    def diagnostics(self) -> dict[str, Any]:
        """Zwróć stan filtra potrzebny do analizy kolejnego eksportu."""
        return {
            "raw_value": self.last_raw_value,
            "reference_value": self.last_reference_value,
            "accepted_value": self.accepted_value,
            "accepted_at": self.accepted_at,
            "accepted_source": self.accepted_source,
            "candidate_value": self.candidate_value,
            "candidate_since": self.candidate_since,
            "last_rejected_at": self.last_rejected_at,
            "rejected_count": self.rejected_count,
            "max_step": self.max_step,
            "confirmation_seconds": self.confirmation_period.total_seconds(),
        }


@dataclass(kw_only=True, slots=True)
class ClimateCoverData:
    """Niemutowalny podczas decyzji snapshot klimatu i konfiguracji."""

    logger: Any
    now: datetime
    sunrise: datetime | None
    sunset: datetime | None
    temp_low: float | None
    temp_high: float | None
    temp_switch: bool
    blind_type: str
    transparent_blind: bool
    weather_condition: list[str] | None
    temp_summer_outside: float | None
    use_lux: bool
    use_irradiance: bool
    lux_threshold: float | None
    irradiance_threshold: float | None
    lux_threshold_on: float | None
    lux_threshold_off: float | None
    irradiance_threshold_on: float | None
    irradiance_threshold_off: float | None
    lux_low_light_state: bool | None
    irradiance_low_light_state: bool | None
    rain_night_only: bool
    rain_position: int
    wind_position: int
    dawn_start_month: int
    dawn_end_month: int
    dawn_duration_min: int
    cold_threshold: float
    cold_hysteresis: float
    cold_protection_active: bool
    wind_threshold: float
    purge_pos: int
    strict_sun_block_toggle: bool
    forecast_temperature: float | None
    thermal_hold_after_sun: bool
    thermal_hold_position: int
    thermal_hold_duration: int
    thermal_hold_release_delta: float
    direct_sun_valid: bool
    last_direct_sun_at: datetime | None
    night_purge_enabled: bool
    night_purge_end_time: str
    inside_temperature_value: float | None
    outside_temperature_value: float | None
    presence: bool
    weather_state: str | None
    cloud_coverage: float | None
    rain_value: Any
    rain_sensor_configured: bool
    rain_sensor_available: bool
    sun_above_horizon: bool
    wind_speed_kmh: float
    lux_value: float | None
    irradiance_value: float | None
    lux_entity: str | None = None
    irradiance_entity: str | None = None
    weather_entity: str | None = None
    rain_entity: str | None = None
    wind_entity: str | None = None
    night_purge_previous_active: bool = False
    inside_temperature_entity: str | None = None
    outside_temperature_entity: str | None = None

    @property
    def inside_temperature(self) -> float | None:
        """Zwróć temperaturę wewnętrzną ze snapshota."""
        return self.inside_temperature_value

    @property
    def outside_temperature(self) -> float | None:
        """Zwróć temperaturę zewnętrzną ze snapshota."""
        return self.outside_temperature_value

    @property
    def max_forecast_temp(self) -> float | None:
        """Zwróć prognozę lub bieżącą temperaturę zewnętrzną."""
        return (
            self.forecast_temperature
            if self.forecast_temperature is not None
            else self.outside_temperature
        )

    @property
    def get_current_temperature(self) -> float | None:
        """Zwróć temperaturę sterującą wybraną w konfiguracji."""
        if self.inside_temperature_entity:
            return self.inside_temperature
        if self.temp_switch:
            return self.outside_temperature
        return None

    @property
    def temperature_source(self) -> str:
        """Opisz źródło temperatury używanej przez automatykę."""
        if self.inside_temperature_entity:
            return (
                "inside"
                if self.inside_temperature is not None
                else "inside_unavailable"
            )
        if self.temp_switch and self.outside_temperature is not None:
            return "outside"
        return "unavailable"

    @property
    def is_presence(self) -> bool:
        """Zwróć znormalizowany stan obecności."""
        return self.presence

    @property
    def is_raining(self) -> bool:
        """Rozstrzygnij deszcz bez ponownego odczytu encji."""
        rainy = False
        if self.rain_sensor_configured and self.rain_sensor_available:
            normalized = str(self.rain_value).lower()
            rainy = normalized in {"on", "true", "detected", "1"}
            rain_rate = _as_float(self.rain_value)
            rainy = rainy or (rain_rate is not None and rain_rate > 0)
        elif self.weather_state:
            rainy = self.weather_state in {
                "rainy",
                "pouring",
                "lightning-rainy",
                "hail",
                "snowy",
                "snowy-rainy",
            }
        return rainy and not (self.rain_night_only and self.sun_above_horizon)

    @property
    def current_wind_speed(self) -> float:
        """Zwróć prędkość wiatru przeliczoną wcześniej do km/h."""
        return self.wind_speed_kmh

    @property
    def is_winter(self) -> bool:
        """Sprawdź dolny próg temperatury."""
        current = self.get_current_temperature
        result = bool(
            self.temp_low is not None
            and current is not None
            and current < self.temp_low
        )
        self.logger.debug(
            "is_winter(): current_temperature < temp_low: %s < %s = %s",
            current,
            self.temp_low,
            result,
        )
        return result

    @property
    def outside_high(self) -> bool:
        """Sprawdź, czy na zewnątrz przekroczono próg letni."""
        if self.temp_summer_outside is None or self.outside_temperature is None:
            return True
        return self.outside_temperature > self.temp_summer_outside

    @property
    def is_summer(self) -> bool:
        """Rozpoznaj potrzebę ochrony przed przegrzaniem."""
        current = self.get_current_temperature
        if self.temp_high is None or current is None:
            return False
        already_hot = current > self.temp_high
        forecast = self.max_forecast_temp
        predictive = bool(
            forecast is not None
            and self.temp_summer_outside is not None
            and forecast > self.temp_summer_outside + 2.0
        )
        radiation = self._radiation_wm2()
        threshold = self._radiation_threshold()
        high_radiation = bool(
            already_hot
            and self.direct_sun_valid
            and threshold is not None
            and radiation > threshold
        )
        return (already_hot and self.outside_high) or predictive or high_radiation

    def _radiation_wm2(self) -> float:
        """Znormalizuj irradiancję lub luks do przybliżonego W/m²."""
        if self.use_irradiance and self.irradiance_value is not None:
            return max(0.0, self.irradiance_value)
        if self.use_lux and self.lux_value is not None:
            return max(0.0, self.lux_value * 0.0079)
        return 0.0

    def _radiation_threshold(self) -> float | None:
        """Zwróć próg w jednostce W/m²."""
        if self.use_irradiance:
            return self.irradiance_threshold
        if self.use_lux and self.lux_threshold is not None:
            return self.lux_threshold * 0.0079
        return None

    def _predicted_temperature(self, radiation: float) -> float:
        """Oszacuj temperaturę pomieszczenia za godzinę."""
        current = self.get_current_temperature
        if current is None or self.outside_temperature is None:
            return current or 0.0
        delta = current - self.outside_temperature
        return current + 0.002 * radiation - 0.1 * delta

    def _comfort_bounds(self, radiation: float) -> tuple[float, float]:
        """Skoryguj strefę komfortu o słońce i prognozę."""
        comfort = float(self.temp_high)
        start = comfort - 2.0
        threshold = self._radiation_threshold()
        if self.direct_sun_valid and threshold is not None and radiation > threshold:
            start -= 1.0
            comfort -= 1.0
        forecast = self.max_forecast_temp
        if (
            forecast is not None
            and self.temp_summer_outside is not None
            and forecast > self.temp_summer_outside + 2.0
        ):
            start -= 1.0
            comfort -= 1.0
        return start, comfort

    @property
    def cooling_advantage(self) -> bool:
        """Sprawdź, czy chłód zewnętrzny zwalnia ochronę przed przegrzaniem."""
        current = self.get_current_temperature
        return bool(
            current is not None
            and self.outside_temperature is not None
            and self.outside_temperature
            <= current - self.thermal_hold_release_delta
        )

    @property
    def thermal_stress(self) -> float:
        """Oblicz stres termiczny w przedziale od 0 do 1."""
        current = self.get_current_temperature
        if self.temp_high is None or current is None:
            return 0.0
        radiation = self._radiation_wm2()
        if self.cooling_advantage:
            return 0.0
        predicted = self._predicted_temperature(radiation)
        effective = max(current, predicted)
        start, comfort = self._comfort_bounds(radiation)
        if effective >= comfort:
            return 1.0
        if effective <= start:
            return 0.0
        return (effective - start) / (comfort - start)

    @property
    def is_sunny(self) -> bool:
        """Rozstrzygnij słoneczność ze wspólnego snapshota pogody."""
        if not self.weather_entity:
            return True
        if self.cloud_coverage is not None:
            if self.cloud_coverage > 65:
                return False
            if self.cloud_coverage < 35:
                return True
        if self.weather_condition is not None:
            return self.weather_state in self.weather_condition
        return True

    @property
    def lux(self) -> bool:
        """Sprawdź stabilny stan słabego światła."""
        if not self.use_lux:
            return False
        if self.lux_low_light_state is not None:
            return self.lux_low_light_state
        return bool(
            self.lux_value is not None
            and self.lux_threshold is not None
            and self.lux_value <= self.lux_threshold
        )

    @property
    def irradiance(self) -> bool:
        """Sprawdź stabilny stan niskiej irradiancji."""
        if not self.use_irradiance:
            return False
        if self.irradiance_low_light_state is not None:
            return self.irradiance_low_light_state
        return bool(
            self.irradiance_value is not None
            and self.irradiance_threshold is not None
            and self.irradiance_value <= self.irradiance_threshold
        )

    @property
    def low_light(self) -> bool:
        """Połącz dostępne sygnały braku skutecznego promieniowania."""
        return self.lux or self.irradiance or not self.is_sunny


@dataclass
class ClimateCoverState(NormalCoverState):
    """Buduj kandydatów i wybieraj wynik przez jeden arbiter."""

    climate_data: ClimateCoverData
    decision_trace: list[dict] = field(default_factory=list, init=False)
    candidates: list[DecisionResult] = field(default_factory=list, init=False)
    _evaluations: list[dict] = field(default_factory=list, init=False)

    def _evaluate(
        self,
        code: str,
        active: bool,
        target: int,
        reason: str,
        **inputs: Any,
    ) -> None:
        """Zapisz ocenę reguły i aktywnego kandydata."""
        self._evaluations.append(
            {
                "code": code,
                "priority": decision_priority(code),
                "active": bool(active),
                **inputs,
            }
        )
        if active:
            self.candidates.append(
                DecisionResult(
                    target_position=int(target),
                    code=code,
                    reason=reason,
                    priority=decision_priority(code),
                    inputs=inputs,
                )
            )

    def normal_type_cover(self) -> int:
        """Wyznacz pozycję komfortową dla rolet pionowych i markiz."""
        if self.climate_data.is_presence:
            return self.normal_with_presence()
        return self.normal_without_presence()

    def normal_with_presence(self) -> int:
        """Wyznacz pozycję komfortową przy obecności."""
        summer = self.climate_data.is_summer
        stress = self.climate_data.thermal_stress
        low_light = self.climate_data.low_light
        if low_light and stress <= 0.0:
            if self.climate_data.is_winter and self.cover.valid:
                self.cover.state_reason = (
                    "Tryb zimowy: pełne odsłonięcie dla zysku słonecznego."
                )
                return 100
            self.cover.state_reason = "Brak silnego słońca: pozycja domyślna."
            return int(self.cover.default)
        if self.climate_data.cooling_advantage:
            self.cover.state_reason = (
                "Chłodne powietrze zewnętrzne: pozycja domyślna."
            )
            return int(self.cover.default)
        if summer and self.climate_data.transparent_blind:
            self.cover.state_reason = "Tryb letni: pełna blokada transparentnej rolety."
            return 0
        if stress > 0.0 and self.cover.valid:
            target = int(super().get_state() * (1.0 - stress))
            self.cover.state_reason = (
                f"Ochrona termiczna {int(stress * 100)}%, pozycja {target}%."
            )
            return target
        self.cover.state_reason = "Adaptacja do bieżącej pozycji słońca."
        return int(super().get_state())

    def normal_without_presence(self) -> int:
        """Wyznacz pozycję komfortową bez obecności."""
        if self.cover.valid:
            stress = self.climate_data.thermal_stress
            if stress > 0.0:
                target = int(self.cover.default * (1.0 - stress))
                self.cover.state_reason = (
                    f"Brak obecności, ochrona termiczna {int(stress * 100)}%."
                )
                return target
            if self.climate_data.is_winter:
                self.cover.state_reason = "Brak obecności: zimowy zysk słoneczny."
                return 100
        self.cover.state_reason = "Brak obecności: pozycja domyślna."
        return int(self.cover.default)

    def tilt_with_presence(self, degrees: int) -> int:
        """Wyznacz pochylenie lamel przy obecności."""
        low_light = (
            self.climate_data.lux
            or self.climate_data.irradiance
            or not self.climate_data.is_sunny
        )
        if self.cover.valid and low_light:
            if self.climate_data.is_summer or self.climate_data.thermal_stress > 0.5:
                self.cover.state_reason = "Tryb letni: lamele pod kątem 45 stopni."
                return int(45 / degrees * 100)
            self.cover.state_reason = "Pochylenie lamel zależne od słońca."
            return int(super().get_state())
        self.cover.state_reason = "Lamele otwarte do 80 stopni."
        return int(80 / degrees * 100)

    def tilt_without_presence(self, degrees: int) -> int:
        """Wyznacz pochylenie lamel bez obecności."""
        beta = np.rad2deg(self.cover.beta)
        if self.cover.valid:
            stress = self.climate_data.thermal_stress
            if self.climate_data.is_summer or stress > 0.0:
                effective = max(stress, 1.0 if self.climate_data.is_summer else 0.0)
                self.cover.state_reason = "Brak obecności: termiczne domknięcie lamel."
                return int((80 / degrees * 100) * (1.0 - effective))
            if self.climate_data.is_winter and self.cover.mode == "mode2":
                self.cover.state_reason = "Zimowe ustawienie równoległe do promieni."
                return int((beta + 90) / degrees * 100)
            self.cover.state_reason = "Domyślne otwarcie lamel do 80 stopni."
            return int(80 / degrees * 100)
        self.cover.state_reason = "Lamele oczekują na aktywne słońce."
        return int(super().get_state())

    def tilt_state(self) -> int:
        """Wyznacz stan dla pojedynczej osi pochylenia."""
        degrees = 180 if self.cover.mode == "mode2" else 90
        if self.climate_data.is_presence:
            return self.tilt_with_presence(degrees)
        return self.tilt_without_presence(degrees)

    def _night_purge_active(self) -> bool:
        """Sprawdź wszystkie warunki nocnego przewietrzania."""
        data = self.climate_data
        if not data.night_purge_enabled or data.sunset is None:
            return False
        try:
            purge_end = time.fromisoformat(data.night_purge_end_time)
        except (TypeError, ValueError):
            purge_end = time(7, 0)
        period = is_night_purge_window_active(data.now, data.sunset, purge_end)
        if (
            not period
            or data.inside_temperature is None
            or data.outside_temperature is None
            or data.temp_low is None
        ):
            return False
        # Rozdziel progi startu i zatrzymania, aby szum czujników nie budził domowników.
        inside_margin = 0.0 if data.night_purge_previous_active else 0.5
        cooling_margin = 0.2 if data.night_purge_previous_active else 1.0
        return (
            data.inside_temperature > data.temp_low + inside_margin
            and data.outside_temperature < data.inside_temperature - cooling_margin
        )

    def _dawn_active(self, night_purge: bool) -> bool:
        """Sprawdź okno ochrony przed świtem."""
        data = self.climate_data
        if (
            night_purge
            or data.sunrise is None
            or not data.dawn_start_month <= data.now.month <= data.dawn_end_month
        ):
            return False
        now_utc = data.now.astimezone(UTC)
        sunrise_utc = data.sunrise.astimezone(UTC)
        seconds = (sunrise_utc - now_utc).total_seconds()
        return 0 < seconds < data.dawn_duration_min * 60

    def _strict_sun(self, night_purge: bool) -> tuple[bool, dict[str, Any]]:
        """Sprawdź mocne słońce wyłącznie z dostępnego źródła."""
        data = self.climate_data
        enabled = (
            data.strict_sun_block_toggle
            and not night_purge
            and data.dawn_start_month <= data.now.month <= data.dawn_end_month
            and self.cover.direct_sun_valid
            and not data.is_raining
            and not data.cooling_advantage
        )
        source = "weather"
        value = data.weather_state
        threshold = None
        signal = data.is_sunny
        if data.use_irradiance and data.irradiance_entity:
            source = "irradiance"
            value = data.irradiance_value
            threshold = data.irradiance_threshold_on or data.irradiance_threshold
            signal = numeric_value_above_threshold(value, threshold)
            if value is not None and data.irradiance_low_light_state is not None:
                signal = not data.irradiance_low_light_state
        elif data.use_lux and data.lux_entity:
            source = "lux"
            value = data.lux_value
            threshold = data.lux_threshold_on or data.lux_threshold
            signal = numeric_value_above_threshold(value, threshold)
            if value is not None and data.lux_low_light_state is not None:
                signal = not data.lux_low_light_state
        return bool(enabled and signal), {
            "source": source,
            "sensor_value": value,
            "threshold": threshold,
            "sensor_available": value is not None,
            "hysteresis_low_light_state": (
                data.irradiance_low_light_state
                if source == "irradiance"
                else data.lux_low_light_state if source == "lux" else None
            ),
            "cooling_advantage": data.cooling_advantage,
        }

    def _thermal_hold_active(self) -> bool:
        """Sprawdź utrzymanie ochrony po ustaniu bezpośredniego słońca."""
        data = self.climate_data
        last_sun = data.last_direct_sun_at
        if last_sun is not None and last_sun.tzinfo is None:
            last_sun = last_sun.replace(tzinfo=UTC)
        return should_hold_thermal_protection(
            now=data.now.astimezone(UTC),
            last_direct_sun_at=(
                last_sun.astimezone(UTC) if last_sun is not None else None
            ),
            duration_minutes=data.thermal_hold_duration,
            direct_sun_valid=self.cover.direct_sun_valid,
            inside_temperature=data.inside_temperature,
            outside_temperature=data.outside_temperature,
            release_delta=data.thermal_hold_release_delta,
            thermal_stress=data.thermal_stress,
        )

    def _evaluate_safety(self, night_purge: bool) -> None:
        """Utwórz kandydatów ochrony pogodowej i temperaturowej."""
        data = self.climate_data
        self._evaluate(
            "rain_detected",
            data.is_raining,
            data.rain_position,
            f"Ochrona pogodowa: deszcz, pozycja {data.rain_position}%.",
            rain_value=data.rain_value,
        )
        self._evaluate(
            "wind_detected",
            data.current_wind_speed > data.wind_threshold,
            data.wind_position,
            f"Ochrona pogodowa: wiatr, pozycja {data.wind_position}%.",
            wind_speed=data.current_wind_speed,
            threshold=data.wind_threshold,
        )
        self._evaluate(
            "cold_protection",
            data.cold_protection_active,
            0,
            "Ochrona przed zimnem: noc i niska temperatura zewnętrzna.",
            outside_temperature=data.outside_temperature,
            activation_threshold=data.cold_threshold,
            release_threshold=data.cold_threshold + data.cold_hysteresis,
        )
        self._evaluate(
            "night_purge",
            night_purge,
            data.purge_pos,
            f"Nocne przewietrzanie: pozycja {data.purge_pos}%.",
            end_time=data.night_purge_end_time,
            previous_active=data.night_purge_previous_active,
            inside_temperature=data.inside_temperature,
            outside_temperature=data.outside_temperature,
            start_inside_margin=0.5,
            start_cooling_delta=1.0,
            stop_cooling_delta=0.2,
        )

    def _evaluate_sun_rules(self, night_purge: bool) -> None:
        """Utwórz kandydatów ochrony przed świtem i silnym słońcem."""
        data = self.climate_data
        dawn = self._dawn_active(night_purge)
        self._evaluate(
            "dawn_protection",
            dawn,
            0,
            "Ochrona przed świtem: blokada wczesnego słońca.",
            month=data.now.month,
            duration_minutes=data.dawn_duration_min,
        )
        strict, details = self._strict_sun(night_purge)
        self._evaluate(
            "strict_sun_block",
            strict,
            0,
            "Blokada słońca: silne bezpośrednie promieniowanie.",
            **details,
        )

    def _comfort_result(self) -> tuple[int, str, str]:
        """Wyznacz bazowego kandydata komfortowego."""
        target = (
            self.tilt_state()
            if self.climate_data.blind_type == "cover_tilt"
            else self.normal_type_cover()
        )
        if self.cover.direct_sun_valid:
            target = max(target, 1)
        code = "auto"
        if not self.cover.valid and self.cover.sunset_valid:
            code = "night_mode"
            target = int(self.cover.sunset_pos)
            self.cover.state_reason = "Tryb nocny: po zachodzie słońca."
        elif not self.cover.valid:
            code = "sun_shadow"
            target = int(self.cover.default)
            self.cover.state_reason = "Słońce poza zasięgiem okna."
        return int(target), code, self.cover.state_reason

    def _evaluate_comfort(self) -> None:
        """Utwórz kandydatów komfortu i Thermal Hold."""
        target, code, reason = self._comfort_result()
        self._evaluate(code, True, target, reason)
        thermal = (
            not self.cover.valid
            and not self.cover.sunset_valid
            and self.climate_data.thermal_hold_after_sun
            and self._thermal_hold_active()
        )
        self._evaluate(
            "thermal_hold",
            thermal,
            self.climate_data.thermal_hold_position,
            "Utrzymanie ochrony termicznej po bezpośrednim słońcu.",
            last_direct_sun_at=self.climate_data.last_direct_sun_at,
            duration_minutes=self.climate_data.thermal_hold_duration,
            release_delta=self.climate_data.thermal_hold_release_delta,
        )

    def get_decision(self) -> DecisionResult:
        """Oceń wszystkie reguły i wybierz najwyższy aktywny priorytet."""
        self.candidates.clear()
        self._evaluations.clear()
        night_purge = self._night_purge_active()
        self._evaluate_safety(night_purge)
        self._evaluate_sun_rules(night_purge)
        self._evaluate_comfort()

        selected = DecisionArbiter.select(self.candidates)
        self.decision_trace = DecisionArbiter.build_trace(
            self._evaluations,
            selected,
        )
        self.cover.state_info = selected.code
        self.cover.state_reason = selected.reason
        return selected

    def get_state(self) -> int:
        """Zwróć pozycję wybraną przez arbiter."""
        return self.get_decision().target_position
