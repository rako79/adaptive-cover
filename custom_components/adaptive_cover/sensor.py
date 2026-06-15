"""Sensor platform for Adaptive Cover integration."""

from __future__ import annotations

import homeassistant.util.dt as dt_util

from collections.abc import Mapping
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_SENSOR_TYPE,
    DOMAIN,
    CONF_WORKDAY_ENTITY,
    CONF_START_TIME_WORKDAY,
    CONF_START_TIME_WEEKEND,
    CONF_CLOSE_SUNSET_OFFSET,
)

from .coordinator import AdaptiveDataUpdateCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Adaptive Cover config entry."""

    name = config_entry.data["name"]
    coordinator: AdaptiveDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    sensor = AdaptiveCoverSensorEntity(
        config_entry.entry_id, hass, config_entry, name, coordinator
    )
    start = AdaptiveCoverTimeSensorEntity(
        config_entry.entry_id,
        hass,
        config_entry,
        name,
        "start",
        "mdi:sun-clock-outline",
        coordinator,
    )
    end = AdaptiveCoverTimeSensorEntity(
        config_entry.entry_id,
        hass,
        config_entry,
        name,
        "end",
        "mdi:sun-clock",
        coordinator,
    )
    control = AdaptiveCoverControlSensorEntity(
        config_entry.entry_id, hass, config_entry, name, coordinator
    )
    explain = AdaptiveCoverExplainSensorEntity(
        config_entry.entry_id, hass, config_entry, name, coordinator
    )
    reason = AdaptiveCoverStateReasonSensorEntity(
        config_entry.entry_id, hass, config_entry, name, coordinator
    )
    schedule = AdaptiveCoverScheduleSensorEntity(
        config_entry.entry_id, hass, config_entry, name, coordinator
    )
    async_add_entities([sensor, start, end, control, explain, reason, schedule])

class AdaptiveCoverSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover Sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:sun-compass"
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._attr_translation_key = "cover_position"
        self._attr_unique_id = f"{unique_id}_Cover Position"
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._device_name = self.type[self.config_entry.data[CONF_SENSOR_TYPE]]
        self._device_id = unique_id

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Handle when entity is added."""
        return self.data.states["state"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._name,
            model=self._device_name,
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:  # noqa: D102
        return self.data.attributes

class AdaptiveCoverTimeSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover Time Sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        key: str,
        icon: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self._attr_icon = icon
        self.key = key
        self._attr_translation_key = "start_sun" if key == "start" else "end_sun"
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._attr_unique_id = f"{unique_id}_Start Sun" if key == "start" else f"{unique_id}_End Sun"
        self._device_id = unique_id
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._cover_type = self.config_entry.data["sensor_type"]
        self._device_name = self.type[config_entry.data[CONF_SENSOR_TYPE]]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Handle when entity is added."""
        return self.data.states[self.key]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._name,
            model=self._device_name,
        )

class AdaptiveCoverControlSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover Control method Sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "control"

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._attr_unique_id = f"{unique_id}_Control Method"
        self._device_id = unique_id
        self.id = unique_id
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._cover_type = self.config_entry.data["sensor_type"]
        self._device_name = self.type[config_entry.data[CONF_SENSOR_TYPE]]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Handle when entity is added."""
        return self.data.states["control"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._name,
            model=self._device_name,
        )

class AdaptiveCoverExplainSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover Explanation Sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:text-box-search-outline"
    _attr_translation_key = "algorithm_status" # Tłumaczenia z plików językowych
    _attr_device_class = SensorDeviceClass.ENUM # Mówi HA, że to skończona lista wariantów
    _attr_options = [
        "auto", "dawn_protection", "rain_detected", "wind_detected",
        "cold_protection", "night_purge", "max_limit", "min_limit",
        "night_mode", "sun_shadow", "calculating", "window_open"
    ]

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._attr_unique_id = f"{unique_id}_explanation"
        self._device_id = unique_id
        self.id = unique_id
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._device_name = self.type[config_entry.data[CONF_SENSOR_TYPE]]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Fetch the explanation string."""
        return self.data.states.get("explanation", "calculating") # Default ENUM fallback

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._name,
            model=self._device_name,
        )

class AdaptiveCoverStateReasonSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover State Reason Sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:text-box-search"
    _attr_translation_key = "state_reason"

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._attr_unique_id = f"{unique_id}_state_reason"
        self._device_id = unique_id
        self.id = unique_id
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._device_name = self.type[config_entry.data[CONF_SENSOR_TYPE]]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Fetch the reason string."""
        return self.data.states.get("state_reason", "Działanie automatyczne")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._name,
            model=self._device_name,
        )

class AdaptiveCoverScheduleSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Sensor showing today's schedule."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:calendar-clock"
    _attr_translation_key = "schedule"

    def __init__(
        self, unique_id: str, hass, config_entry, name: str, coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize the schedule sensor."""
        super().__init__(coordinator=coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"{unique_id}_schedule"
        self.config_entry = config_entry
        self.hass = hass
        self._name = name
        self._device_id = unique_id
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self._device_name = self.type[config_entry.data[CONF_SENSOR_TYPE]]

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the schedule sensor state."""
        return "Aktywny"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._name,
            model=self._device_name,
        )

    @property
    def extra_state_attributes(self):
        """Return today's schedule details."""
        is_workday = True
        workday_entity = self.config_entry.options.get(CONF_WORKDAY_ENTITY)

        if workday_entity:
            state = self.hass.states.get(workday_entity)
            if state:
                is_workday = state.state == "on"

        start_w = self.config_entry.options.get(CONF_START_TIME_WORKDAY, "07:00:00")
        start_we = self.config_entry.options.get(CONF_START_TIME_WEEKEND, "09:00:00")
        offset = self.config_entry.options.get(CONF_CLOSE_SUNSET_OFFSET, 0)

        end_time_str = "Brak"
        if self.coordinator._end_time:
            local_end = dt_util.as_local(self.coordinator._end_time)
            end_time_str = local_end.strftime("%H:%M")

        return {
            "Dzisiaj dzień roboczy": "Tak" if is_workday else "Nie",
            "Godzina otwarcia (Dzisiaj)": start_w if is_workday else start_we,
            "Godzina zamknięcia (Dzisiaj)": end_time_str,
            "Przesunięcie zachodu (Minuty)": offset,
        }
