"""Testy regresyjne struktury koordynatora niewymagające instalacji Home Assistant."""

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
COORDINATOR_PATH = ROOT / "custom_components" / "adaptive_cover" / "coordinator.py"
INIT_PATH = ROOT / "custom_components" / "adaptive_cover" / "__init__.py"
SWITCH_PATH = ROOT / "custom_components" / "adaptive_cover" / "switch.py"
CLIMATE_PATH = ROOT / "custom_components" / "adaptive_cover" / "climate.py"
MANUAL_CONTROL_PATH = (
    ROOT / "custom_components" / "adaptive_cover" / "manual_control.py"
)
COORDINATOR_DATA_PATH = (
    ROOT / "custom_components" / "adaptive_cover" / "coordinator_data.py"
)
COORDINATOR_EVENTS_PATH = (
    ROOT / "custom_components" / "adaptive_cover" / "coordinator_events.py"
)
COORDINATOR_EXECUTION_PATH = (
    ROOT / "custom_components" / "adaptive_cover" / "coordinator_execution.py"
)
COORDINATOR_PIPELINE_PATH = (
    ROOT / "custom_components" / "adaptive_cover" / "coordinator_pipeline.py"
)
SCHEDULE_PATH = ROOT / "custom_components" / "adaptive_cover" / "schedule.py"
NUMBER_PATH = ROOT / "custom_components" / "adaptive_cover" / "number.py"


