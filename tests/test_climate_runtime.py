"""Behawioralne testy czystego arbitra klimatycznego."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).parents[1] / "custom_components" / "adaptive_cover"
PACKAGE = "adaptive_cover_climate_test"

package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package


def load_module(name: str, filename: str):
    """Wczytaj moduł w izolowanym pakiecie testowym."""
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


decision = load_module("decision", "decision.py")
geometry = ModuleType(f"{PACKAGE}.geometry")


@dataclass
class NormalCoverState:
    """Minimalna baza zwracająca geometryczny cel snapshota."""

    cover: object

    def get_state(self) -> int:
        """Zwróć ustawiony wynik geometrii."""
        return self.cover.base_state


geometry.NormalCoverState = NormalCoverState
sys.modules[geometry.__name__] = geometry
try:
    import numpy as np  # noqa: F401
except ImportError:
    np = ModuleType("numpy")
    np.rad2deg = lambda value: value
    sys.modules["numpy"] = np
climate = load_module("climate", "climate.py")


class FakeCover:
    """Czysty snapshot geometrii wymagany przez silnik klimatu."""

    def __init__(
        self,
        *,
        valid: bool = True,
        sunset_valid: bool = False,
        direct_sun_valid: bool = True,
        default: int = 80,
    ) -> None:
        """Ustaw sterowalne warunki testu."""
        self.valid = valid
        self.sunset_valid = sunset_valid
        self.direct_sun_valid = direct_sun_valid
        self.default = default
        self.sunset_pos = 0
        self.base_state = 60
        self.min_pos = 0
        self.max_pos = 100
        self.apply_min_position = False
        self.apply_max_position = False
        self.mode = "mode1"
        self.beta = 0.0
        self.logger = Mock()
        self.state_reason = "Adaptacja."
        self.state_info = "auto"


def climate_data(**changes):
    """Zbuduj kompletny snapshot z bezpiecznymi wartościami."""
    values = {
        "logger": Mock(),
        "now": datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        "sunrise": datetime(2026, 7, 29, 4, 45, tzinfo=UTC),
        "sunset": datetime(2026, 7, 29, 19, 45, tzinfo=UTC),
        "temp_low": 20.0,
        "temp_high": 24.0,
        "temp_switch": True,
        "blind_type": "cover_blind",
        "transparent_blind": False,
        "weather_condition": ["sunny"],
        "temp_summer_outside": 24.0,
        "use_lux": False,
        "use_irradiance": True,
        "lux_threshold": 1000.0,
        "irradiance_threshold": 300.0,
        "lux_threshold_on": 1200.0,
        "lux_threshold_off": 800.0,
        "irradiance_threshold_on": 350.0,
        "irradiance_threshold_off": 250.0,
        "lux_low_light_state": None,
        "irradiance_low_light_state": False,
        "rain_night_only": False,
        "rain_position": 5,
        "wind_position": 10,
        "dawn_start_month": 5,
        "dawn_end_month": 10,
        "dawn_duration_min": 60,
        "cold_threshold": 16.0,
        "cold_hysteresis": 1.0,
        "cold_protection_active": False,
        "wind_threshold": 40.0,
        "purge_pos": 15,
        "strict_sun_block_toggle": True,
        "forecast_temperature": 24.0,
        "thermal_hold_after_sun": True,
        "thermal_hold_position": 30,
        "thermal_hold_duration": 120,
        "thermal_hold_release_delta": 1.0,
        "direct_sun_valid": True,
        "last_direct_sun_at": datetime(2026, 7, 29, 11, 30, tzinfo=UTC),
        "night_purge_enabled": True,
        "night_purge_end_time": "07:00:00",
        "inside_temperature_value": 25.0,
        "outside_temperature_value": 25.0,
        "inside_temperature_entity": "sensor.room_temperature",
        "outside_temperature_entity": "sensor.outside_temperature",
        "presence": True,
        "weather_state": "sunny",
        "cloud_coverage": 10.0,
        "rain_value": 0.0,
        "rain_sensor_configured": True,
        "rain_sensor_available": True,
        "sun_above_horizon": True,
        "wind_speed_kmh": 0.0,
        "lux_value": None,
        "irradiance_value": 500.0,
        "irradiance_entity": "sensor.sun",
        "weather_entity": "weather.home",
        "rain_entity": "sensor.rain",
    }
    values.update(changes)
    return climate.ClimateCoverData(**values)


class ClimateArbiterTests(unittest.TestCase):
    """Sprawdzaj wynik pełnej oceny kandydatów."""

    def test_rain_wins_over_wind_and_strict_sun(self) -> None:
        """Deszcz zachowuje pierwszy awaryjny priorytet przy remisie z wiatrem."""
        data = climate_data(rain_value=1.0, wind_speed_kmh=80.0)
        result = climate.ClimateCoverState(FakeCover(), data).get_decision()

        self.assertEqual("rain_detected", result.code)
        self.assertEqual(5, result.target_position)

    def test_wind_wins_over_strict_sun(self) -> None:
        """Wiatr nie może zostać nadpisany komfortową blokadą słońca."""
        data = climate_data(wind_speed_kmh=80.0)
        result = climate.ClimateCoverState(FakeCover(), data).get_decision()

        self.assertEqual("wind_detected", result.code)

    def test_unavailable_irradiance_disables_strict_sun(self) -> None:
        """Brak liczby nie może oznaczać mocnego słońca."""
        data = climate_data(
            irradiance_value=None,
            irradiance_low_light_state=None,
            inside_temperature_value=22.0,
            outside_temperature_value=19.0,
            forecast_temperature=19.0,
        )
        result = climate.ClimateCoverState(FakeCover(), data).get_decision()

        self.assertNotEqual("strict_sun_block", result.code)

    def test_unavailable_weather_light_and_temperature_are_safe(self) -> None:
        """Brak wszystkich opcjonalnych wejść nie aktywuje ochrony pozornie."""
        data = climate_data(
            inside_temperature_value=None,
            outside_temperature_value=None,
            forecast_temperature=None,
            weather_state=None,
            cloud_coverage=None,
            rain_value=None,
            rain_sensor_available=False,
            lux_value=None,
            irradiance_value=None,
            lux_low_light_state=None,
            irradiance_low_light_state=None,
        )
        result = climate.ClimateCoverState(FakeCover(), data).get_decision()

        self.assertNotIn(
            result.code,
            {
                "rain_detected",
                "cold_protection",
                "strict_sun_block",
                "thermal_hold",
            },
        )
        self.assertEqual(0.0, data.thermal_stress)

    def test_unavailable_configured_inside_sensor_is_not_replaced_by_outside(
        self,
    ) -> None:
        """Brak czujnika pokoju nie może udawać temperatury zewnętrznej."""
        data = climate_data(
            temp_high=22.0,
            temp_summer_outside=20.0,
            inside_temperature_entity="sensor.room_temperature",
            inside_temperature_value=None,
            outside_temperature_value=24.2,
            forecast_temperature=27.1,
            irradiance_value=146.82,
            irradiance_low_light_state=True,
        )

        result = climate.ClimateCoverState(FakeCover(default=100), data).get_decision()

        self.assertIsNone(data.get_current_temperature)
        self.assertEqual("inside_unavailable", data.temperature_source)
        self.assertEqual(0.0, data.thermal_stress)
        self.assertEqual(100, result.target_position)

    def test_outside_temperature_remains_fallback_without_inside_sensor(self) -> None:
        """Tryb bez czujnika pokojowego nadal może używać temperatury zewnętrznej."""
        data = climate_data(
            inside_temperature_entity=None,
            inside_temperature_value=None,
            outside_temperature_value=24.2,
            temp_switch=True,
        )

        self.assertEqual(24.2, data.get_current_temperature)
        self.assertEqual("outside", data.temperature_source)


class ClimateAndTemperatureStabilityTests(unittest.TestCase):
    """Sprawdzaj stabilizację wejścia i pozostałe reguły klimatyczne."""

    def test_short_cold_spike_keeps_last_stable_temperature(self) -> None:
        """Sekwencja 19,7 -> 7,1 -> 19,7 nie może uruchomić ochrony zimna."""
        temperature_filter = climate.TemperatureStabilityFilter()
        start = datetime(2026, 8, 2, 23, 50, tzinfo=UTC)

        self.assertEqual(
            19.7,
            temperature_filter.update(19.7, now=start, reference_value=20.0),
        )
        self.assertEqual(
            19.7,
            temperature_filter.update(
                7.1,
                now=start.replace(minute=51),
                reference_value=19.8,
            ),
        )
        self.assertEqual(
            19.7,
            temperature_filter.update(
                19.7,
                now=start.replace(minute=51, second=30),
                reference_value=19.8,
            ),
        )
        self.assertEqual(1, temperature_filter.rejected_count)
        self.assertIsNone(temperature_filter.candidate_value)

    def test_persistent_step_is_accepted_after_confirmation(self) -> None:
        """Rzeczywista duża zmiana zostaje przyjęta po pięciu minutach."""
        temperature_filter = climate.TemperatureStabilityFilter()
        start = datetime(2026, 8, 2, 23, 50, tzinfo=UTC)
        temperature_filter.update(19.7, now=start, reference_value=20.0)
        temperature_filter.update(
            7.1,
            now=start.replace(minute=51),
            reference_value=19.8,
        )

        accepted = temperature_filter.update(
            6.9,
            now=start.replace(minute=56),
            reference_value=19.7,
        )

        self.assertEqual(6.9, accepted)
        self.assertEqual("confirmed_step", temperature_filter.accepted_source)

    def test_weather_reference_protects_first_outlier_after_restart(self) -> None:
        """Pierwszy błędny odczyt po starcie nie może zamknąć rolet."""
        temperature_filter = climate.TemperatureStabilityFilter()
        now = datetime(2026, 8, 3, 1, 14, 59, tzinfo=UTC)

        accepted = temperature_filter.update(
            6.5,
            now=now,
            reference_value=19.4,
        )

        self.assertEqual(19.4, accepted)
        self.assertEqual("weather_reference", temperature_filter.accepted_source)
        self.assertEqual(6.5, temperature_filter.candidate_value)

    def test_night_mode_uses_configured_sunset_position(self) -> None:
        """Po zachodzie nie pozostawiaj dziennego celu pod etykietą trybu nocnego."""
        cover = FakeCover(
            valid=False,
            sunset_valid=True,
            direct_sun_valid=False,
            default=100,
        )
        data = climate_data(
            night_purge_enabled=False,
            irradiance_low_light_state=True,
        )

        result = climate.ClimateCoverState(cover, data).get_decision()

        self.assertEqual("night_mode", result.code)
        self.assertEqual(0, result.target_position)

    def test_cooler_outside_and_low_radiation_has_zero_stress(self) -> None:
        """Chłodne powietrze bez silnego słońca nie uzasadnia zamykania."""
        data = climate_data(
            inside_temperature_value=25.0,
            outside_temperature_value=19.0,
            forecast_temperature=19.0,
            irradiance_value=100.0,
        )

        self.assertEqual(0.0, data.thermal_stress)

    def test_cooling_advantage_releases_thermal_stress_despite_direct_sun(self) -> None:
        """Chłodne powietrze ma zwolnić zwykłą ochronę także przy słońcu."""
        data = climate_data(
            temp_high=22.0,
            inside_temperature_value=21.57,
            outside_temperature_value=12.0,
            forecast_temperature=12.0,
            irradiance_value=338.21,
            irradiance_low_light_state=False,
            strict_sun_block_toggle=False,
        )

        self.assertEqual(0.0, data.thermal_stress)

    def test_cooling_advantage_releases_strict_sun_to_default_position(self) -> None:
        """Chłodne powietrze ma odblokować też ścisłą blokadę słońca."""
        cover = FakeCover(default=100)
        cover.base_state = 0
        data = climate_data(
            temp_high=22.0,
            inside_temperature_value=21.51,
            outside_temperature_value=13.3,
            forecast_temperature=13.3,
            irradiance_value=373.97,
            irradiance_low_light_state=False,
        )

        result = climate.ClimateCoverState(cover, data).get_decision()

        self.assertEqual("auto", result.code)
        self.assertEqual(100, result.target_position)
        self.assertEqual(0.0, data.thermal_stress)

    def test_export_conditions_open_present_room_to_default_position(self) -> None:
        """Prognoza upału nie nadpisuje aktualnego braku promieniowania."""
        cover = FakeCover(default=100)
        cover.base_state = 70
        data = climate_data(
            temp_high=22.0,
            temp_summer_outside=20.0,
            inside_temperature_value=26.2,
            outside_temperature_value=18.9,
            forecast_temperature=27.2,
            irradiance_value=44.96,
            irradiance_low_light_state=True,
            presence=True,
        )

        result = climate.ClimateCoverState(cover, data).get_decision()

        self.assertTrue(data.is_summer)
        self.assertEqual(0.0, data.thermal_stress)
        self.assertEqual(100, result.target_position)
        self.assertEqual("Brak silnego słońca: pozycja domyślna.", result.reason)

    def test_export_conditions_open_empty_room_to_default_position(self) -> None:
        """Brak obecności nie może zamknąć rolety wyłącznie przez prognozę."""
        cover = FakeCover(default=100)
        cover.base_state = 22
        data = climate_data(
            temp_high=22.0,
            temp_summer_outside=20.0,
            inside_temperature_value=25.71,
            outside_temperature_value=18.9,
            forecast_temperature=27.2,
            irradiance_value=44.96,
            irradiance_low_light_state=True,
            presence=False,
        )

        result = climate.ClimateCoverState(cover, data).get_decision()

        self.assertEqual(0.0, data.thermal_stress)
        self.assertEqual(100, result.target_position)

    def test_low_light_does_not_release_positive_thermal_stress(self) -> None:
        """Słabe światło nie otwiera rolety, gdy gorące powietrze nadal grzeje."""
        cover = FakeCover(default=100)
        data = climate_data(
            temp_high=22.0,
            temp_summer_outside=20.0,
            inside_temperature_value=26.0,
            outside_temperature_value=30.0,
            forecast_temperature=32.0,
            irradiance_value=44.96,
            irradiance_low_light_state=True,
            presence=True,
        )

        result = climate.ClimateCoverState(cover, data).get_decision()

        self.assertGreater(data.thermal_stress, 0.0)
        self.assertLess(result.target_position, 100)

    def test_same_snapshot_is_deterministic(self) -> None:
        """Dwukrotna ocena tych samych wejść daje identyczny wynik i ślad."""
        data = climate_data()
        first = climate.ClimateCoverState(FakeCover(), data)
        second = climate.ClimateCoverState(FakeCover(), data)

        self.assertEqual(first.get_decision(), second.get_decision())
        self.assertEqual(first.decision_trace, second.decision_trace)

    def test_position_limit_is_constraint_not_competing_rule(self) -> None:
        """Limit zachowuje kod decyzji bezpieczeństwa i zmienia tylko cel."""
        original = decision.DecisionResult(5, "rain_detected", "Deszcz", 100)
        constrained, details = decision.DecisionArbiter.constrain_position(
            original,
            minimum=20,
            maximum=100,
            apply_minimum=True,
            apply_maximum=False,
        )

        self.assertEqual("rain_detected", constrained.code)
        self.assertEqual(20, constrained.target_position)
        self.assertEqual("min_limit", details["code"])


if __name__ == "__main__":
    unittest.main()
