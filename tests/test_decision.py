"""Tests for pure Adaptive Cover decisions."""

from datetime import UTC, datetime, time, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

MODULE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "adaptive_cover" / "decision.py"
)
SPEC = importlib.util.spec_from_file_location("adaptive_cover_decision", MODULE_PATH)
decision = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = decision
SPEC.loader.exec_module(decision)


class NightPurgeTests(unittest.TestCase):
    """Verify the hard night-purge deadline."""

    def test_window_ends_even_when_sunrise_is_later(self) -> None:
        """Stop purge exactly at the configured deadline before sunrise."""
        sunset = datetime(2026, 12, 1, 16, 0, tzinfo=UTC)
        self.assertTrue(
            decision.is_night_purge_window_active(
                datetime(2026, 12, 2, 5, 59, tzinfo=UTC),
                sunset,
                time(6, 0),
            )
        )
        self.assertFalse(
            decision.is_night_purge_window_active(
                datetime(2026, 12, 2, 6, 0, tzinfo=UTC),
                sunset,
                time(6, 0),
            )
        )

    def test_daytime_is_not_part_of_night_purge(self) -> None:
        """Exclude ordinary daytime before the next sunset."""
        now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
        sunset = datetime(2026, 7, 11, 20, 0, tzinfo=UTC)
        self.assertFalse(decision.is_night_purge_window_active(now, sunset, time(6, 0)))

    def test_daytime_deadline_before_sunset_does_not_activate_all_day(self) -> None:
        """Treat a deadline such as 18:00 as inactive before a later sunset."""
        now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
        sunset = datetime(2026, 7, 11, 20, 0, tzinfo=UTC)
        self.assertFalse(
            decision.is_night_purge_window_active(now, sunset, time(18, 0))
        )

    def test_same_evening_deadline_after_sunset_is_supported(self) -> None:
        """Allow a valid same-evening deadline later than sunset."""
        now = datetime(2026, 12, 1, 21, 0, tzinfo=UTC)
        sunset = datetime(2026, 12, 1, 16, 0, tzinfo=UTC)
        self.assertTrue(decision.is_night_purge_window_active(now, sunset, time(22, 0)))

    def test_utc_sunset_is_converted_to_local_time_before_purge(self) -> None:
        """Nie uruchamiaj przewietrzania dwie godziny za wcześnie latem."""
        warsaw = ZoneInfo("Europe/Warsaw")
        sunset_utc = datetime(2026, 8, 2, 18, 17, 35, tzinfo=UTC)

        self.assertFalse(
            decision.is_night_purge_window_active(
                datetime(2026, 8, 2, 20, 3, tzinfo=warsaw),
                sunset_utc,
                time(6, 0),
            )
        )
        self.assertTrue(
            decision.is_night_purge_window_active(
                datetime(2026, 8, 2, 20, 18, tzinfo=warsaw),
                sunset_utc,
                time(6, 0),
            )
        )


class ColdProtectionTests(unittest.TestCase):
    """Sprawdzaj stabilne przełączanie ochrony przed chłodem."""

    def test_protection_activates_below_configured_threshold(self) -> None:
        """Aktywuj ochronę dopiero po zejściu poniżej progu."""
        self.assertTrue(
            decision.resolve_cold_protection(
                outside_temperature=15.9,
                threshold=16.0,
                night_active=True,
                previous_active=False,
            )
        )

    def test_active_protection_uses_one_degree_release_hysteresis(self) -> None:
        """Nie przełączaj rolet przy drobnych wahaniach wokół 16°C."""
        self.assertTrue(
            decision.resolve_cold_protection(
                outside_temperature=16.4,
                threshold=16.0,
                night_active=True,
                previous_active=True,
            )
        )
        self.assertFalse(
            decision.resolve_cold_protection(
                outside_temperature=17.0,
                threshold=16.0,
                night_active=True,
                previous_active=True,
            )
        )

    def test_protection_is_released_outside_night(self) -> None:
        """Stan z poprzedniej nocy nie może przejść na dzień."""
        self.assertFalse(
            decision.resolve_cold_protection(
                outside_temperature=10.0,
                threshold=16.0,
                night_active=False,
                previous_active=True,
            )
        )


