"""Wykonywanie, weryfikacja i ponawianie ruchów Adaptive Cover."""

from __future__ import annotations

import asyncio
import datetime as dt
from copy import deepcopy
from math import isfinite
from typing import Protocol

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
)
from homeassistant.exceptions import HomeAssistantError

from .const import ATTR_POSITION, ATTR_TILT_POSITION
from .decision import EMERGENCY_DECISION_CODES, position_requires_move
from .models import MovementOutcome, MovementResult

COMMAND_ORIGIN_GRACE = dt.timedelta(minutes=2)


class MovementContext(Protocol):
    """Kontrakt koordynatora wymagany przez wykonawcę ruchów."""

    hass: object
    manager: object
    logger: object
    _cover_type: str
    _unloading: bool
    min_change: int | float
    global_cooldown: int | float
    max_moves_per_hour: int
    max_moves_per_day: int
    time_threshold: int | float
    control_toggle: bool
    dry_run_toggle: bool
    is_window_open: bool
    window_open_action: str
    window_open_position: int
    state: int

    def _create_background_task(self, target, name: str): ...

    def _decision_code(self) -> str: ...

    def _get_current_position(self, entity: str) -> int | None: ...

    def _target_for_entity(self, entity: str, state: int) -> int: ...


class CoverMovementExecutor:
    """Jedyne miejsce wysyłające fizyczne polecenia do osłon."""

    def __init__(self, context: MovementContext) -> None:
        """Zainicjalizuj wykonawcę z dynamicznym kontekstem koordynatora."""
        self.context = context
        self.wait_for_target: dict[str, bool] = {}
        self.target_call: dict[str, int] = {}
        self.verify_tasks: dict[str, asyncio.Task] = {}
        self.verify_task_metadata: dict[str, dict] = {}
        self.command_generation: dict[str, int] = {}
        self.last_command_at: dict[str, dt.datetime] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._command_contexts: dict[str, dict] = {}

    def cancel(self) -> None:
        """Anuluj wszystkie zadania weryfikacyjne podczas unload."""
        for task in self.verify_tasks.values():
            if not task.done():
                task.cancel()
        self.verify_tasks.clear()
        self.wait_for_target.clear()

    def is_waiting(self, entity: str) -> bool:
        """Zwróć, czy napęd powinien jeszcze osiągnąć wysłany cel."""
        return self.wait_for_target.get(entity, False)

    def target_for(self, entity: str) -> int | None:
        """Zwróć ostatni cel wysłany do wskazanej osłony."""
        return self.target_call.get(entity)

    def observe_position_event(
        self,
        entity: str,
        *,
        position: int | float | None,
        movement_state: str,
        tolerance: int | float,
    ) -> bool:
        """Rozpoznaj zdarzenie będące skutkiem polecenia automatyki."""
        target = self.target_for(entity)
        if target is None or position is None:
            return self.is_waiting(entity)

        target_reached = not position_requires_move(position, target, tolerance)
        command_at = self.last_command_at.get(entity)
        command_is_recent = bool(
            command_at is not None
            and dt.datetime.now(dt.UTC) - command_at <= COMMAND_ORIGIN_GRACE
        )

        if self.is_waiting(entity):
            if target_reached:
                self._complete_from_event(entity)
                return True
            if command_is_recent:
                return True
            if movement_state not in {"open", "closed", "ok", "stopped"}:
                return True
            self.wait_for_target[entity] = False
            return False

        cancelled_in_motion = (
            self.verify_task_metadata.get(entity, {}).get("outcome")
            == "retry_conditions_changed"
        )
        return bool(command_is_recent and (target_reached or cancelled_in_motion))

    def _complete_from_event(self, entity: str) -> None:
        """Zakończ weryfikację od razu po potwierdzeniu napędu."""
        self._cancel_previous_verification(entity)
        self._finish_verification(
            entity, self.command_generation.get(entity, 0), "target_verified_by_event"
        )

    def reconcile(self, entity: str, target: int) -> None:
        """Anuluj stare retry również wtedy, gdy nowy ruch blokują limity."""
        if entity not in self.verify_tasks:
            return
        owner = self.context
        if (
            not owner.control_toggle
            or self.target_for(entity) != target
            or owner.manager.is_cover_manual(entity)
            or (
                owner.is_window_open
                and owner.window_open_action in {"pause", "return_after_close"}
            )
        ):
            self._cancel_previous_verification(entity)
            self._finish_verification(
                entity,
                self.command_generation.get(entity, 0),
                "retry_conditions_changed",
            )

    def update_metadata(
        self,
        entity: str,
        *,
        expected_generation: int | None = None,
        **changes,
    ) -> None:
        """Aktualizuj ograniczony snapshot zadania retry."""
        metadata = self.verify_task_metadata.setdefault(entity, {})
        if (
            expected_generation is not None
            and metadata.get("generation") != expected_generation
        ):
            return
        metadata.update(changes)
        metadata["updated_at"] = dt.datetime.now(dt.UTC)

    async def async_set_position(
        self,
        entity: str,
        state: int,
        *,
        enforce_current_target: bool = True,
    ) -> MovementResult:
        """Wyślij polecenie i zaplanuj jego weryfikację."""
        async with self._locks.setdefault(entity, asyncio.Lock()):
            return await self._async_set_position(
                entity, state, enforce_current_target=enforce_current_target
            )

    async def _async_set_position(
        self, entity: str, state: int, *, enforce_current_target: bool
    ) -> MovementResult:
        """Wykonaj polecenie po zakończeniu wcześniejszego wywołania usługi."""
        owner = self.context
        decision = getattr(owner, "last_decision", None)
        if enforce_current_target and decision is not None:
            if owner._target_for_entity(entity, decision.target_position) != state:
                return MovementResult(
                    entity, state, MovementOutcome.SKIPPED, "superseded_target"
                )
        blocked = self._preflight(entity, state)
        if blocked is not None:
            return blocked
        service, service_data = self._service_payload(entity, state)
        generation = self._begin_command(entity, state, service, service_data)
        if self.context.dry_run_toggle:
            return self._dry_run_result(
                entity,
                state,
                service,
                service_data,
                generation,
            )
        self._cancel_previous_verification(entity)
        failed = await self._send_initial_command(
            entity,
            state,
            service,
            service_data,
            generation,
        )
        if failed is not None:
            return failed
        return self._schedule_verification(
            entity,
            state,
            service,
            service_data,
            generation,
            enforce_current_target,
        )

    def _preflight(self, entity: str, state: int) -> MovementResult | None:
        """Zablokuj polecenie przed utworzeniem generacji wykonawczej."""
        owner = self.context
        if owner._unloading:
            return MovementResult(
                entity,
                state,
                MovementOutcome.BLOCKED,
                "integration_unloading",
            )
        if not owner.control_toggle:
            return MovementResult(
                entity, state, MovementOutcome.BLOCKED, "control_disabled"
            )
        if self.is_waiting(entity) and self.target_for(entity) == state:
            owner.manager.set_status(
                entity, "waiting_for_target", "command_already_pending"
            )
            return MovementResult(
                entity, state, MovementOutcome.SKIPPED, "command_already_pending"
            )
        current = owner._get_current_position(entity)
        if current is not None and not isfinite(float(current)):
            current = None
        if owner.is_window_open:
            action = owner.window_open_action
            if action in {"pause", "return_after_close"} or (
                action == "block_closing_only"
                and current is not None
                and state < current
            ):
                owner.manager.set_status(entity, "blocked", "window_open")
                return MovementResult(
                    entity, state, MovementOutcome.BLOCKED, "window_open"
                )
        if current is not None and position_requires_move(
            current,
            state,
            owner.min_change,
        ):
            return None
        self.wait_for_target[entity] = False
        self.target_call[entity] = state
        reason = (
            "position_unavailable" if current is None else "target_within_tolerance"
        )
        status = "blocked" if current is None else "auto"
        outcome = (
            MovementOutcome.BLOCKED if current is None else MovementOutcome.SKIPPED
        )
        owner.manager.set_status(entity, status, reason)
        return MovementResult(entity, state, outcome, reason)

    def _begin_command(
        self,
        entity: str,
        state: int,
        service: str,
        service_data: dict,
    ) -> int:
        """Utwórz nową generację polecenia."""
        generation = self.command_generation.get(entity, 0) + 1
        self.command_generation[entity] = generation
        self.wait_for_target[entity] = True
        self.target_call[entity] = state
        self.last_command_at[entity] = dt.datetime.now(dt.UTC)
        decision = getattr(self.context, "last_decision", None)
        climate = getattr(self.context, "last_climate_data", None)
        self._command_contexts[entity] = deepcopy(
            {
                "decision": decision.as_dict()
                if decision is not None
                else {"code": self.context._decision_code()},
                "decision_trace": getattr(self.context, "last_decision_trace", []),
                "refresh_generation": getattr(
                    self.context, "_active_refresh_generation", None
                ),
                "refresh_triggers": sorted(
                    getattr(self.context, "_active_refresh_triggers", [])
                ),
                "current_position": self.context._get_current_position(entity),
                "final_target": state,
                "position_bias": getattr(
                    getattr(self.context, "learner", None), "position_biases", {}
                ).get(entity, 0),
                "inside_temperature": climate.inside_temperature if climate else None,
                "outside_temperature": climate.outside_temperature if climate else None,
                "irradiance": climate.irradiance_value if climate else None,
                "wind_speed_kmh": climate.current_wind_speed if climate else None,
                "rain_value": climate.rain_value if climate else None,
                "command_generation": generation,
            }
        )
        self.context.logger.debug("Run %s with data %s", service, service_data)
        return generation

    def _dry_run_result(
        self,
        entity: str,
        state: int,
        service: str,
        service_data: dict,
        generation: int,
    ) -> MovementResult:
        """Zapisz symulowane polecenie bez zadania retry."""
        self.wait_for_target[entity] = False
        self.last_command_at.pop(entity, None)
        self.context.manager.record_move(
            entity,
            service,
            service_data,
            dry_run=True,
            command_context=self._command_contexts[entity] | {"kind": "dry_run"},
        )
        self.context.manager.set_status(entity, "dry_run", f"would_set_{state}")
        self.update_metadata(
            entity,
            generation=generation,
            target=state,
            state="dry_run",
            outcome="not_executed",
        )
        return MovementResult(
            entity,
            state,
            MovementOutcome.DRY_RUN,
            "not_executed",
            generation,
        )

    def _cancel_previous_verification(self, entity: str) -> None:
        """Anuluj retry zastąpione nowszym poleceniem."""
        task = self.verify_tasks.pop(entity, None)
        if task is None:
            return
        task.cancel()
        self.update_metadata(
            entity,
            state="cancelled",
            outcome="replaced_by_new_command",
        )

    async def _send_initial_command(
        self,
        entity: str,
        state: int,
        service: str,
        service_data: dict,
        generation: int,
    ) -> MovementResult | None:
        """Wyślij pierwsze polecenie i jawnie obsłuż błąd usługi."""
        try:
            await self._async_send_service(service, service_data)
        except HomeAssistantError as err:
            self.wait_for_target[entity] = False
            self.last_command_at.pop(entity, None)
            self.context.manager.last_service_error[entity] = str(err)
            self.context.manager.set_status(entity, "blocked", "service_call_failed")
            self.update_metadata(
                entity,
                generation=generation,
                target=state,
                state="failed",
                outcome="service_call_failed",
                error=str(err),
            )
            self.context.logger.error("Unable to move %s: %s", entity, err)
            return MovementResult(
                entity,
                state,
                MovementOutcome.FAILED,
                "service_call_failed",
                generation,
            )
        self.context.manager.record_move(
            entity,
            service,
            service_data,
            command_context=self._command_contexts[entity] | {"kind": "initial"},
        )
        self.context.manager.set_status(entity, "waiting_for_target", f"target_{state}")
        return None

    def _schedule_verification(
        self,
        entity: str,
        state: int,
        service: str,
        service_data: dict,
        generation: int,
        enforce_current_target: bool,
    ) -> MovementResult:
        """Utwórz metadane i zadanie kontroli osiągnięcia celu."""
        wait_time = self._verification_wait_time()
        self.verify_task_metadata[entity] = self._verification_metadata(
            entity,
            state,
            service,
            service_data,
            generation,
            enforce_current_target,
            wait_time,
        )
        self.verify_tasks[entity] = self.context._create_background_task(
            self.async_verify_and_retry(
                entity,
                state,
                service,
                service_data,
                generation=generation,
                enforce_current_target=enforce_current_target,
                wait_time=wait_time,
                max_retries=2,
            ),
            f"adaptive_cover verify target for {entity}",
        )
        return MovementResult(
            entity,
            state,
            MovementOutcome.EXECUTED,
            "command_sent",
            generation,
        )

    def _verification_wait_time(self) -> int:
        """Oddziel czas pracy napędu od limitów częstotliwości poleceń."""
        return 45

    def _verification_metadata(
        self,
        entity: str,
        state: int,
        service: str,
        service_data: dict,
        generation: int,
        enforce_current_target: bool,
        wait_time: int,
    ) -> dict:
        """Zbuduj ograniczony snapshot jednego zadania retry."""
        now = dt.datetime.now(dt.UTC)
        return {
            "created_at": now,
            "updated_at": now,
            "generation": generation,
            "target": state,
            "service": service,
            "service_data": dict(service_data),
            "state": "scheduled",
            "outcome": None,
            "attempt": 0,
            "max_retries": 2,
            "wait_seconds": wait_time,
            "next_check_at": now + dt.timedelta(seconds=wait_time),
            "last_observed_position": self.context._get_current_position(entity),
            "enforce_current_target": enforce_current_target,
        }

    async def async_verify_and_retry(
        self,
        entity: str,
        target_state: int,
        service: str,
        service_data: dict,
        *,
        generation: int,
        enforce_current_target: bool = True,
        wait_time: int = 45,
        max_retries: int = 2,
    ) -> None:
        """Sprawdź osiągnięcie celu i ponów aktualne polecenie."""
        try:
            for attempt in range(1, max_retries + 2):
                await self._wait_before_verification(
                    entity,
                    generation,
                    attempt,
                    wait_time,
                )
                async with self._locks.setdefault(entity, asyncio.Lock()):
                    outcome = self._verification_stop_reason(
                        entity,
                        target_state,
                        generation,
                        enforce_current_target,
                    )
                    if outcome is not None:
                        self._finish_verification(entity, generation, outcome)
                        return
                    if attempt > max_retries:
                        self._finish_verification(
                            entity, generation, "target_not_reached"
                        )
                        return
                    if not await self._send_retry(
                        entity,
                        service,
                        service_data,
                        generation,
                        attempt,
                    ):
                        return
        except asyncio.CancelledError:
            if self.verify_tasks.get(entity) is asyncio.current_task():
                self.update_metadata(
                    entity,
                    expected_generation=generation,
                    state="cancelled",
                    outcome="task_cancelled",
                )
            raise
        finally:
            if self.verify_tasks.get(entity) is asyncio.current_task():
                self.verify_tasks.pop(entity, None)

    async def _wait_before_verification(
        self,
        entity: str,
        generation: int,
        attempt: int,
        wait_time: int,
    ) -> None:
        """Zapisz termin i odczekaj przed kolejną kontrolą."""
        self.update_metadata(
            entity,
            expected_generation=generation,
            state="waiting",
            attempt=attempt,
            next_check_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=wait_time),
        )
        await asyncio.sleep(wait_time)

    def _verification_stop_reason(
        self,
        entity: str,
        target_state: int,
        generation: int,
        enforce_current_target: bool,
    ) -> str | None:
        """Zwróć powód zakończenia retry albo zezwól na ponowienie."""
        owner = self.context
        if self.retry_is_stale(
            entity,
            target_state,
            generation,
            enforce_current_target,
        ):
            owner.manager.set_status(entity, "skipped", "retry_conditions_changed")
            return "retry_conditions_changed"
        if not self.is_waiting(entity):
            owner.manager.set_status(entity, "auto", "target_verified")
            return "target_verified_by_event"

        current = owner._get_current_position(entity)
        self.update_metadata(
            entity,
            expected_generation=generation,
            last_observed_position=current,
        )
        if current is not None and not position_requires_move(
            current,
            target_state,
            owner.min_change,
        ):
            owner.manager.set_status(entity, "auto", "target_verified")
            return "target_within_tolerance"
        return self._movement_limit_reason(entity)

    def _movement_limit_reason(self, entity: str) -> str | None:
        """Sprawdź limity ponowienia z wyjątkiem decyzji awaryjnej."""
        owner = self.context
        if owner._decision_code() in EMERGENCY_DECISION_CODES:
            return None
        history = getattr(owner.manager, "movement_history", {}).get(entity, [])
        if history and dt.datetime.now(dt.UTC) - max(history) < dt.timedelta(
            minutes=float(owner.time_threshold)
        ):
            owner.manager.set_status(entity, "blocked", "time_delta_not_passed")
            return "time_delta_not_passed"
        if owner.manager.can_move(
            entity,
            owner.global_cooldown,
            owner.max_moves_per_hour,
            owner.max_moves_per_day,
        ):
            return None
        return owner.manager.last_skip_reason.get(entity, "movement_limit")

    async def _send_retry(
        self,
        entity: str,
        service: str,
        service_data: dict,
        generation: int,
        attempt: int,
    ) -> bool:
        """Wyślij jedno ponowienie i zapisz jego wynik."""
        owner = self.context
        owner.manager.set_status(entity, "retrying", f"retry_{attempt}")
        try:
            await self._async_send_service(service, service_data)
        except HomeAssistantError as err:
            owner.manager.last_service_error[entity] = str(err)
            owner.manager.set_status(entity, "blocked", "retry_service_failed")
            self.wait_for_target[entity] = False
            self.update_metadata(
                entity,
                expected_generation=generation,
                state="failed",
                outcome="retry_service_failed",
                error=str(err),
            )
            return False
        owner.manager.record_move(
            entity,
            service,
            service_data,
            command_context=self._command_contexts.get(entity, {})
            | {"kind": "retry", "attempt": attempt},
        )
        self.last_command_at[entity] = dt.datetime.now(dt.UTC)
        self.update_metadata(
            entity,
            expected_generation=generation,
            state="retry_sent",
            outcome=None,
        )
        return True

    def _finish_verification(
        self,
        entity: str,
        generation: int,
        outcome: str,
    ) -> None:
        """Zamknij oczekiwanie i zachowaj ostateczny wynik."""
        if self.command_generation.get(entity, 0) != generation:
            return
        self.wait_for_target[entity] = False
        if outcome == "target_not_reached":
            self.context.manager.set_status(entity, "blocked", outcome)
        self.update_metadata(
            entity,
            expected_generation=generation,
            state="finished",
            outcome=outcome,
        )

    def retry_is_stale(
        self,
        entity: str,
        target_state: int,
        generation: int,
        enforce_current_target: bool,
    ) -> bool:
        """Sprawdź, czy opóźnione retry nadal odpowiada aktualnym warunkom."""
        owner = self.context
        if (
            owner._unloading
            or not owner.control_toggle
            or self.command_generation.get(entity) != generation
            or owner.manager.is_cover_manual(entity)
        ):
            return True
        decision = getattr(owner, "last_decision", None)
        current_target = (
            decision.target_position if decision is not None else owner.state
        )
        if (
            enforce_current_target or decision is not None
        ) and owner._target_for_entity(entity, current_target) != target_state:
            return True
        if owner.is_window_open:
            current = owner._get_current_position(entity)
            action = owner.window_open_action
            if action in {"pause", "return_after_close"}:
                return True
            if action == "move_to_position":
                return target_state != owner._target_for_entity(
                    entity, int(owner.window_open_position)
                )
            if (
                action == "block_closing_only"
                and current is not None
                and target_state < current
            ):
                return True
        return False

    def _service_payload(self, entity: str, state: int) -> tuple[str, dict]:
        """Zbuduj nazwę usługi i dane dla rodzaju osłony."""
        service_data = {ATTR_ENTITY_ID: entity}
        if self.context._cover_type == "cover_tilt":
            service_data[ATTR_TILT_POSITION] = state
            return SERVICE_SET_COVER_TILT_POSITION, service_data
        service_data[ATTR_POSITION] = state
        return SERVICE_SET_COVER_POSITION, service_data

    async def _async_send_service(self, service: str, service_data: dict) -> None:
        """Wyślij jedno fizyczne polecenie do Home Assistant."""
        await self.context.hass.services.async_call(
            COVER_DOMAIN,
            service,
            service_data,
            blocking=True,
        )
