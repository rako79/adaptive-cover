"""Zdarzenia, timery i cykl życia runtime koordynatora."""

from __future__ import annotations

import asyncio
import datetime as dt

import homeassistant.util.dt as dt_util
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_NIGHT_PURGE_ENABLED, CONF_NIGHT_PURGE_END_TIME
from .models import PendingRefreshes, RefreshTrigger, StateChangedData

RUNTIME_INITIALIZATION_DELAY = 2


def _as_float(value, default=None):
    """Zamień wartość Home Assistant na liczbę, gdy jest dostępna."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class CoordinatorEventsMixin:
    """Obsługuj zdarzenia i timery bez obliczeń domenowych."""

    @property
    def state_change(self) -> bool:
        """Zwróć, czy oczekuje zwykła zmiana śledzonej encji."""
        return self._pending_refreshes.contains(RefreshTrigger.ENTITY_STATE)

    @property
    def cover_state_change(self) -> bool:
        """Zwróć, czy oczekuje zdarzenie położenia rolety."""
        return bool(self._pending_cover_events)

    @property
    def first_refresh(self) -> bool:
        """Zwróć, czy oczekuje pierwszy wykonawczy przebieg runtime."""
        return self._pending_refreshes.contains(RefreshTrigger.FIRST_REFRESH)

    @property
    def timed_refresh(self) -> bool:
        """Zwróć, czy oczekuje wykonanie terminu harmonogramu."""
        return bool(
            self._pending_refreshes.values
            & {
                RefreshTrigger.TIMED_END,
                RefreshTrigger.NIGHT_PURGE_DEADLINE,
            }
        )

    def _drain_execution_events(
        self,
    ) -> tuple[int, set[RefreshTrigger], list[StateChangedData]]:
        """Pobierz jedną partię zdarzeń przed pierwszą operacją asynchroniczną."""
        if self._diagnostic_refresh or not self._runtime_initialized:
            return 0, set(), []
        generation, triggers = self._pending_refreshes.drain()
        if not triggers:
            triggers = frozenset({RefreshTrigger.PERIODIC})
        cover_events = list(self._pending_cover_events)
        self._pending_cover_events.clear()
        self._active_refresh_generation = generation
        self._active_refresh_triggers = triggers
        return generation, set(triggers), cover_events

    async def async_config_entry_first_refresh(self) -> None:
        """Config entry first refresh."""
        await self.learner.async_load()
        self._last_direct_sun_at = self.learner.last_direct_sun_at
        await super().async_config_entry_first_refresh()
        self.logger.debug("Config entry first refresh")

    @callback
    def schedule_runtime_initialization(self) -> None:
        """Schedule one movement pass after startup entities settle."""
        if self._runtime_initialized or (
            self._runtime_initialization_task is not None
            and not self._runtime_initialization_task.done()
        ):
            return
        self._runtime_initialization_task = self._create_background_task(
            self.async_runtime_entities_initialized(),
            f"adaptive_cover initialize runtime for {self.config_entry.entry_id}",
        )

    async def async_runtime_entities_initialized(self) -> None:
        """Enable physical movement after Home Assistant startup stabilizes."""
        await asyncio.sleep(RUNTIME_INITIALIZATION_DELAY)
        if self._unloading or self._runtime_initialized:
            return
        self._pending_refreshes = PendingRefreshes()
        self._pending_cover_events.clear()
        self.state_change_data = None
        self._runtime_initialized = True
        self._pending_refreshes.add(RefreshTrigger.FIRST_REFRESH)
        await self.async_refresh()

    async def async_diagnostic_refresh(self) -> None:
        """Przelicz eksport w osobnym cyklu bez przejmowania zdarzeń wykonawczych."""
        async with self._update_lock:
            self._diagnostic_refresh = True
            try:
                data = await self.async_run_update_pipeline()
            finally:
                self._diagnostic_refresh = False
            self.async_set_updated_data(data)

    def _create_background_task(self, target, name: str):
        """Create a lifecycle-bound task which never delays Home Assistant startup."""
        entry_create_task = getattr(
            self.config_entry,
            "async_create_background_task",
            None,
        )
        if entry_create_task is not None:
            return entry_create_task(self.hass, target, name)

        hass_create_task = getattr(self.hass, "async_create_background_task", None)
        if hass_create_task is not None:
            return hass_create_task(target, name)

        return self.hass.async_create_task(target, name)

    def _update_verify_metadata(
        self,
        entity: str,
        *,
        expected_generation: int | None = None,
        **changes,
    ) -> None:
        """Update the bounded retry snapshot retained for one cover."""
        self.movement.update_metadata(
            entity,
            expected_generation=expected_generation,
            **changes,
        )

    async def async_timed_refresh(self, event) -> None:
        """Control state at end time."""
        self.schedule_controller.mark_fired("end_time")
        self._update_listener = None
        self._scheduled_time = None
        self._pending_refreshes.add(RefreshTrigger.TIMED_END)
        self.logger.debug("Timed refresh triggered at %s", dt_util.now())
        await self.async_refresh()

    async def async_get_weather_forecast_temperature(
        self, weather_entity: str | None
    ) -> float | None:
        """Get today's forecast temperature using Home Assistant weather service."""
        if not weather_entity:
            return None

        cached_temperature = (
            self._forecast_temperature
            if self._forecast_entity == weather_entity
            else None
        )
        now = dt_util.utcnow()
        if (
            self._forecast_entity == weather_entity
            and self._forecast_fetched_at is not None
            and now - self._forecast_fetched_at < dt.timedelta(hours=1)
        ):
            return cached_temperature

        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": weather_entity, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            self.logger.debug(
                "Unable to fetch weather forecast for %s: %s",
                weather_entity,
                err,
            )
            return cached_temperature

        forecast = response.get(weather_entity, {}).get("forecast", [])
        if not forecast:
            return cached_temperature
        self._forecast_entity = weather_entity
        self._forecast_fetched_at = now
        self._forecast_temperature = _as_float(forecast[0].get("temperature"))
        return self._forecast_temperature

    async def async_check_entity_state_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Fetch and process state change event."""
        self.logger.debug("Entity state change")
        self._pending_refreshes.add(RefreshTrigger.ENTITY_STATE)
        await self.async_refresh()

    async def async_check_cover_state_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Fetch and process state change event."""
        self.logger.debug("Cover state change")
        data = event.data
        if data["old_state"] is None or data["new_state"] is None:
            self.logger.debug("Incomplete cover state-change event")
            return
        state_change = StateChangedData(
            data["entity_id"], data["old_state"], data["new_state"]
        )
        if self.ignore_intermediate_states and state_change.new_state.state in {
            "opening",
            "closing",
        }:
            self.logger.debug("Ignoring intermediate cover state")
            return
        if state_change.old_state.state != "unknown":
            self.state_change_data = state_change
            self._pending_cover_events.append(state_change)
            self._pending_refreshes.add(RefreshTrigger.COVER_STATE)
            self.process_entity_state_change(state_change)
            await self.async_refresh()
        else:
            self.logger.debug("Old state is unknown, not processing")

    def process_entity_state_change(
        self,
        event: StateChangedData | None = None,
    ) -> None:
        """Process state change event."""
        event = event or self.state_change_data
        if event is None or event.new_state is None:
            return
        self.logger.debug("Processing state change event: %s", event)
        entity_id = event.entity_id
        if self.ignore_intermediate_states and event.new_state.state in [
            "opening",
            "closing",
        ]:
            self.logger.debug("Ignoring intermediate state change for %s", entity_id)
            return
        if self.movement.is_waiting(entity_id):
            position = event.new_state.attributes.get(
                "current_position"
                if self._cover_type != "cover_tilt"
                else "current_tilt_position"
            )
            if position == self.movement.target_for(entity_id):
                self.logger.debug("Position %s reached for %s", position, entity_id)
            self.logger.debug(
                "Wait for target: %s",
                self.movement.wait_for_target,
            )
        else:
            self.logger.debug("No wait for target call for %s", entity_id)

    @callback
    def _async_cancel_update_listener(self) -> None:
        """Cancel the scheduled update."""
        self.schedule_controller.cancel("end_time")
        self._update_listener = None
        self._scheduled_time = None

    @callback
    def _async_cancel_night_purge_listener(self) -> None:
        """Anuluj zaplanowane zamknięcie po nocnym wietrzeniu."""
        self.schedule_controller.cancel("night_purge")
        self._night_purge_update_listener = None
        self._night_purge_scheduled_time = None

    @callback
    def _async_cancel_runtime_tasks(self) -> None:
        """Cancel callbacks and verification tasks owned by this coordinator."""
        self._unloading = True
        self._async_cancel_update_listener()
        self._async_cancel_night_purge_listener()
        self.schedule_controller.cancel_all()
        self.movement.cancel()

    def _next_night_purge_close_time(self) -> dt.datetime | None:
        """Wyznacz najbliższą godzinę zamknięcia po nocnym wietrzeniu."""
        value = self._active_options.get(CONF_NIGHT_PURGE_END_TIME, "07:00:00")
        target_local = self.schedule_resolver.next_deadline(
            local_now=dt_util.now(),
            configured_time=value,
        )
        if target_local is None:
            self.logger.warning("Invalid night purge end time: %s", value)
            return None
        return dt_util.as_utc(target_local)

    def _schedule_night_purge_close(self) -> None:
        """Zaplanuj punktualne zamknięcie po nocnym wietrzeniu."""
        enabled = self._active_options.get(CONF_NIGHT_PURGE_ENABLED, True)
        if not self._climate_mode or not enabled or not self.switch_mode:
            self._async_cancel_night_purge_listener()
            return

        target = self._next_night_purge_close_time()
        if target is None or target == self._night_purge_scheduled_time:
            return

        self._async_cancel_night_purge_listener()
        self._night_purge_update_listener = self.schedule_controller.schedule(
            "night_purge",
            target,
            self.async_close_after_night_purge,
        )
        self._night_purge_scheduled_time = target
        self.logger.debug("Night purge close scheduled at %s", target)

    async def async_close_after_night_purge(self, _event) -> None:
        """Zamknij rolety punktualnie po zakończeniu nocnego wietrzenia."""
        self.schedule_controller.mark_fired("night_purge")
        self._night_purge_update_listener = None
        self._night_purge_scheduled_time = None

        self._pending_refreshes.add(RefreshTrigger.NIGHT_PURGE_DEADLINE)
        await self.async_refresh()
        self._schedule_night_purge_close()

    def _night_purge_close_overdue(self) -> bool:
        """Return whether startup occurred after a missed morning purge deadline."""
        if not (
            self._climate_mode
            and self.switch_mode
            and self._active_options.get(CONF_NIGHT_PURGE_ENABLED, True)
        ):
            return False
        return self.schedule_resolver.night_purge_overdue(
            local_now=dt_util.now(),
            configured_time=self._active_options.get(
                CONF_NIGHT_PURGE_END_TIME,
                "07:00:00",
            ),
            start_time=self._start_time,
        )

    async def async_timed_end_time(self, target: dt.datetime | None = None) -> None:
        """Zaplanuj zamknięcie na właściwy dzień także dla zakresu przez północ."""
        target = target if target is not None else self._end_time
        self.logger.debug("Scheduling end time update at %s", self._end_time)
        self._async_cancel_update_listener()
        self.logger.debug(
            "End time: %s, Track end time: %s, Scheduled time: %s, Condition: %s",
            self._end_time,
            self._track_end_time,
            self._scheduled_time,
            self._end_time != self._scheduled_time,
        )
        self._update_listener = self.schedule_controller.schedule(
            "end_time",
            target,
            self.async_timed_refresh,
        )
        self._scheduled_time = target
