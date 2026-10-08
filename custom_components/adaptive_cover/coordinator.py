"""Koordynator integracji Adaptive Cover."""

from __future__ import annotations

import asyncio

from collections import deque
import datetime as dt
from time import perf_counter

import homeassistant.util.dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .climate import ClimateCoverData, TemperatureStabilityFilter
from .config_context_adapter import ConfigContextAdapter
from .const import (
    _LOGGER,
    CONF_CLIMATE_MODE,
    CONF_INTERP,
    CONF_INVERSE_STATE,
    CONF_MANUAL_IGNORE_INTERMEDIATE,
    CONF_MANUAL_OVERRIDE_DURATION,
    CONF_MANUAL_OVERRIDE_RESET,
    CONF_RETURN_SUNSET,
    DOMAIN,
    LOGGER,
)
from .coordinator_data import CoordinatorDataMixin
from .coordinator_events import CoordinatorEventsMixin
from .coordinator_execution import CoordinatorExecutionMixin
from .coordinator_pipeline import CoordinatorPipelineMixin
from .decision import DecisionResult
from .learning import BehavioralLearner
from .manual_control import AdaptiveCoverManager
from .models import (
    AdaptiveCoverData,
    PendingRefreshes,
    RefreshTrigger,
    StateChangedData,
)
from .movement import CoverMovementExecutor
from .options import normalize_options
from .schedule import ScheduleController, ScheduleResolver


class AdaptiveDataUpdateCoordinator(
    CoordinatorPipelineMixin,
    CoordinatorEventsMixin,
    CoordinatorExecutionMixin,
    CoordinatorDataMixin,
    DataUpdateCoordinator[AdaptiveCoverData],
):
    """Orkiestruj snapshot, decyzję, wykonanie i publikację."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Zainicjalizuj niezależne warstwy runtime wpisu konfiguracji."""
        self.config_entry = config_entry
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=dt.timedelta(minutes=1),
        )
        options = normalize_options(config_entry.options)
        self._initialize_configuration(options)
        self._initialize_decisions()
        self._initialize_runtime(options)
        self._initialize_schedule()
        self._initialize_health()
        self._register_unload_callbacks()

    def _initialize_configuration(self, options: dict) -> None:
        """Zapisz konfigurację wymaganą przed pierwszym snapshotem."""
        self.logger = ConfigContextAdapter(_LOGGER)
        self.logger.set_config_name(self.config_entry.data.get("name"))
        self._cover_type = self.config_entry.data.get("sensor_type")
        self._climate_mode = options[CONF_CLIMATE_MODE]
        self._switch_mode = bool(self._climate_mode)
        self._inverse_state = options[CONF_INVERSE_STATE]
        self._use_interpolation = options[CONF_INTERP]
        self._track_end_time = options[CONF_RETURN_SUNSET]
        self.manual_reset = options[CONF_MANUAL_OVERRIDE_RESET]
        self.manual_duration = options[CONF_MANUAL_OVERRIDE_DURATION]
        self.ignore_intermediate_states = options[CONF_MANUAL_IGNORE_INTERMEDIATE]
        self._active_options = options

    def _initialize_decisions(self) -> None:
        """Utwórz ograniczoną pamięć decyzji i stanów przełączników."""
        self._temp_toggle = None
        self._control_toggle = None
        self._manual_toggle = None
        self._lux_toggle = None
        self._irradiance_toggle = None
        self._strict_sun_block_toggle = False
        self._dry_run_toggle = False
        self._lux_low_light_state: bool | None = None
        self._irradiance_low_light_state: bool | None = None
        self._last_direct_sun_at: dt.datetime | None = None
        self._direct_sun_was_active = False
        self._cold_protection_active = False
        self._night_purge_active = False
        self._outside_temperature_filter = TemperatureStabilityFilter()
        self._outside_temperature_raw: float | None = None
        self._outside_temperature_reference: float | None = None
        self.last_decision: DecisionResult | None = None
        self._calculated_decision: DecisionResult | None = None
        self.last_decision_trace: list[dict] = []
        self.decision_history: deque[dict] = deque(maxlen=50)
        self.last_climate_data: ClimateCoverData | None = None
        self.climate_state = None
        self.control_method = "intermediate"

    def _initialize_runtime(self, options: dict) -> None:
        """Utwórz kolejkę zdarzeń, manager i wykonawcę ruchów."""
        self._pending_refreshes = PendingRefreshes()
        self._pending_cover_events: deque[StateChangedData] = deque()
        self._active_refresh_triggers: frozenset[RefreshTrigger] = frozenset()
        self._last_refresh_triggers: frozenset[RefreshTrigger] = frozenset()
        self._active_refresh_generation = 0
        self.state_change_data: StateChangedData | None = None
        self.learner = BehavioralLearner(
            self.hass,
            self.logger,
            self.config_entry.entry_id,
        )
        self.manager = AdaptiveCoverManager(
            options[CONF_MANUAL_OVERRIDE_DURATION],
            self.logger,
            self.learner,
        )
        self.movement = CoverMovementExecutor(self)
        self._unloading = False
        self._runtime_initialized = False
        self._runtime_initialization_task = None
        self._diagnostic_refresh = False
        self._update_lock = asyncio.Lock()

    def _initialize_schedule(self) -> None:
        """Utwórz jeden resolver i kontroler wszystkich terminów."""
        self._start_time = None
        self._resolved_schedule = None
        self._last_start_time_resolution = None
        self._last_end_time_resolution = None
        self._sun_start_time = None
        self._sun_end_time = None
        self._scheduled_time = None
        self._night_purge_scheduled_time = None
        self._update_listener = None
        self._night_purge_update_listener = None
        self.schedule_resolver = ScheduleResolver(dt_util.DEFAULT_TIME_ZONE)
        self.schedule_controller = ScheduleController(
            self.hass,
            async_track_point_in_time,
        )

    def _initialize_health(self) -> None:
        """Utwórz metryki zdrowia i cache prognozy."""
        self._started_at = dt.datetime.now(dt.UTC)
        self._update_count = 0
        self._last_update_started_at: dt.datetime | None = None
        self._last_update_finished_at: dt.datetime | None = None
        self._last_update_duration_ms: float | None = None
        self._last_update_error: str | None = None
        self._forecast_temperature: float | None = None
        self._forecast_fetched_at: dt.datetime | None = None
        self._forecast_entity: str | None = None

    def _register_unload_callbacks(self) -> None:
        """Powiąż timery i zadania z cyklem życia wpisu."""
        self.config_entry.async_on_unload(self._async_cancel_night_purge_listener)
        self.config_entry.async_on_unload(self._async_cancel_runtime_tasks)

    async def _async_update_data(self) -> AdaptiveCoverData:
        """Zmierz zdrowie jednego pełnego odświeżenia."""
        started = perf_counter()
        self._update_count += 1
        self._last_update_started_at = dt.datetime.now(dt.UTC)
        self._last_update_error = None
        try:
            return await self._async_calculate_update_data()
        except Exception as err:  # noqa: BLE001
            self._last_update_error = f"{type(err).__name__}: {err}"
            raise
        finally:
            self._last_update_finished_at = dt.datetime.now(dt.UTC)
            self._last_update_duration_ms = round(
                (perf_counter() - started) * 1000,
                3,
            )

    async def _async_calculate_update_data(self) -> AdaptiveCoverData:
        """Deleguj przebieg do etapowego pipeline."""
        async with self._update_lock:
            return await self.async_run_update_pipeline()