class ThermalHoldTests(unittest.TestCase):
    """Verify room-specific post-sun protection."""

    def test_cooler_outside_air_releases_hold(self) -> None:
        """Release shading when outdoor cooling has a clear advantage."""
        now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
        self.assertFalse(
            decision.should_hold_thermal_protection(
                now=now,
                last_direct_sun_at=now - timedelta(minutes=15),
                duration_minutes=120,
                direct_sun_valid=False,
                inside_temperature=22.5,
                outside_temperature=19.0,
                release_delta=1.0,
                thermal_stress=1.0,
            )
        )

    def test_hold_requires_previous_direct_sun(self) -> None:
        """Do not call ordinary shade a post-sun thermal hold."""
        self.assertFalse(
            decision.should_hold_thermal_protection(
                now=datetime(2026, 7, 11, 10, 0, tzinfo=UTC),
                last_direct_sun_at=None,
                duration_minutes=120,
                direct_sun_valid=False,
                inside_temperature=23.0,
                outside_temperature=23.0,
                release_delta=1.0,
                thermal_stress=1.0,
            )
        )

    def test_recent_sun_and_no_cooling_keeps_hold(self) -> None:
        """Retain recent protection while the room cannot cool effectively."""
        now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
        self.assertTrue(
            decision.should_hold_thermal_protection(
                now=now,
                last_direct_sun_at=now - timedelta(minutes=15),
                duration_minutes=120,
                direct_sun_valid=False,
                inside_temperature=23.0,
                outside_temperature=22.5,
                release_delta=1.0,
                thermal_stress=0.5,
            )
        )


class UnitConversionTests(unittest.TestCase):
    """Verify weather input normalization."""

    def test_wind_speed_is_normalized_to_kmh(self) -> None:
        """Convert meters per second before applying the km/h threshold."""
        self.assertAlmostEqual(36.0, decision.wind_speed_to_kmh(10.0, "m/s"))


class WindConfirmationTests(unittest.TestCase):
    """Sprawdź potwierdzanie przekroczenia progu przez raporty stacji."""

    def test_wind_requires_three_fresh_consecutive_reports(self) -> None:
        """Odrzuć pojedynczy poryw i nie doliczaj duplikatu raportu."""
        wind = decision.WindConfirmation(3, 40)
        now = datetime(2026, 11, 19, 9, 6, 32, tzinfo=UTC)

        self.assertFalse(wind.record(40.3, now))
        self.assertFalse(wind.record(27.7, now + timedelta(seconds=10)))
        self.assertEqual(0, wind.samples)
        next_report = now + timedelta(seconds=20)
        self.assertFalse(wind.record(42, next_report))
        self.assertFalse(wind.record(42, next_report))
        self.assertFalse(wind.record(42, now + timedelta(seconds=30)))
        self.assertEqual(2, wind.samples)
        self.assertTrue(wind.record(42, now + timedelta(seconds=40)))
        self.assertFalse(wind.record(None, now + timedelta(seconds=50)))
        self.assertEqual(3, wind.samples)
        self.assertTrue(wind.record(40, now + timedelta(minutes=1)))
        self.assertEqual(0, wind.samples)

    def test_startup_seed_accepts_only_calm_reading(self) -> None:
        """Spokojny stan przy starcie zwalnia otwieranie; silny wiatr czeka na raporty."""
        calm = decision.WindConfirmation(1, 40)
        calm.seed(12)
        self.assertFalse(calm.blocks_opening)
        storm = decision.WindConfirmation(1, 40)
        storm.seed(55)
        storm.seed(None)
        self.assertTrue(storm.blocks_opening)
        self.assertEqual(0, storm.samples)

    def test_gap_and_missing_data_break_a_pending_run(self) -> None:
        """Nie łącz odczytów rozdzielonych przerwą lub niedostępnością."""
        wind = decision.WindConfirmation(3, 40)
        now = datetime(2026, 11, 19, 9, 6, tzinfo=UTC)
        wind.record(42, now)
        wind.record(None, now + timedelta(seconds=10))
        self.assertEqual(0, wind.samples)
        wind.record(42, now + timedelta(seconds=20))
        self.assertEqual(0, wind.samples_at(now + timedelta(minutes=3)))
        wind.record(42, now + timedelta(minutes=3))
        self.assertEqual(1, wind.samples)


class PositionToleranceTests(unittest.TestCase):
    """Verify movement suppression for devices with imprecise end positions."""

    def test_reported_97_percent_satisfies_100_percent_target(self) -> None:
        """Do not retry a 100% target below the configured 10% movement delta."""
        self.assertFalse(decision.position_requires_move(97, 100, 10))

    def test_difference_equal_to_threshold_requires_movement(self) -> None:
        """Preserve movement when the position difference reaches the threshold."""
        self.assertTrue(decision.position_requires_move(90, 100, 10))

    def test_exact_position_never_requires_movement(self) -> None:
        """Avoid redundant calls even when the configured threshold is zero."""
        self.assertFalse(decision.position_requires_move(100, 100, 0))


