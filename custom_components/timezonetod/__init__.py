"""The Time Zone Times of the Day integration."""

# /config/custom_components/timezonetod/__init__.py

from __future__ import annotations
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# List of supported he platforms

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Timezone Time of Day from a config entry."""
    _LOGGER.debug("Setting up config entry: %s", entry.title)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    # This function tells Home Assistant to forward the setup process
    # to the 'binary_sensor' platform. It will then look for a
    # 'binary_sensor.py' file and call its 'async_setup_entry' function.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry: %s", entry.title)
    
    # This unloads the platforms (e.g., your binary_sensor).
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)