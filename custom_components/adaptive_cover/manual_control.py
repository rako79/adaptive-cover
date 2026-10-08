"""Ręczne przejęcie, statusy i historia ruchów Adaptive Cover."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite

import datetime as dt
from typing import Any


class AdaptiveCoverManager:
    """Śledź ręczne przejęcia i historię poleceń dla rolet."""

    def __init__(self, reset_duration: dict[str, int], logger, learner=None) -> None:
        """Zainicjalizuj stan ręcznego sterowania."""
        self.covers: set[str] = set()
        self.manual_control: dict[str, bool] = {}
        self.manual_control_time: dict[str, dt.datetime] = {}
        self.manual_control_until: dict[str, dt.datetime] = {}
        self.reset_duration = dt.timedelta(**reset_duration)
        self.logger = logger
        self.learner = learner
        self.cover_status: dict[str, str] = {}
        self.status_reason: dict[str, str] = {}
        self.last_skip_reason: dict[str, str] = {}
        self.last_service_call: dict[str, dict] = {}
        self.last_service_error: dict[str, str] = {}
        self.movement_history: dict[str, list[dt.datetime]] = {}
        self.command_history: dict[str, list[dict]] = {}

    def add_covers(self, entities: list[str]) -> None:
        """Dodaj nowe rolety bez usuwania ich historii."""
        self.covers.update(entities)
        for cover in entities:
            self.cover_status.setdefault(cover, "auto")
            self.movement_history.setdefault(cover, [])
            self.command_history.setdefault(cover, [])

    def set_status(
        self,
        entity_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        """Zapisz bieżący status automatyki do diagnostyki."""
        self.cover_status[entity_id] = status
        if reason is not None:
            self.status_reason[entity_id] = reason
            if status in {"blocked", "skipped", "paused"}:
                self.last_skip_reason[entity_id] = reason

    def _prune_history(self, entity_id: str) -> None:
        """Ogranicz historię ruchów do ostatniej doby."""
        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
        self.movement_history[entity_id] = [
            moved_at
            for moved_at in self.movement_history.get(entity_id, [])
            if moved_at >= since
        ]

    def can_move(
        self,
        entity_id: str,
        cooldown_minutes: int | float | None,
        max_per_hour: int | None,
        max_per_day: int | None,
        *,
        bypass_cooldown: bool = False,
    ) -> bool:
        """Sprawdź cooldown i limity ruchów jednej rolety."""
        now = dt.datetime.now(dt.UTC)
        self._prune_history(entity_id)
        history = self.movement_history.setdefault(entity_id, [])

        if cooldown_minutes and history and not bypass_cooldown:
            cooldown = dt.timedelta(minutes=float(cooldown_minutes))
            if now - history[-1] < cooldown:
                self.set_status(entity_id, "blocked", "cooldown")
                return False

        last_hour = [
            moved_at for moved_at in history if now - moved_at <= dt.timedelta(hours=1)
        ]
        if max_per_hour and len(last_hour) >= int(max_per_hour):
            self.set_status(entity_id, "blocked", "hourly_move_limit")
            return False

        if max_per_day and len(history) >= int(max_per_day):
            self.set_status(entity_id, "blocked", "daily_move_limit")
            return False

        return True

    def record_move(
        self,
        entity_id: str,
        service: str,
        service_data: dict,
        *,
        dry_run: bool = False,
        command_context: dict | None = None,
    ) -> None:
        """Zapisz polecenie na potrzeby limitów i diagnostyki."""
        now = dt.datetime.now(dt.UTC)
        if not dry_run:
            self.movement_history.setdefault(entity_id, []).append(now)
            self._prune_history(entity_id)
        self.last_service_call[entity_id] = {
            "service": service,
            "data": dict(service_data),
            "dry_run": dry_run,
            "time": now.isoformat(),
            "context": deepcopy(command_context or {}),
        }
        history = self.command_history.setdefault(entity_id, [])
        history.append(
            {
                "service": service,
                "data": dict(service_data),
                "dry_run": dry_run,
                "requested_at": now,
                "context": deepcopy(command_context or {}),
            }
        )
        del history[:-50]
        self.last_service_error.pop(entity_id, None)

    def movement_counts(self, period: dt.timedelta) -> dict[str, int]:
        """Zwróć liczbę ruchów każdej rolety w zadanym okresie."""
        now = dt.datetime.now(dt.UTC)
        return {
            entity_id: len(
                [moved_at for moved_at in history if now - moved_at <= period]
            )
            for entity_id, history in self.movement_history.items()
        }

    def handle_state_change(
        self,
        states_data,
        our_state,
        blind_type,
        allow_reset,
        movement,
        manual_threshold,
        position_tolerance=1,
        current_temp=None,
        is_summer=False,
        manual_until=None,
        allow_learning=True,
    ) -> None:
        """Rozpoznaj, czy zmiana położenia pochodzi od użytkownika."""
        event = states_data
        if event is None or event.entity_id not in self.covers:
            return

        new_state = event.new_state
        if new_state is None:
            return

        attribute = (
            "current_tilt_position"
            if blind_type == "cover_tilt"
            else "current_position"
        )
        new_position = new_state.attributes.get(attribute)

        tolerance = max(
            float(position_tolerance),
            (float(manual_threshold) if manual_threshold is not None else 2.0),
        )
        if movement.observe_position_event(
            event.entity_id,
            position=new_position,
            movement_state=new_state.state,
            tolerance=tolerance,
        ):
            return

        old_state = event.old_state
        if new_state.state in {"opening", "closing", "unknown", "unavailable"}:
            return
        if old_state is None or old_state.state in {"unknown", "unavailable"}:
            return
        if old_state.attributes.get(attribute) == new_position:
            # Zmiana atrybutu lub ponowny raport nie jest ręcznym ruchem.
            return

        if new_position is None or our_state is None:
            self.logger.debug(
                "No usable position in state change for %s",
                event.entity_id,
            )
            return
        if not isfinite(float(new_position)) or not 0 <= float(new_position) <= 100:
            return

        if new_position == our_state:
            return
        if (
            manual_threshold is not None
            and abs(our_state - new_position) < manual_threshold
        ):
            self.logger.debug(
                "Position change is less than threshold %s for %s",
                manual_threshold,
                event.entity_id,
            )
            return

        self.logger.debug(
            "Manual change detected for %s. Our state: %s, new state: %s",
            event.entity_id,
            our_state,
            new_position,
        )
        self.mark_manual_control(event.entity_id)
        self.set_last_updated(
            event.entity_id,
            new_state,
            allow_reset,
            manual_until,
        )

        if self.learner and allow_learning:
            self.learner.register_override(
                event.entity_id,
                current_temp,
                our_state,
                new_position,
                is_summer,
            )

    def set_last_updated(
        self,
        entity_id: str,
        new_state: Any,
        allow_reset: bool,
        manual_until: dt.datetime | None = None,
    ) -> None:
        """Zapisz niezmienny termin zakończenia ręcznego przejęcia."""
        if entity_id not in self.manual_control_time or allow_reset:
            last_updated = new_state.last_updated
            self.manual_control_time[entity_id] = last_updated
            self.manual_control_until[entity_id] = (
                manual_until
                if manual_until is not None
                else last_updated + self.reset_duration
            )
            self.logger.debug(
                "Updating last updated for manual control to %s for %s. Allow reset:%s",
                last_updated,
                entity_id,
                allow_reset,
            )
            return
        self.logger.debug(
            "Already manual control time specified for %s, reset is not "
            "allowed by user setting:%s",
            entity_id,
            allow_reset,
        )

    def mark_manual_control(self, cover: str) -> None:
        """Oznacz roletę jako sterowaną ręcznie."""
        self.manual_control[cover] = True
        self.set_status(cover, "manual_override", "manual_position_change")

    async def reset_if_needed(self) -> None:
        """Wyłącz przejęcia, których termin już minął."""
        current_time = dt.datetime.now(dt.UTC)
        for entity_id, last_updated in dict(self.manual_control_time).items():
            deadline = self.manual_control_until.get(
                entity_id,
                last_updated + self.reset_duration,
            )
            if current_time >= deadline:
                self.logger.debug(
                    "Resetting manual override for %s, because duration has elapsed",
                    entity_id,
                )
                self.reset(entity_id)

    def reset(self, entity_id: str) -> None:
        """Przywróć automatyczne sterowanie jednej rolety."""
        self.manual_control[entity_id] = False
        self.manual_control_time.pop(entity_id, None)
        self.manual_control_until.pop(entity_id, None)
        self.set_status(entity_id, "auto", "manual_override_reset")
        self.logger.debug("Reset manual override for %s", entity_id)

    def is_cover_manual(self, entity_id: str) -> bool:
        """Sprawdź, czy roleta jest sterowana ręcznie."""
        return self.manual_control.get(entity_id, False)

    @property
    def binary_cover_manual(self) -> bool:
        """Sprawdź, czy dowolna roleta ma aktywne przejęcie."""
        return any(self.manual_control.values())

    @property
    def manual_controlled(self) -> list[str]:
        """Zwróć listę rolet sterowanych ręcznie."""
        return [
            entity_id
            for entity_id, is_manual in self.manual_control.items()
            if is_manual
        ]