class NumericSignalTests(unittest.TestCase):
    """Verify that missing sensor data never becomes a strong-sun signal."""

    def test_missing_irradiance_is_not_strong_sun(self) -> None:
        """Treat startup null values as unavailable, not above threshold."""
        self.assertFalse(decision.numeric_value_above_threshold(None, 300))
        self.assertFalse(decision.numeric_value_above_threshold("unavailable", 300))

    def test_irradiance_must_exceed_threshold(self) -> None:
        """Use the actual numeric reading for Strict Sun Block."""
        self.assertFalse(decision.numeric_value_above_threshold(145.78, 300))
        self.assertTrue(decision.numeric_value_above_threshold(413, 300))


class DecisionResultTests(unittest.TestCase):
    """Verify explainable decision metadata."""

    def test_safety_decision_has_higher_priority_than_comfort(self) -> None:
        """Keep safety rules above thermal comfort decisions."""
        self.assertGreater(
            decision.decision_priority("rain_detected"),
            decision.decision_priority("thermal_hold"),
        )

    def test_decision_is_serializable(self) -> None:
        """Expose complete decision data to diagnostics."""
        result = decision.DecisionResult(
            target_position=0,
            code="strict_sun_block",
            reason="sun",
            priority=decision.decision_priority("strict_sun_block"),
            inputs={"irradiance": 413.0},
        )
        self.assertEqual(413.0, result.as_dict()["inputs"]["irradiance"])

    def test_only_comfort_decisions_are_learnable(self) -> None:
        """Do not learn user preferences from rain or wind safety targets."""
        self.assertIn("thermal_hold", decision.LEARNABLE_DECISION_CODES)
        self.assertNotIn("rain_detected", decision.LEARNABLE_DECISION_CODES)
        # Brak słońca w oknie: domyślna pozycja bez korekty ze słonecznych poprawek.
        self.assertNotIn("sun_shadow", decision.LEARNABLE_DECISION_CODES)
        self.assertIn("rain_detected", decision.EMERGENCY_DECISION_CODES)

    def test_behavioral_learning_requires_active_adaptive_schedule(self) -> None:
        """Ruch przed startem harmonogramu nie może zmieniać preferencji."""
        self.assertFalse(
            decision.behavioral_learning_allowed(
                "auto",
                adaptive_movement_allowed=False,
            )
        )
        self.assertTrue(
            decision.behavioral_learning_allowed(
                "auto",
                adaptive_movement_allowed=True,
            )
        )
        self.assertFalse(
            decision.behavioral_learning_allowed(
                "rain_detected",
                adaptive_movement_allowed=True,
            )
        )

    def test_arbiter_selects_highest_priority_from_full_matrix(self) -> None:
        """Kolejność listy nie może zmienić jawnego priorytetu reguł."""
        codes = [
            "auto",
            "sun_shadow",
            "night_mode",
            "thermal_hold",
            "night_purge",
            "strict_sun_block",
            "dawn_protection",
            "cold_protection",
            "wind_detected",
            "window_open",
            "control_disabled",
        ]
        candidates = [
            decision.DecisionResult(
                target_position=index,
                code=code,
                reason=code,
                priority=decision.decision_priority(code),
            )
            for index, code in enumerate(codes)
        ]

        selected = decision.DecisionArbiter.select(candidates)

        self.assertEqual("control_disabled", selected.code)

    def test_window_policy_is_selected_by_same_arbiter(self) -> None:
        """Otwarte okno ma jawnie nadpisać decyzję komfortową i jej cel."""
        base = decision.DecisionResult(
            40,
            "auto",
            "Komfort",
            decision.decision_priority("auto"),
        )

        selected, trace = decision.apply_runtime_policies(
            base,
            control_enabled=True,
            window_open=True,
            window_action="move_to_position",
            window_position=100,
        )

        self.assertEqual("window_open", selected.code)
        self.assertEqual(100, selected.target_position)
        self.assertTrue(
            any(item["code"] == "window_open" and item["selected"] for item in trace)
        )

    def test_timed_end_is_between_safety_and_comfort(self) -> None:
        """Koniec harmonogramu zamyka komfort, ale nie nadpisuje ochrony."""
        self.assertGreater(
            decision.decision_priority("strict_sun_block"),
            decision.decision_priority("timed_end"),
        )
        self.assertGreater(
            decision.decision_priority("timed_end"),
            decision.decision_priority("thermal_hold"),
        )
        self.assertEqual(
            decision.decision_priority("timed_end"),
            decision.decision_priority("night_purge_end"),
        )


if __name__ == "__main__":
    unittest.main()