def function_named(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Return one named function from a parsed module."""
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == name
    )


class SunsetOffsetEntityTests(unittest.TestCase):
    """Pilnuj dostępności suwaka przesunięcia zachodu dla istniejących wpisów."""

    def test_offset_entity_is_always_loaded(self) -> None:
        """Nie pozostawiaj encji jako niedostępnej przy ustawionym end_time."""
        setup = function_named(
            ast.parse(NUMBER_PATH.read_text(encoding="utf-8")),
            "async_setup_entry",
        )
        add_calls = [
            node
            for node in ast.walk(setup)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func) == "async_add_entities"
        ]

        self.assertEqual(1, len(add_calls))
        self.assertFalse(any(isinstance(node, ast.If) for node in ast.walk(setup)))


class NightPurgeDeadlineTests(unittest.TestCase):
    """Pilnuj świeżej decyzji przy końcu nocnego wietrzenia."""

    @classmethod
    def setUpClass(cls) -> None:
        """Wczytaj strukturę kodu bez importowania zależności Home Assistant."""
        cls.events_tree = ast.parse(COORDINATOR_EVENTS_PATH.read_text(encoding="utf-8"))
        cls.execution_tree = ast.parse(
            COORDINATOR_EXECUTION_PATH.read_text(encoding="utf-8")
        )
        cls.pipeline_tree = ast.parse(
            COORDINATOR_PIPELINE_PATH.read_text(encoding="utf-8")
        )
        cls.schedule_tree = ast.parse(SCHEDULE_PATH.read_text(encoding="utf-8"))
        cls.callback = function_named(
            cls.events_tree,
            "async_close_after_night_purge",
        )

    def test_deadline_never_sends_a_position_directly(self) -> None:
        """Nie pozwalaj timerowi omijać aktualnej decyzji bezpieczeństwa."""
        calls = [
            node
            for node in ast.walk(self.callback)
            if isinstance(node, ast.Call) and "set_position" in ast.unparse(node.func)
        ]

        self.assertEqual([], calls)

    def test_deadline_requests_fresh_arbitration(self) -> None:
        """Oznacz przyczynę i wykonaj pełne odświeżenie koordynatora."""
        calls = {
            ast.unparse(node.func)
            for node in ast.walk(self.callback)
            if isinstance(node, ast.Call)
        }
        callback_source = ast.unparse(self.callback)

        self.assertIn("self._pending_refreshes.add", calls)
        self.assertIn("await self.async_refresh()", callback_source)
        self.assertIn("RefreshTrigger.NIGHT_PURGE_DEADLINE", callback_source)

    def test_first_refresh_catches_up_missed_deadline(self) -> None:
        """Użyj świeżego celu także po restarcie wykonanym po terminie."""
        handler = function_named(
            self.execution_tree,
            "async_handle_first_refresh",
        )
        calls = {
            ast.unparse(node.func)
            for node in ast.walk(handler)
            if isinstance(node, ast.Call)
        }
        self.assertIn("self._night_purge_close_overdue", calls)
        self.assertIn("self.async_handle_timed_refresh", calls)


class CoordinatorExecutionTests(unittest.TestCase):
    """Guard coordinator execution ordering and gating rules."""

    @classmethod
    def setUpClass(cls) -> None:
        """Parse runtime modules without importing Home Assistant."""
        cls.source = COORDINATOR_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.init_tree = ast.parse(INIT_PATH.read_text(encoding="utf-8"))
        cls.switch_tree = ast.parse(SWITCH_PATH.read_text(encoding="utf-8"))
        cls.data_tree = ast.parse(COORDINATOR_DATA_PATH.read_text(encoding="utf-8"))
        cls.events_tree = ast.parse(COORDINATOR_EVENTS_PATH.read_text(encoding="utf-8"))
        cls.execution_tree = ast.parse(
            COORDINATOR_EXECUTION_PATH.read_text(encoding="utf-8")
        )
        cls.pipeline_tree = ast.parse(
            COORDINATOR_PIPELINE_PATH.read_text(encoding="utf-8")
        )
        cls.schedule_tree = ast.parse(SCHEDULE_PATH.read_text(encoding="utf-8"))
        cls.climate_tree = ast.parse(CLIMATE_PATH.read_text(encoding="utf-8"))
        cls.manual_control_tree = ast.parse(
            MANUAL_CONTROL_PATH.read_text(encoding="utf-8")
        )

    def test_restore_entities_before_first_automation_pass(self) -> None:
        """Do not consume first refresh before RestoreEntity switches are loaded."""
        setup = function_named(self.init_tree, "async_setup_entry")
        calls = [
            (ast.unparse(node.func), node.lineno)
            for node in ast.walk(setup)
            if isinstance(node, ast.Call)
        ]
        forward_line = next(
            line for name, line in calls if name.endswith("async_forward_entry_setups")
        )
        initialized_line = next(
            line
            for name, line in calls
            if name.endswith("schedule_runtime_initialization")
        )
        self.assertLess(forward_line, initialized_line)

    def test_started_helper_cannot_miss_runtime_initialization(self) -> None:
        """Use the HA helper that handles both startup and integration reload."""
        setup = ast.unparse(function_named(self.init_tree, "async_setup_entry"))
        self.assertIn("async_at_started", setup)
        self.assertNotIn("async_listen_once", setup)

    def test_startup_events_cannot_issue_physical_movement(self) -> None:
        """Calculate during startup but execute handlers only after stabilization."""
        update = ast.unparse(
            function_named(self.pipeline_tree, "_execute_pending_events")
        )
        service = ast.unparse(
            function_named(self.execution_tree, "async_handle_call_service")
        )
        self.assertIn("self._runtime_initialized", update)
        self.assertIn("if not self._runtime_initialized", service)
        self.assertIn("runtime_initializing", service)

    def test_strict_sun_requires_numeric_sensor_value(self) -> None:
        """Do not interpret unavailable irradiance as strong sunlight."""
        climate_state = next(
            node
            for node in ast.walk(self.climate_tree)
            if isinstance(node, ast.ClassDef) and node.name == "ClimateCoverState"
        )
        body = ast.unparse(climate_state)
        self.assertIn("numeric_value_above_threshold", body)
        self.assertIn("sensor_value", body)

    def test_intermediate_cover_states_return_before_refresh(self) -> None:
        """Ensure ignored motor states cannot trigger manual-override processing."""
        handler = function_named(
            self.events_tree,
            "async_check_cover_state_change",
        )
        ignored_if = next(
            node
            for node in handler.body
            if isinstance(node, ast.If)
            and "ignore_intermediate_states" in ast.unparse(node.test)
        )
        self.assertTrue(any(isinstance(node, ast.Return) for node in ignored_if.body))

    def test_emergency_decisions_bypass_generic_limits(self) -> None:
        """Keep rain and wind movement independent from cooldown and manual mode."""
        handler = function_named(self.execution_tree, "movement_block_reason")
        body = ast.unparse(handler)
        self.assertIn("EMERGENCY_DECISION_CODES", body)
        self.assertIn("SCHEDULE_EXEMPT_DECISION_CODES", body)
        self.assertIn("not emergency and self.manager.is_cover_manual", body)
        self.assertIn("not emergency and (not self.manager.can_move", body)

    def test_timed_refresh_preserves_physical_position_limits(self) -> None:
        """Koniec harmonogramu nie może ominąć min/max ustawionych dla napędu."""
        handler = ast.unparse(function_named(self.pipeline_tree, "_finalize_decision"))
        self.assertIn("DecisionArbiter.constrain_position", handler)

    def test_manual_override_uses_absolute_deadline(self) -> None:
        """Prevent a shrinking relative duration from resetting at half-time."""
        manager_source = MANUAL_CONTROL_PATH.read_text(encoding="utf-8")
        self.assertIn("manual_control_until", manager_source)
        reset = ast.unparse(function_named(self.manual_control_tree, "reset_if_needed"))
        self.assertIn("current_time >= deadline", reset)

    def test_zero_is_valid_interpolation_endpoint(self) -> None:
        """Allow the normal 0-100 mapping to start at zero."""
        interpolation = ast.unparse(
            function_named(self.data_tree, "interpolate_states")
        )
        self.assertIn("self.start_value is not None", interpolation)

    def test_universal_schedule_uses_universal_option(self) -> None:
        """Use start_time when no Workday entity is configured."""
        resolver = ast.unparse(
            function_named(self.schedule_tree, "_configured_start_source")
        )
        self.assertIn("explicit_start_time", resolver)
        self.assertIn("{'on', 'off'}", resolver)

    def test_control_switch_uses_shared_movement_gates(self) -> None:
        """Do not reintroduce schedule or manual gates before safety decisions."""
        turn_on = ast.unparse(function_named(self.switch_tree, "async_turn_on"))
        self.assertIn("async_handle_call_service", turn_on)
        self.assertNotIn("adaptive_movement_allowed", turn_on)
        self.assertNotIn("is_cover_manual", turn_on)


if __name__ == "__main__":
    unittest.main()
