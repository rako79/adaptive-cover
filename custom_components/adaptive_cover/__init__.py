"""The Adaptive Cover integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import (
    async_track_state_change_event,
)
import homeassistant.helpers.config_validation as cv
import json
import os
import voluptuous as vol

from .const import (
    CONF_END_ENTITY,
    CONF_ENTITIES,
    CONF_PRESENCE_ENTITY,
    CONF_TEMP_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_ENTITY,
    CONF_RAIN_ENTITY,
    CONF_WIND_ENTITY,
    DOMAIN,
    _LOGGER,
)
from .coordinator import AdaptiveDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SELECT, Platform.TIME, Platform.NUMBER]
CONF_SUN = ["sun.sun"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Adaptive Cover component."""

    async def export_config(call: ServiceCall) -> None:
        """Export all config entries to a JSON file."""
        filename = call.data.get("filename", "adaptive_cover_settings.json")
        filepath = hass.config.path(filename)
        
        export_data = {}
        for entry in hass.config_entries.async_entries(DOMAIN):
            export_data[entry.entry_id] = {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            }
            
        def write_file():
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=4)
                
        await hass.async_add_executor_job(write_file)
        _LOGGER.info("Exported Adaptive Cover configuration to %s", filepath)

    async def import_config(call: ServiceCall) -> None:
        """Import config entries from a JSON file."""
        filename = call.data.get("filename", "adaptive_cover_settings.json")
        filepath = hass.config.path(filename)
        
        def read_file():
            if not os.path.exists(filepath):
                return None
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
                
        import_data = await hass.async_add_executor_job(read_file)
        
        if import_data is None:
            _LOGGER.error("Import file not found: %s", filepath)
            return
            
        for entry in hass.config_entries.async_entries(DOMAIN):
            # Znajdź dane w pliku importu pasujące po nazwie (title) zamiast po entry_id
            matched_data = None
            for stored_id, stored_data in import_data.items():
                if stored_data.get("title") == entry.title:
                    matched_data = stored_data
                    break
                    
            if matched_data:
                hass.config_entries.async_update_entry(
                    entry, 
                    data=matched_data.get("data", entry.data),
                    options=matched_data.get("options", entry.options)
                )
        _LOGGER.info("Imported Adaptive Cover configuration from %s", filepath)

    hass.services.async_register(
        DOMAIN, 
        "export_config", 
        export_config,
        schema=vol.Schema({
            vol.Optional("filename", default="adaptive_cover_settings.json"): cv.string,
        })
    )

    hass.services.async_register(
        DOMAIN, 
        "import_config", 
        import_config,
        schema=vol.Schema({
            vol.Optional("filename", default="adaptive_cover_settings.json"): cv.string,
        })
    )

    return True

async def async_initialize_integration(
    hass: HomeAssistant,
    config_entry: ConfigEntry | None = None,
) -> bool:
    """Initialize the integration."""

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Adaptive Cover from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    coordinator = AdaptiveDataUpdateCoordinator(hass)
    _temp_entity = entry.options.get(CONF_TEMP_ENTITY)
    _presence_entity = entry.options.get(CONF_PRESENCE_ENTITY)
    _weather_entity = entry.options.get(CONF_WEATHER_ENTITY)
    _cover_entities = entry.options.get(CONF_ENTITIES, [])
    _end_time_entity = entry.options.get(CONF_END_ENTITY)
    _window_entity = entry.options.get(CONF_WINDOW_ENTITY)
    
    # --- NOWE ENCJE ---
    _rain_entity = entry.options.get(CONF_RAIN_ENTITY)
    _wind_entity = entry.options.get(CONF_WIND_ENTITY)
    # ------------------
    
    _entities = ["sun.sun"]
    
    # --- DODANE NOWE ENCJE NA KONIEC TEJ LISTY ---
    for entity in [_temp_entity, _presence_entity, _weather_entity, _end_time_entity, _window_entity, _rain_entity, _wind_entity]:
        if entity is not None:
            _entities.append(entity)

    _LOGGER.debug("Setting up entry %s", entry.data.get("name"))

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            _entities,
            coordinator.async_check_entity_state_change,
        )
    )

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            _cover_entities,
            coordinator.async_check_cover_state_change,
        )
    )

    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
