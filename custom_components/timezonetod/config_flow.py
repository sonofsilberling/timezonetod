"""Config flow for Times of the Day integration."""

from __future__ import annotations
import logging
import zoneinfo
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

# Selectors
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from .const import (
    DOMAIN,
    CONF_IS_CHILD,
    CONF_PARENT_ENTITY,
    CONF_START_TIME,
    CONF_END_TIME,
    CONF_START_OFFSET,
    CONF_END_OFFSET,
    CONF_TIMEZONE,
    CONF_START_REF,
    CONF_END_REF,
    REF_START,
    REF_END,
    ATTR_IS_CHILD,
)

_LOGGER = logging.getLogger(__name__)

_TIMEZONES: list[str] | None = None

def _get_timezones() -> list[str]:
    """Get the list of available timezones.
    
    Lazily loads and caches the list of IANA timezones from the zoneinfo module.
    The list is sorted alphabetically for easier selection in the UI.
    
    Returns:
        list[str]: Sorted list of timezone names (e.g., 'America/New_York', 'UTC').
    """
    global _TIMEZONES
    if _TIMEZONES is None:
        _TIMEZONES = sorted(zoneinfo.available_timezones())
    return _TIMEZONES

# Helper for validation
def validate_time_format(value: str) -> bool:
    """Validate that a time string is in an acceptable format.
    
    Accepts three formats:
    - 'sunrise': Solar sunrise event
    - 'sunset': Solar sunset event  
    - HH:MM:SS or HH:MM: Standard time format (parsed by dt_util.parse_time)
    
    Args:
        value: The time string to validate.
        
    Returns:
        bool: True if the format is valid, False otherwise.
    """
    if value in ("sunrise", "sunset"):
        return True
    return dt_util.parse_time(value) is not None

async def _get_valid_parents(hass):
    """Fetch valid parent entities for child sensors.
    
    Retrieves all entities from this integration that are root sensors (not children)
    and formats them for display in a selector dropdown. Only root sensors can be
    parents since child sensors cannot have their own children.
    
    Args:
        hass: The Home Assistant instance.
        
    Returns:
        list[dict]: List of options with 'value' (entity_id) and 'label' (friendly name)
                    suitable for use in a SelectSelector.
    """
    registry = er.async_get(hass)
    options = []
    for entry in registry.entities.values():
        if entry.platform == DOMAIN:
            state = hass.states.get(entry.entity_id)
            if state and state.attributes.get(ATTR_IS_CHILD) is False:
                label = state.attributes.get('friendly_name') or entry.entity_id
                options.append({'value': entry.entity_id, 'label': label})
    return options

class TimezoneTodConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for the Timezone Time of Day sensor."""

    def __init__(self):
        """Initialize the config flow.
        
        Sets up an empty data dictionary to accumulate configuration values
        across multiple steps of the flow (user -> root/child -> create entry).
        """
        self._data = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user step: sensor identity and type selection.
        
        This is the first step in the configuration flow where the user provides:
        - A unique name for the sensor
        - Whether it's a root sensor (standalone) or child sensor (dependent)
        
        The flow validates that no sensor with the same name already exists,
        then routes to either async_step_root or async_step_child based on
        the is_child flag.
        
        Args:
            user_input: Dictionary containing CONF_NAME and CONF_IS_CHILD, or None
                       if this is the first display of the form.
                       
        Returns:
            FlowResult: Either a form to display or a redirect to the next step.
        """
        errors: dict[str, str] = {}
        _LOGGER.debug("Starting step user")

        # """Step 1: Basic Identity."""
        if user_input is not None:
            # Check if a sensor with this name already exists
            name = user_input[CONF_NAME]
            for entry in self._async_current_entries():
                if entry.data.get(CONF_NAME) == name:
                    return self.async_abort(reason="already_configured")
            
            self._data.update(user_input)
            if user_input.get(CONF_IS_CHILD):
                return await self.async_step_child()
            return await self.async_step_root()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Optional(CONF_IS_CHILD, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_root(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure a root sensor's schedule and timezone.
        
        Root sensors define their own time boundaries using:
        - Start time: HH:MM:SS format or 'sunrise'/'sunset'
        - End time: HH:MM:SS format or 'sunrise'/'sunset'
        - Timezone: IANA timezone string (defaults to system timezone)
        
        The times are validated using validate_time_format(). If validation passes,
        the config entry is created with all accumulated data from previous steps.
        
        Args:
            user_input: Dictionary containing CONF_START_TIME, CONF_END_TIME, and
                       optionally CONF_TIMEZONE, or None for initial form display.
                       
        Returns:
            FlowResult: Either a form with errors or a created config entry.
        """
        errors = {}
        _LOGGER.debug("Starting step root")
        if user_input is not None:
            # Validate the time inputs
            if not validate_time_format(user_input[CONF_START_TIME]):
                errors[CONF_START_TIME] = "invalid_time_format"
            if not validate_time_format(user_input[CONF_END_TIME]):
                errors[CONF_END_TIME] = "invalid_time_format"

            if not errors:
                self._data.update(user_input)
                return self.async_create_entry(
                    title=self._data[CONF_NAME], data=self._data
                )

        # Build a sorted list of timezones for the selector
        get_timezones = _get_timezones()

        _LOGGER.debug("Got timezones")

        root_schema = vol.Schema(
            {
                vol.Required(CONF_START_TIME): TextSelector(
                    TextSelectorConfig(autocomplete="HH:MM:SS or 'sunrise'/'sunset'")
                ),
                vol.Required(CONF_END_TIME): TextSelector(
                    TextSelectorConfig(autocomplete="HH:MM:SS or 'sunrise'/'sunset'")
                ),
                vol.Optional(
                    CONF_TIMEZONE, default=self.hass.config.time_zone
                ): SelectSelector(
                    SelectSelectorConfig(
                        multiple=False,
                        options=get_timezones,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        _LOGGER.debug("Setup root schema")

        return self.async_show_form(
            step_id="root", data_schema=root_schema, errors=errors
        )

    async def async_step_child(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure a child sensor's parent relationship and time offsets.
        
        Child sensors inherit their time boundaries from a parent root sensor,
        but can apply relative offsets. Configuration includes:
        - Parent entity: Must be a root sensor from this integration
        - Start reference: Whether child start relates to parent's start or end
        - Start offset: Seconds to add/subtract from the reference point
        - End reference: Whether child end relates to parent's start or end  
        - End offset: Seconds to add/subtract from the reference point
        
        This allows creating sensors like "30 minutes before parent ends" or
        "1 hour after parent starts".
        
        Args:
            user_input: Dictionary containing parent entity and offset configuration,
                       or None for initial form display.
                       
        Returns:
            FlowResult: Either a form to display or a created config entry.
        """
        _LOGGER.debug("Starting step child")
        ref_selector = SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": REF_START, "label": "Parent Start"},
                    {"value": REF_END, "label": "Parent End"},
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        valid_parents = await _get_valid_parents(self.hass)
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        child_schema = vol.Schema(
            {
                vol.Required(CONF_PARENT_ENTITY): SelectSelector(
                    SelectSelectorConfig(
                        options=valid_parents, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(CONF_START_REF, default=REF_START): ref_selector,
                vol.Required(CONF_START_OFFSET, default=0): NumberSelector(
                    NumberSelectorConfig(
                        mode=NumberSelectorMode.BOX, unit_of_measurement="seconds"
                    )
                ),
                vol.Required(CONF_END_REF, default=REF_END): ref_selector,
                vol.Required(CONF_END_OFFSET, default=0): NumberSelector(
                    NumberSelectorConfig(
                        mode=NumberSelectorMode.BOX, unit_of_measurement="seconds"
                    )
                ),
            }
        )

        return self.async_show_form(step_id="child", data_schema=child_schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TimezoneTodOptionsFlow:
        """Create an options flow handler for this config entry.
        
        Called by Home Assistant when the user wants to edit an existing sensor's
        configuration. Returns an instance of TimezoneTodOptionsFlow to handle
        the options editing process.
        
        Args:
            config_entry: The existing config entry to be edited.
            
        Returns:
            TimezoneTodOptionsFlow: The options flow handler instance.
        """


class TimezoneTodOptionsFlow(config_entries.OptionsFlow):
    """Options flow to allow editing the sensor after creation.
    
    Provides a UI for users to modify an existing sensor's configuration without
    deleting and recreating it. The available options depend on whether the sensor
    is a root sensor (time/timezone settings) or child sensor (parent/offset settings).
    
    The sensor's type (root vs child) cannot be changed after creation.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the options flow initialization step.
        
        Presents a form with fields appropriate to the sensor type:
        - Root sensors: Can edit start_time, end_time, and timezone
        - Child sensors: Can edit parent_entity, offsets, and reference points
        
        The form is pre-populated with current values from the config entry's
        data and options (options override data). Validation is applied to time
        formats for root sensors.
        
        Args:
            user_input: Dictionary containing updated configuration values, or None
                       for initial form display.
                       
        Returns:
            FlowResult: Either a form with current values/errors or an updated entry.
        """
        errors = {}
        current_config = {**self.config_entry.data, **self.config_entry.options}
        ref_selector = SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": REF_START, "label": "Parent Start"},
                    {"value": REF_END, "label": "Parent End"},
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        if user_input is not None:
            # Apply same validation as Config Flow
            if not current_config.get(CONF_IS_CHILD):
                if not validate_time_format(user_input[CONF_START_TIME]):
                    errors[CONF_START_TIME] = "invalid_time_format"
                if not validate_time_format(user_input[CONF_END_TIME]):
                    errors[CONF_END_TIME] = "invalid_time_format"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        is_child = current_config.get(CONF_IS_CHILD, False)

        get_timezones = _get_timezones()

        if is_child:
            valid_parents = await _get_valid_parents(self.hass)
            schema = vol.Schema(
                {
                    vol.Required(CONF_PARENT_ENTITY): SelectSelector(
                        SelectSelectorConfig(
                            options=valid_parents, mode=SelectSelectorMode.DROPDOWN
                        )
                    ),
                    vol.Required(
                        CONF_START_REF,
                        default=current_config.get(CONF_START_REF, REF_START),
                    ): ref_selector,
                    vol.Required(
                        CONF_START_OFFSET,
                        default=current_config.get(CONF_START_OFFSET, 0),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            mode=NumberSelectorMode.BOX, unit_of_measurement="seconds"
                        )
                    ),
                    vol.Required(
                        CONF_END_REF,
                        default=current_config.get(CONF_END_REF, REF_END),
                    ): ref_selector,
                    vol.Required(
                        CONF_END_OFFSET,
                        default=current_config.get(CONF_END_OFFSET, 0),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            mode=NumberSelectorMode.BOX, unit_of_measurement="seconds"
                        )
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_START_TIME,
                        default=current_config.get(CONF_START_TIME),
                    ): TextSelector(),
                    vol.Required(
                        CONF_END_TIME, default=current_config.get(CONF_END_TIME)
                    ): TextSelector(),
                    vol.Optional(
                        CONF_TIMEZONE, default=current_config.get(CONF_TIMEZONE)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=get_timezones,
                            sort=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
