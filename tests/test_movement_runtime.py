"""Testy wykonawcy ruchów bez uruchamiania Home Assistant."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock

from fakes import FakeServices, FakeState, FakeStateChange

ROOT = Path(__file__).parents[1]
PACKAGE_PATH = ROOT / "custom_components" / "adaptive_cover"
PACKAGE_NAME = "adaptive_cover_movement_test"

try:
    import homeassistant.components.cover  # noqa: F401
    import homeassistant.const  # noqa: F401
    import homeassistant.exceptions as homeassistant_exceptions
except ImportError:
    homeassistant_cover = ModuleType("homeassistant.components.cover")
    homeassistant_cover.DOMAIN = "cover"
    homeassistant_const = ModuleType("homeassistant.const")
    homeassistant_const.ATTR_ENTITY_ID = "entity_id"
    homeassistant_const.SERVICE_SET_COVER_POSITION = "set_cover_position"
    homeassistant_const.SERVICE_SET_COVER_TILT_POSITION = "set_cover_tilt_position"
    homeassistant_exceptions = ModuleType("homeassistant.exceptions")
    homeassistant_exceptions.HomeAssistantError = type(
        "HomeAssistantError",
        (Exception,),
        {},
    )

    sys.modules.setdefault(
        "homeassistant.components",
        ModuleType("homeassistant.components"),
    )
    sys.modules["homeassistant.components.cover"] = homeassistant_cover
    sys.modules["homeassistant.const"] = homeassistant_const
    sys.modules["homeassistant.exceptions"] = homeassistant_exceptions

package = ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_PATH)]
sys.modules[PACKAGE_NAME] = package


def load_module(name: str, filename: str):
    """Wczytaj moduł z działającymi importami względnymi."""
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{name}",
        PACKAGE_PATH / filename,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load_module("const", "const.py")
load_module("decision", "decision.py")
models = load_module("models", "models.py")
movement = load_module("movement", "movement.py")
manual_control = load_module("manual_control", "manual_control.py")


class FakeManager:
    """Minimalna polityka limitów i statusów dla wykonawcy."""

    def __init__(self) -> None:
        """Zainicjalizuj rejestry diagnostyczne."""
        self.last_service_error = {}
        self.last_skip_reason = {}
        self.statuses = []
        self.moves = []
        self.manual = False
        self.allow_move = True

    def set_status(self, entity, status, reason) -> None:
        """Zapisz ostatni status."""
        self.statuses.append((entity, status, reason))

    def record_move(
        self, entity, service, data, *, dry_run=False, command_context=None
    ) -> None:
        """Zapisz polecenie uwzględniane przez limity."""
        self.moves.append((entity, service, dict(data), dry_run))

    def is_cover_manual(self, _entity) -> bool:
        """Zwróć stan ręcznego przejęcia."""
        return self.manual

    def can_move(self, *_args) -> bool:
        """Zwróć wynik polityki limitów."""
        return self.allow_move


class FakeContext:
    """Kontekst wykonawcy odpowiadający kontraktowi koordynatora."""

    def __init__(self) -> None:
        """Ustaw bezpieczne wartości domyślne."""
        self.hass = SimpleNamespace(services=FakeServices())
        self.manager = FakeManager()
        self.logger = Mock()
        self._cover_type = "cover_blind"
        self._unloading = False
        self.min_change = 1
        self.global_cooldown = 0
        self.max_moves_per_hour = 8
        self.max_moves_per_day = 40
        self.time_threshold = 0
        self.control_toggle = True
        self.dry_run_toggle = False
        self.is_window_open = False
        self.window_open_action = "pause"
        self.window_open_position = 100
        self.state = 40
        self.current_position = 20
        self.target = 40
        self.tasks = []
        self.decision_code = "auto"

    def _create_background_task(self, target, _name):
        """Utwórz zadanie, które test może anulować."""
        task = asyncio.create_task(target)
        self.tasks.append(task)
        return task

    def _decision_code(self):
        """Zwróć aktualny kod decyzji."""
        return self.decision_code

    def _get_current_position(self, _entity):
        """Zwróć symulowaną pozycję napędu."""
        return self.current_position

    def _target_for_entity(self, _entity, _state):
        """Zwróć finalny cel po korekcie BehavioralLearner."""
        return self.target


class MovementRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """Sprawdzaj wykonanie, błędy i aktualność retry."""

    async def asyncTearDown(self) -> None:
        """Pozwól pętli zakończyć anulowane zadania."""
        await asyncio.sleep(0)

    async def test_initial_command_uses_single_cover_service_gateway(self) -> None:
        """Ruch ma przejść przez rejestr usług dokładnie raz."""
        context = FakeContext()
        executor = movement.CoverMovementExecutor(context)

        result = await executor.async_set_position("cover.room", 45)
        executor.cancel()

        self.assertEqual(models.MovementOutcome.EXECUTED, result.outcome)
        self.assertEqual(1, len(context.hass.services.calls))
        self.assertEqual(45, context.hass.services.calls[0][2]["position"])

    async def test_service_error_returns_explicit_failed_result(self) -> None:
        """Błąd HA nie może wyglądać jak wykonany ruch."""
        context = FakeContext()
        context.hass.services.error = homeassistant_exceptions.HomeAssistantError(
            "offline"
        )
        executor = movement.CoverMovementExecutor(context)

        result = await executor.async_set_position("cover.room", 45)

        self.assertEqual(models.MovementOutcome.FAILED, result.outcome)
        self.assertFalse(result)
        self.assertEqual("service_call_failed", result.reason)

    async def test_retry_compares_learned_final_target(self) -> None:
        """Cel 45% z biasem nie może być uznany za nieaktualny wobec bazy 40%."""
        context = FakeContext()
        context.target = 45
        executor = movement.CoverMovementExecutor(context)
        executor.command_generation["cover.room"] = 3

        stale = executor.retry_is_stale("cover.room", 45, 3, True)

        self.assertFalse(stale)

    async def test_emergency_retry_bypasses_generic_limits(self) -> None:
        """Retry deszczu ma zostać wysłane mimo wyczerpanego limitu."""
        context = FakeContext()
        context.decision_code = "rain_detected"
        context.target = 0
        context.manager.allow_move = False
        executor = movement.CoverMovementExecutor(context)
        executor.command_generation["cover.room"] = 1
        executor.wait_for_target["cover.room"] = True

        original_sleep = movement.asyncio.sleep

        async def no_wait(_seconds):
            return None

        movement.asyncio.sleep = no_wait
        try:
            await executor.async_verify_and_retry(
                "cover.room",
                0,
                "set_cover_position",
                {"entity_id": "cover.room", "position": 0},
                generation=1,
                wait_time=45,
                max_retries=1,
            )
        finally:
            movement.asyncio.sleep = original_sleep

        self.assertEqual(1, len(context.hass.services.calls))

    def test_only_movement_module_calls_cover_domain_service(self) -> None:
        """Pilnuj jednej fizycznej bramki usług osłon w repozytorium."""
        call_sites = []
        for path in (ROOT / "custom_components" / "adaptive_cover").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "hass.services.async_call(" in source and "COVER_DOMAIN" in source:
                call_sites.append(path.name)

        self.assertEqual(["movement.py"], call_sites)


class ManualControlRuntimeTests(unittest.TestCase):
    """Sprawdzaj potwierdzenie ruchu użytkownika przed uczeniem."""

    def setUp(self) -> None:
        """Utwórz zarządcę jednej rolety i atrapę BehavioralLearner."""
        self.learner = Mock()
        self.manager = manual_control.AdaptiveCoverManager(
            {"minutes": 15},
            Mock(),
            self.learner,
        )
        self.manager.add_covers(["cover.room"])
        self.old_state = FakeState("open", {"current_position": 50})
        context = FakeContext()
        context.manager = self.manager
        self.movement = movement.CoverMovementExecutor(context)

    def test_intermediate_motor_state_is_not_learned(self) -> None:
        """Stan opening/closing nie potwierdza ręcznego zatrzymania."""
        self.movement.wait_for_target["cover.room"] = True
        self.movement.target_call["cover.room"] = 50
        event = FakeStateChange(
            "cover.room",
            self.old_state,
            FakeState("closing", {"current_position": 30}),
        )

        self.manager.handle_state_change(
            event,
            50,
            "cover_blind",
            True,
            self.movement,
            2,
        )

        self.assertTrue(self.movement.is_waiting("cover.room"))
        self.assertFalse(self.manager.is_cover_manual("cover.room"))
        self.learner.register_override.assert_not_called()

    def test_stable_intermediate_report_after_own_command_is_not_learned(self) -> None:
        """Napęd może raportować open także podczas trwającego ruchu."""
        self.movement.wait_for_target["cover.room"] = True
        self.movement.target_call["cover.room"] = 50
        self.movement.last_command_at["cover.room"] = dt.datetime.now(dt.UTC)
        event = FakeStateChange(
            "cover.room",
            self.old_state,
            FakeState("open", {"current_position": 30}),
        )

        self.manager.handle_state_change(
            event,
            50,
            "cover_blind",
            True,
            self.movement,
            2,
            current_temp=23.0,
            is_summer=True,
        )

        self.assertTrue(self.movement.is_waiting("cover.room"))
        self.assertFalse(self.manager.is_cover_manual("cover.room"))
        self.learner.register_override.assert_not_called()

    def test_stable_position_after_command_grace_can_be_manual(self) -> None:
        """Po upływie ochrony stabilny postój poza celem oznacza ingerencję."""
        self.movement.wait_for_target["cover.room"] = True
        self.movement.target_call["cover.room"] = 50
        self.movement.last_command_at["cover.room"] = (
            dt.datetime.now(dt.UTC)
            - movement.COMMAND_ORIGIN_GRACE
            - dt.timedelta(seconds=1)
        )
        event = FakeStateChange(
            "cover.room",
            self.old_state,
            FakeState("open", {"current_position": 30}),
        )

        self.manager.handle_state_change(
            event,
            50,
            "cover_blind",
            True,
            self.movement,
            2,
            current_temp=23.0,
            is_summer=True,
        )

        self.assertFalse(self.movement.is_waiting("cover.room"))
        self.assertTrue(self.manager.is_cover_manual("cover.room"))
        self.learner.register_override.assert_called_once()

    def test_duplicate_final_report_uses_last_physical_target(self) -> None:
        """Późny raport celu nie może być porównany z nową kalkulacją."""
        self.movement.wait_for_target["cover.room"] = True
        self.movement.target_call["cover.room"] = 50
        self.movement.last_command_at["cover.room"] = dt.datetime.now(dt.UTC)
        final_state = FakeState("open", {"current_position": 50})

        self.manager.handle_state_change(
            FakeStateChange("cover.room", self.old_state, final_state),
            50,
            "cover_blind",
            True,
            self.movement,
            2,
        )
        self.manager.handle_state_change(
            FakeStateChange("cover.room", final_state, final_state),
            80,
            "cover_blind",
            True,
            self.movement,
            2,
        )

        self.assertFalse(self.movement.is_waiting("cover.room"))
        self.assertFalse(self.manager.is_cover_manual("cover.room"))
        self.learner.register_override.assert_not_called()


if __name__ == "__main__":
    unittest.main()
