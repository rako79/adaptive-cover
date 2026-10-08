"""Polityki wykonawcze łączące decyzję z bramką ruchu."""

from __future__ import annotations

from math import isfinite

from homeassistant.util import dt as dt_util

from .const import (
    WINDOW_ACTION_BLOCK_CLOSING_ONLY,
    WINDOW_ACTION_MOVE_TO_POSITION,
    WINDOW_ACTION_RETURN_AFTER_CLOSE,
)
from .decision import (
    EMERGENCY_DECISION_CODES,
    LEARNABLE_DECISION_CODES,
    SCHEDULE_EXEMPT_DECISION_CODES,
    behavioral_learning_allowed,
)
from .models import StateChangedData

THERMAL_CLOSING_DECISION_CODES = frozenset(
    {"auto", "strict_sun_block", "thermal_hold"}
)


class CoordinatorExecutionMixin:
    """Realizuj jedną decyzję bez obliczeń geometrii i klimatu."""

    async def async_handle_state_change(self, state: int, options):
        """Handle state change from tracked entities."""
        if self.control_toggle:
            for cover in self.entities:
                await self.async_handle_call_service(cover, state, options)
        else:
            self.logger.debug("State change but control toggle is off")
        self.logger.debug("State change handled")

    async def async_handle_cover_state_change(
        self,
        state: int,
        state_change_data: StateChangedData,
    ) -> None:
        """Handle state change from assigned covers."""
        if self.manual_toggle and self.control_toggle:
            entity_id = state_change_data.entity_id
            expected_state = (
                self._target_for_entity(entity_id, state)
                if entity_id is not None
                else state
            )
            climate = self.last_climate_data
            self.manager.handle_state_change(
                state_change_data,
                expected_state,
                self._cover_type,
                self.manual_reset,
                self.movement,
                self.manual_threshold,
                position_tolerance=self.min_change,
                current_temp=(climate.get_current_temperature if climate else None),
                is_summer=(climate.is_summer if climate else False),
                manual_until=self._manual_override_deadline(
                    state_change_data.new_state.last_updated
                    if state_change_data.new_state
                    else dt_util.utcnow()
                ),
                allow_learning=behavioral_learning_allowed(
                    self._decision_code(),
                    adaptive_movement_allowed=self.adaptive_movement_allowed,
                ),
            )
        self.logger.debug("Cover state change handled")

    async def async_handle_window_policy(self, entity: str, target_state: int) -> bool:
        """Apply configured behavior while the window or door is open."""
        if not self.is_window_open:
            return False

        action = self.window_open_action
        if action == WINDOW_ACTION_BLOCK_CLOSING_ONLY:
            current = self._get_current_position(entity)
            if current is not None and target_state < current:
                self.manager.set_status(entity, "blocked", "window_open_block_closing")
                self.logger.debug(
                    "Window open: blocked closing movement for %s", entity
                )
                return True
            return False

        if action == WINDOW_ACTION_MOVE_TO_POSITION:
            target = self._target_for_entity(entity, int(self.window_open_position))
            self.manager.set_status(entity, "window_open", "moving_to_window_position")
            if self.check_position(entity, target):
                await self.async_set_manual_position(
                    entity, target, enforce_current_target=False
                )
            return True

        if action == WINDOW_ACTION_RETURN_AFTER_CLOSE:
            self.manager.set_status(entity, "paused", "window_open_return_after_close")
            return True

        self.manager.set_status(entity, "paused", "window_open_pause")
        self.logger.debug("Window is open. Pausing adaptive movement for %s", entity)
        return True

    async def async_handle_first_refresh(self, state: int, options):
        """Handle first refresh."""
        if self.control_toggle:
            if self._night_purge_close_overdue():
                await self.async_handle_timed_refresh(state, options)
                self.logger.debug("Missed night-purge deadline handled at startup")
                return
            for cover in self.entities:
                await self.async_handle_call_service(cover, state, options)
        else:
            self.logger.debug("First refresh but control toggle is off")
        self.logger.debug("First refresh handled")

    async def async_handle_timed_refresh(self, state: int, options):
        """Handle timed refresh."""
        decision_code = self._decision_code()
        self.logger.debug(
            "Timed refresh: decision=%s, final state=%s",
            decision_code,
            state,
        )
        if self.control_toggle:
            for cover in self.entities:
                if self._pending_refreshes.generation > self._active_refresh_generation:
                    self.manager.set_status(
                        cover,
                        "skipped",
                        "newer_refresh_pending",
                    )
                    break
                target = self._target_for_entity(cover, state)
                if await self.async_handle_window_policy(cover, target):
                    continue
                if not self.manager.is_cover_manual(cover):
                    await self.async_set_manual_position(
                        cover, target, enforce_current_target=False
                    )
                else:
                    self.logger.debug(
                        "Skiping timed refresh for %s because it is under manual control",
                        cover,
                    )
        else:
            self.logger.debug("Timed refresh but control toggle is off")
        self.logger.debug("Timed refresh handled")

    async def async_handle_call_service(self, entity, state: int, options):
        """Handle call service."""
        if not self._runtime_initialized:
            self.manager.set_status(entity, "skipped", "runtime_initializing")
            return
        if self._pending_refreshes.generation > self._active_refresh_generation:
            self.manager.set_status(entity, "skipped", "newer_refresh_pending")
            return
        state = self._target_for_entity(entity, state)
        if await self.async_handle_window_policy(entity, state):
            return
        if self._pending_refreshes.generation > self._active_refresh_generation:
            self.manager.set_status(entity, "skipped", "newer_refresh_pending")
            return

        block_reason = self.movement_block_reason(entity, state, options)
        if block_reason is None:
            await self.async_set_position(entity, state)
        elif block_reason in {"cooldown", "hourly_move_limit", "daily_move_limit"}:
            self.manager.set_status(entity, "blocked", block_reason)
        else:
            self.manager.set_status(entity, "skipped", block_reason)

    def _target_for_entity(self, entity: str, state: int) -> int:
        """Zastosuj uczenie komfortu z zachowaniem fizycznych limitów pozycji."""
        if self._decision_code() in LEARNABLE_DECISION_CODES:
            state = self.learner.get_adjusted_position(entity, state)
        cover = getattr(getattr(self, "normal_cover_state", None), "cover", None)
        if cover is not None:
            if cover.apply_max_position and cover.max_pos is not None:
                state = min(state, int(cover.max_pos))
            if cover.apply_min_position and cover.min_pos is not None:
                state = max(state, int(cover.min_pos))
        return int(state)

    def _decision_code(self) -> str:
        """Return the decision code currently selected by the calculator."""
        if self.last_decision is not None:
            return self.last_decision.code
        cover = getattr(getattr(self, "normal_cover_state", None), "cover", None)
        return getattr(cover, "state_info", "auto")

    def movement_block_reason(self, entity, state: int, options) -> str | None:
        """Zwróć konkretny powód zablokowania ruchu rolety."""
        decision_code = self._decision_code()
        emergency = decision_code in EMERGENCY_DECISION_CODES
        cooling_release = self._is_cooling_release(entity, state)
        if (
            decision_code not in SCHEDULE_EXEMPT_DECISION_CODES
            and not self.adaptive_movement_allowed
        ):
            return "outside_adaptive_time"
        if not self.check_position_delta(entity, state, options):
            return "position_delta_too_small"
        if not emergency and not cooling_release and not self.check_time_delta(entity):
            return "time_delta_not_passed"
        if not emergency and self.manager.is_cover_manual(entity):
            return "manual_override_active"
        if not emergency and not self.manager.can_move(
            entity,
            self.global_cooldown,
            self.max_moves_per_hour,
            self.max_moves_per_day,
            bypass_cooldown=cooling_release,
        ):
            return self.manager.last_skip_reason.get(entity, "movement_limit")
        return None

    def _is_cooling_release(self, entity: str, state: int) -> bool:
        """Rozpoznaj bezpieczne otwarcie po niedawnym domknięciu słonecznym."""
        current = self._get_current_position(entity)
        climate = getattr(self, "last_climate_data", None)
        last_call = self.manager.last_service_call.get(entity, {})
        service_data = last_call.get("data", {})
        previous_target = service_data.get(
            "position", service_data.get("tilt_position")
        )
        previous_code = (
            last_call.get("context", {}).get("decision", {}).get("code")
        )

        try:
            values = (
                float(current),
                float(state),
                float(previous_target),
                float(climate.inside_temperature),
                float(climate.outside_temperature),
                float(climate.thermal_hold_release_delta),
            )
        except (AttributeError, TypeError, ValueError):
            return False

        current_position, target, previous, inside, outside, release_delta = values
        return bool(
            all(isfinite(value) for value in values)
            and previous_code in THERMAL_CLOSING_DECISION_CODES
            and target > current_position
            and previous < target
            and outside <= inside - release_delta
        )

    async def async_set_position(self, entity, state: int):
        """Ustaw pozycję przez wspólny wykonawca ruchów."""
        return await self.movement.async_set_position(entity, state)

    async def async_set_manual_position(
        self,
        entity,
        state,
        *,
        enforce_current_target: bool = True,
    ):
        """Ustaw pozycję poza automatyczną walidacją bieżącego celu."""
        return await self.movement.async_set_position(
            entity,
            state,
            enforce_current_target=enforce_current_target,
        )

    async def async_verify_and_retry(
        self,
        entity,
        target_state,
        service,
        service_data,
        *,
        generation,
        enforce_current_target=True,
        wait_time=45,
        max_retries=2,
    ):
        """Deleguj kontrolę celu i retry do wykonawcy ruchów."""
        await self.movement.async_verify_and_retry(
            entity,
            target_state,
            service,
            service_data,
            generation=generation,
            enforce_current_target=enforce_current_target,
            wait_time=wait_time,
            max_retries=max_retries,
        )

    def _retry_is_stale(
        self,
        entity: str,
        target_state: int,
        generation: int,
        enforce_current_target: bool,
    ) -> bool:
        """Sprawdź aktualność retry przez wspólny wykonawca ruchów."""
        return self.movement.retry_is_stale(
            entity,
            target_state,
            generation,
            enforce_current_target,
        )
