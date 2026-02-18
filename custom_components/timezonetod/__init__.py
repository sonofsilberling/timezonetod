"""The Time Zone Times of the Day integration."""

# /config/custom_components/timezonetod/__init__.py

from __future__ import annotations
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# List of supported platforms

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Timezone Time of Day from a config entry.
    
    This is the main entry point called by Home Assistant when the integration is loaded.
    It performs the following tasks:
    1. Registers an update listener to handle options changes
    2. Forwards the setup to all supported platforms (binary_sensor)
    
    The update listener ensures that when a user modifies the sensor's configuration
    through the options flow, the sensor is automatically reloaded with the new settings.
    
    Args:
        hass: The Home Assistant instance.
        entry: The config entry containing the sensor's configuration data.
        
    Returns:
        bool: True if setup was successful, False otherwise.
    """
    _LOGGER.debug("Setting up config entry: %s", entry.title)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    # This function tells Home Assistant to forward the setup process
    # to the 'binary_sensor' platform. It will then look for a
    # 'binary_sensor.py' file and call its 'async_setup_entry' function.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.
    
    Called when the integration is being removed or reloaded. This function ensures
    proper cleanup by unloading all platforms (binary_sensor) associated with this
    config entry.
    
    This is important for:
    - Removing the sensor from Home Assistant's state machine
    - Canceling any scheduled callbacks or timers
    - Freeing up resources
    
    Args:
        hass: The Home Assistant instance.
        entry: The config entry to unload.
        
    Returns:
        bool: True if unload was successful, False if any platform failed to unload.
    """
    _LOGGER.debug("Unloading config entry: %s", entry.title)
    
    # This unloads the platforms (e.g., your binary_sensor).
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the config entry.
    
    This function is called automatically when a user updates the sensor's configuration
    through the options flow. It triggers a full reload of the config entry, which:
    1. Unloads the existing sensor (calling async_unload_entry)
    2. Reloads the sensor with the updated configuration (calling async_setup_entry)
    
    This ensures that configuration changes take effect immediately without requiring
    a Home Assistant restart.
    
    Args:
        hass: The Home Assistant instance.
        entry: The config entry that was updated.
        
    Returns:
        None
    """
    await hass.config_entries.async_reload(entry.entry_id)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Timezone Time of Day component from YAML.
    
    This function handles the legacy YAML configuration by initiating a config flow
    import for each entry found under the integration's domain in configuration.yaml.
    
    Args:
        hass: The Home Assistant instance.
        config: The full configuration dictionary from configuration.yaml.
        
    Returns:
        bool: True if setup was initiated successfully.
    """
    if DOMAIN not in config:
        return True

    for entry_conf in config[DOMAIN]:
        # This triggers the 'async_step_import' in your config_flow.py
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data=entry_conf,
            )
        )

    return True    