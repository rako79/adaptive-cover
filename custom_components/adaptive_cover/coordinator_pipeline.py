"""Etapowy przebieg aktualizacji koordynatora Adaptive Cover."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any

import homeassistant.util.dt as dt_util

from .climate import NormalCoverState
from .const import (
    CONF_AZIMUTH,
    CONF_BLIND_SPOT_ELEVATION,
    CONF_DEFAULT_HEIGHT,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_NIGHT_PURGE_END_TIME,
    CONF_SUNSET_OFFSET,
    CONF_SUNSET_POS,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_FORECAST_TEMP,
)
from .decision import (
    DecisionArbiter,
    DecisionResult,
    apply_runtime_policies,
    decision_priority,
    inverse_state,
)
from .models import AdaptiveCoverData, RefreshTrigger, StateChangedData
from .options import normalize_options


@dataclass(slots=True)
class UpdateCycle:
    """Dane jednej, niezmiennej partii aktualizacji."""

    options: dict
    cover: Any
    triggers: set[RefreshTrigger]
    cover_events: list[StateChangedData]
    state: int
    start: dt.datetime | None = None
    end: dt.datetime | None = None


class CoordinatorPipelineMixin:
    """Orkiestruj krótkie fazy jednego odświeżenia."""

    async def async_run_update_pipeline(self) -> AdaptiveCoverData:
        """Wykonaj pełny przebieg obliczeń, wykonania i publikacji."""
        cycle = await self._prepare_update_cycle()
        if not self._diagnostic_refresh:
            await self._sync_end_timer(cycle)
        self._apply_scheduled_close_decision(cycle)
        await self._execute_pending_events(cycle)
        cycle.start, cycle.end = await self._solar_window(cycle)
        learned_targets = self._record_decision(cycle)
        return self._build_adaptive_data(cycle, learned_targets)

    async def _prepare_update_cycle(self) -> UpdateCycle:
        """Pobierz zdarzenia i zbuduj jeden snapshot decyzji."""
        _generation, triggers, cover_events = self._drain_execution_events()
        options = normalize_options(self.config_entry.options)
        self._active_options = options
        self._update_options(options)
        cover = self.get_blind_data(options=options)
        self.resolve_schedule(options, cover)
        if not self._diagnostic_refresh:
            self._schedule_night_purge_close()
        self._update_manager_and_covers()
        await self._calculate_cover_state(options, cover)
        state = self._finalize_decision(cover)
        await self.manager.reset_if_needed()
        return UpdateCycle(options, cover, triggers, cover_events, state)

    async def _calculate_cover_state(self, options: dict, cover: Any) -> None:
        """Oblicz bazową i klimatyczną pozycję dla jednego snapshota."""
        self._calculated_decision = None
        if self._climate_mode:
            options = dict(options)
            options[
                CONF_WEATHER_FORECAST_TEMP
            ] = await self.async_get_weather_forecast_temperature(
                options.get(CONF_WEATHER_ENTITY)
            )
            self.climate_mode_data(options, cover)
        else:
            self.last_climate_data = None
            self.last_decision_trace = []

        self.normal_cover_state = NormalCoverState(cover)
        self.default_state = round(self.normal_cover_state.get_state())
        if not self._climate_mode:
            self.climate_state = self.default_state

    def _base_decision(self, cover: Any, state: int) -> DecisionResult:
        """Powiąż przekształconą pozycję z wybraną regułą domenową."""
        calculated = self._calculated_decision if self._switch_mode else None
        code = (
            calculated.code
            if calculated is not None
            else (
                "night_mode"
                if cover.sunset_valid
                else ("auto" if cover.direct_sun_valid else "sun_shadow")
            )
        )
        reason = (
            calculated.reason
            if calculated is not None
            else {
                "night_mode": "Tryb nocny: pozycja nocna.",
                "sun_shadow": "Słońce poza zasięgiem okna: pozycja domyślna.",
                "auto": "Działanie automatyczne według geometrii słońca.",
            }[code]
        )
        if calculated is None:
            self.last_decision_trace = [
                {
                    "code": code,
                    "active": True,
                    "selected": True,
                    "priority": decision_priority(code),
                    "outcome": "selected",
                }
            ]
        inputs = dict(calculated.inputs) if calculated is not None else {}
        inputs |= {
            "sun_azimuth": cover.sol_azi,
            "sun_elevation": cover.sol_elev,
            "direct_sun_valid": cover.direct_sun_valid,
        }
        return DecisionResult(
            target_position=state,
            code=code,
            reason=reason,
            priority=decision_priority(code),
            inputs=inputs,
        )

    def _finalize_decision(self, cover: Any) -> int:
        """Zastosuj transformacje, limity i nadrzędne polityki runtime."""
        base = self._base_decision(cover, self.state)
        constrained, constraint = DecisionArbiter.constrain_position(
            base,
            minimum=cover.min_pos,
            maximum=cover.max_pos,
            apply_minimum=cover.apply_min_position,
            apply_maximum=cover.apply_max_position,
        )
        self._merge_constraint_trace(constraint)
        selected, runtime_trace = apply_runtime_policies(
            constrained,
            control_enabled=bool(self.control_toggle),
            window_open=self.is_window_open,
            window_action=self.window_open_action,
            window_position=self.window_open_position,
        )
        self._merge_runtime_trace(selected, runtime_trace)
        self.last_decision = selected
        cover.state_info = selected.code
        cover.state_reason = selected.reason
        return selected.target_position

    def _merge_constraint_trace(self, constraint: dict | None) -> None:
        """Dodaj do śladu fizyczne ograniczenie finalnej pozycji."""
        if constraint is None:
            return
        self.last_decision_trace.append(
            {
                **constraint,
                "active": True,
                "selected": False,
                "outcome": "applied_constraint",
            }
        )

    def _merge_runtime_trace(
        self,
        selected: DecisionResult,
        runtime_trace: list[dict],
    ) -> None:
        """Oznacz rzeczywistego zwycięzcę po politykach wykonawczych."""
        runtime_override = selected.code in {"control_disabled", "window_open"}
        if runtime_override:
            for item in self.last_decision_trace:
                if item.get("selected"):
                    item["selected"] = False
                    item["outcome"] = "overridden_by_runtime_policy"
        for item in runtime_trace:
            if item["code"] in {"control_disabled", "window_open"}:
                self.last_decision_trace.append(item)
        if not self.last_decision_trace:
            self.last_decision_trace = runtime_trace

    async def _sync_end_timer(self, cycle: UpdateCycle) -> None:
        """Dopasuj timer końca do rozstrzygniętego harmonogramu."""
        end_time = self._end_time
        if not self._track_end_time or end_time is None:
            if self._scheduled_time is not None:
                self._async_cancel_update_listener()
            return
        schedule = self._resolved_schedule
        if (
            schedule is not None
            and schedule.start.value is not None
            and schedule.end.value is not None
            and schedule.start.value > schedule.end.value
            and dt_util.now() >= schedule.start.value
        ):
            end_time = dt_util.as_utc(dt_util.as_local(end_time) + dt.timedelta(days=1))
        if end_time == self._scheduled_time:
            return
        if end_time > dt_util.utcnow():
            await self.async_timed_end_time(end_time)
            return
        self._async_cancel_update_listener()
        self._scheduled_time = end_time
        cycle.triggers.add(RefreshTrigger.TIMED_END)

    def _scheduled_close_code(self, cycle: UpdateCycle) -> str | None:
        """Rozpoznaj termin wymagający jawnej pozycji zamknięcia."""
        if RefreshTrigger.TIMED_END in cycle.triggers:
            return "timed_end"
        if RefreshTrigger.NIGHT_PURGE_DEADLINE in cycle.triggers:
            return "night_purge_end"
        if (
            RefreshTrigger.FIRST_REFRESH in cycle.triggers
            and self._night_purge_close_overdue()
        ):
            return "night_purge_end"
        return None

    def _apply_scheduled_close_decision(self, cycle: UpdateCycle) -> None:
        """Dodaj termin zamknięcia do arbitra przed wykonaniem ruchu."""
        decision_code = self._scheduled_close_code(cycle)
        if decision_code is None:
            return
        sunset_position = cycle.options.get(CONF_SUNSET_POS)
        if sunset_position is None:
            return
        target = (
            inverse_state(sunset_position)
            if self._inverse_state
            else int(sunset_position)
        )
        reason = (
            "Osiągnięto skonfigurowany koniec harmonogramu."
            if decision_code == "timed_end"
            else "Zakończono nocne przewietrzanie; przywrócono pozycję nocną."
        )
        scheduled = DecisionResult(
            target_position=target,
            code=decision_code,
            reason=reason,
            priority=decision_priority(decision_code),
            inputs={
                "sunset_position": int(sunset_position),
                "refresh_triggers": sorted(item.value for item in cycle.triggers),
            },
        )
        scheduled, constraint = DecisionArbiter.constrain_position(
            scheduled,
            minimum=cycle.cover.min_pos,
            maximum=cycle.cover.max_pos,
            apply_minimum=cycle.cover.apply_min_position,
            apply_maximum=cycle.cover.apply_max_position,
        )
        selected = DecisionArbiter.select([self.last_decision, scheduled])
        selected_scheduled = selected is scheduled
        if selected_scheduled:
            for item in self.last_decision_trace:
                if item.get("selected"):
                    item["selected"] = False
                    item["outcome"] = f"overridden_by_{decision_code}"
            self.last_decision = scheduled
            cycle.state = scheduled.target_position
            cycle.cover.state_info = scheduled.code
            cycle.cover.state_reason = scheduled.reason
        self.last_decision_trace.append(
            {
                "code": scheduled.code,
                "priority": scheduled.priority,
                "active": True,
                "selected": selected_scheduled,
                "outcome": (
                    "selected"
                    if selected_scheduled
                    else "overridden_by_higher_priority"
                ),
                "target_position": scheduled.target_position,
            }
        )
        if selected_scheduled:
            self._merge_constraint_trace(constraint)

    async def _execute_pending_events(self, cycle: UpdateCycle) -> None:
        """Obsłuż partię zdarzeń w ustalonej kolejności."""
        if not self._runtime_initialized or self._diagnostic_refresh:
            return
        self._active_refresh_triggers = frozenset(cycle.triggers)
        for cover_event in cycle.cover_events:
            await self.async_handle_cover_state_change(cycle.state, cover_event)
        for entity in self.entities:
            self.movement.reconcile(
                entity, self._target_for_entity(entity, cycle.state)
            )
        timed = {
            RefreshTrigger.TIMED_END,
            RefreshTrigger.NIGHT_PURGE_DEADLINE,
        }
        if cycle.triggers & timed:
            await self.async_handle_timed_refresh(cycle.state, cycle.options)
        elif RefreshTrigger.FIRST_REFRESH in cycle.triggers:
            await self.async_handle_first_refresh(cycle.state, cycle.options)
        elif cycle.triggers & {RefreshTrigger.ENTITY_STATE, RefreshTrigger.PERIODIC}:
            await self.async_handle_state_change(cycle.state, cycle.options)
        self._last_refresh_triggers = frozenset(cycle.triggers)
        self._active_refresh_triggers = frozenset()

    async def _solar_window(
        self,
        cycle: UpdateCycle,
    ) -> tuple[dt.datetime | None, dt.datetime | None]:
        """Odśwież kosztowny zakres bezpośredniego słońca raz dziennie."""
        refresh = (
            RefreshTrigger.FIRST_REFRESH in cycle.triggers
            or self._sun_start_time is None
            or dt_util.now().date() != dt_util.as_local(self._sun_start_time).date()
        )
        if refresh:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, cycle.cover.solar_times)
            self._sun_start_time, self._sun_end_time = result
        return self._sun_start_time, self._sun_end_time

    def _record_decision(self, cycle: UpdateCycle) -> dict[str, int]:
        """Zapisz finalny cel każdej rolety w ograniczonej historii."""
        targets = {
            entity: self._target_for_entity(entity, cycle.state)
            for entity in self.entities
        }
        self.decision_history.append(
            {
                "timestamp": dt.datetime.now(dt.UTC),
                "refresh_generation": self._active_refresh_generation,
                "refresh_triggers": sorted(item.value for item in cycle.triggers),
                "decision": self.last_decision.as_dict(),
                "decision_trace": list(self.last_decision_trace),
                "final_targets": targets,
                "cover_status": dict(self.manager.cover_status),
                "status_reason": dict(self.manager.status_reason),
            }
        )
        return targets

    def _state_payload(self, cycle: UpdateCycle) -> dict:
        """Zbuduj stany publikowane przez encje integracji."""
        return {
            "state": cycle.state,
            "start": cycle.start,
            "end": cycle.end,
            "control": self.control_method,
            "explanation": self.last_decision.code,
            "state_reason": self.last_decision.reason,
            "sun_motion": cycle.cover.valid,
            "manual_override": self.manager.binary_cover_manual,
            "manual_list": self.manager.manual_controlled,
            "cover_status": self.manager.cover_status,
        }

    def _decision_attributes(
        self,
        cycle: UpdateCycle,
        targets: dict[str, int],
    ) -> dict:
        """Zbuduj diagnostykę decyzji i harmonogramu."""
        end_resolution = self._last_end_time_resolution
        return {
            "target_position": cycle.state,
            "decision": self.last_decision.as_dict(),
            "decision_trace": list(self.last_decision_trace),
            "learned_targets": targets,
            "final_targets": targets,
            "refresh_triggers": sorted(item.value for item in cycle.triggers),
            "refresh_generation": self._active_refresh_generation,
            "end_time_source": end_resolution.source if end_resolution else None,
            "end_time_raw_value": end_resolution.raw_value if end_resolution else None,
            "end_time_fallback_reason": (
                end_resolution.fallback_reason if end_resolution else None
            ),
            "start_time_source": (
                self._last_start_time_resolution.source
                if self._last_start_time_resolution
                else None
            ),
        }

    def _configuration_attributes(self, cycle: UpdateCycle) -> dict:
        """Zbuduj stabilne parametry geometrii i polityk."""
        options = cycle.options
        return {
            "default": options.get(CONF_DEFAULT_HEIGHT),
            "sunset_default": options.get(CONF_SUNSET_POS),
            "sunset_offset": options.get(CONF_SUNSET_OFFSET),
            "azimuth_window": options.get(CONF_AZIMUTH),
            "field_of_view": [
                options.get(CONF_FOV_LEFT),
                options.get(CONF_FOV_RIGHT),
            ],
            "blind_spot": options.get(CONF_BLIND_SPOT_ELEVATION),
            "dry_run": self.dry_run_toggle,
            "window_open": self.is_window_open,
            "window_open_action": self.window_open_action,
            "window_open_position": self.window_open_position,
            "night_purge_end_time": options.get(
                CONF_NIGHT_PURGE_END_TIME,
                "07:00:00",
            ),
            "night_purge_next_close": (
                self._night_purge_scheduled_time.isoformat()
                if self._night_purge_scheduled_time
                else None
            ),
            "sun_azimuth": cycle.cover.sol_azi,
            "sun_elevation": cycle.cover.sol_elev,
        }

    def _movement_attributes(self) -> dict:
        """Zbuduj diagnostykę wykonawcy i ręcznego przejęcia."""
        return {
            "last_skip_reason": self.manager.last_skip_reason,
            "status_reason": self.manager.status_reason,
            "last_service_call": self.manager.last_service_call,
            "last_service_error": self.manager.last_service_error,
            "movement_count_last_hour": self.manager.movement_counts(
                dt.timedelta(hours=1)
            ),
            "movement_count_last_day": self.manager.movement_counts(
                dt.timedelta(days=1)
            ),
            "cover_status": self.manager.cover_status,
        }

    def _climate_attributes(self) -> dict:
        """Zbuduj diagnostykę dokładnie z użytego snapshota klimatu."""
        climate = self.last_climate_data
        if climate is None:
            return {}
        return {
            "lux_low_light": self._lux_low_light_state,
            "irradiance_low_light": self._irradiance_low_light_state,
            "lux": climate.lux_value,
            "irradiance": climate.irradiance_value,
            "low_light": climate.low_light,
            "is_summer": climate.is_summer,
            "is_winter": climate.is_winter,
            "inside_temperature_entity": climate.inside_temperature_entity,
            "outside_temperature_entity": climate.outside_temperature_entity,
            "temperature_source": climate.temperature_source,
            "inside_temperature_available": climate.inside_temperature is not None,
            "inside_temperature": climate.inside_temperature,
            "current_temperature": climate.get_current_temperature,
            "outside_temperature": climate.outside_temperature,
            "outside_temperature_raw": self._outside_temperature_raw,
            "outside_temperature_reference": self._outside_temperature_reference,
            "outside_temperature_filter": (
                self._outside_temperature_filter.diagnostics()
            ),
            "cold_protection_active": climate.cold_protection_active,
            "cold_protection_activation_threshold": climate.cold_threshold,
            "cold_protection_release_threshold": (
                climate.cold_threshold + climate.cold_hysteresis
            ),
            "forecast_temperature": climate.forecast_temperature,
            "thermal_stress": climate.thermal_stress,
            "last_direct_sun_at": self._last_direct_sun_at,
            "is_raining": climate.is_raining,
            "rain_rate": climate.rain_value,
            "weather_state": climate.weather_state,
            "wind_speed": climate.current_wind_speed,
        }

    def _build_adaptive_data(
        self,
        cycle: UpdateCycle,
        targets: dict[str, int],
    ) -> AdaptiveCoverData:
        """Połącz gotowe sekcje bez ponownego odczytu Home Assistant."""
        attributes = (
            self._configuration_attributes(cycle)
            | self._decision_attributes(cycle, targets)
            | self._movement_attributes()
            | self._climate_attributes()
        )
        return AdaptiveCoverData(
            climate_mode_toggle=self.switch_mode,
            states=self._state_payload(cycle),
            attributes=attributes,
        )
