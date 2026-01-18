"""Config flow for Times of the Day integration."""

from __future__ import annotations
import logging
import zoneinfo
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import Platform, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.util import dt as dt_util

# Selectors
from homeassistant.helpers.selector import (
    # EntitySelector,
    # EntitySelectorConfig,
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


# Helper for validation
def validate_time_format(value: str) -> bool:
    """Check if the string is 'sunrise', 'sunset', or a valid HH:MM:SS."""
    if value in ("sunrise", "sunset"):
        return True
    return dt_util.parse_time(value) is not None


class TimezoneTodConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for the Timezone Time of Day sensor."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    async def _get_valid_parents(self):
        """Fetch entities from this integration that are not children."""
        states = self.hass.states.async_all()
        options = []

        for state in states:
            # Check if the entity belongs to our domain
            # and if it has the ATTR_IS_CHILD attribute set to False
            if state.entity_id.startswith("binary_sensor."):
                is_child = state.attributes.get(ATTR_IS_CHILD)
                # Only include if it's explicitly not a child (or lacks the attr)
                if is_child is False:
                    label = state.attributes.get("friendly_name") or state.entity_id
                    options.append({"value": state.entity_id, "label": label})

        return options

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}
        _LOGGER.info("Starting step user")

        """Step 1: Basic Identity."""
        if user_input is not None:
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
        """Step 2 (Root): Configure Time and Timezone."""
        errors = {}
        _LOGGER.info("Starting step root")
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

        # Build a list of timezones for the selector
        get_timezones: list[str] = list(
            await self.hass.async_add_executor_job(zoneinfo.available_timezones)
        )

        _LOGGER.info("Got timezones")

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
                        sort=True,
                    )
                ),
            }
        )

        _LOGGER.info("Setup root schema")

        return self.async_show_form(
            step_id="root", data_schema=root_schema, errors=errors
        )

    async def async_step_child(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 (Child): Configure Parent and Offsets."""
        _LOGGER.info("Starting step child")
        ref_selector = SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": REF_START, "label": "Parent Start"},
                    {"value": REF_END, "label": "Parent End"},
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        valid_parents = await self._get_valid_parents()
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
        return TimezoneTodOptionsFlow()


class TimezoneTodOptionsFlow(config_entries.OptionsFlow):
    """Options flow to allow editing the sensor after creation."""

    VERSION = 1    

    # def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
    #     self.config_entry = config_entry
    async def _get_valid_parents(self):
        """Fetch entities from this integration that are not children."""
        states = self.hass.states.async_all()
        options = []

        for state in states:
            # Check if the entity belongs to our domain
            # and if it has the ATTR_IS_CHILD attribute set to False
            if state.entity_id.startswith("binary_sensor."):
                is_child = state.attributes.get(ATTR_IS_CHILD)
                # Only include if it's explicitly not a child (or lacks the attr)
                if is_child is False:
                    label = state.attributes.get("friendly_name") or state.entity_id
                    options.append({"value": state.entity_id, "label": label})

        return options

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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

        get_timezones: list[str] = list(
            await self.hass.async_add_executor_job(zoneinfo.available_timezones)
        )

        if is_child:
            valid_parents = await self._get_valid_parents()
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