"""Timezone Time of Day Sensor binary sensor for Home Assistant."""

from __future__ import annotations
import logging
import asyncio
from datetime import datetime, timedelta, date
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from .entity import TimezoneTodSensorCore
from homeassistant.const import CONF_NAME
from .const import (
    CONF_START_TIME,
    CONF_END_TIME,
    CONF_START_OFFSET,
    CONF_END_OFFSET,
    CONF_TIMEZONE,
    CONF_PARENT_ENTITY,
    CONF_IS_CHILD,
    CONF_START_REF,
    CONF_END_REF,
    ATTR_START_TIME_LOCAL,
    ATTR_END_TIME_LOCAL,
    ATTR_NEXT_UPDATE_LOCAL,
    ATTR_START_TIME_UTC,
    ATTR_END_TIME_UTC,
    ATTR_NEXT_UPDATE_UTC,
    ATTR_IS_CHILD,
    ATTR_PARENT_ENTITY,
    ATTR_TIMEZONE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the TimezoneTodSensor binary sensor entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry containing the sensor configuration.
        async_add_entities: The callback to add entities to the platform.
    """
    async_add_entities([TimezoneTodSensor(hass, entry)])


class TimezoneTodSensor(BinarySensorEntity):
    """The Home Assistant entity wrapper for the Timezone Time of Day Sensor.

    This class handles the integration with Home Assistant's state machine,
    managing timers, listeners, and attribute formatting.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor.

        Combines config entry data and options to initialize the core logic.
        The core logic is framework-agnostic and handles all time calculations,
        while this wrapper manages Home Assistant integration (state updates,
        timers, event listeners).
        
        Configuration values from entry.options take precedence over entry.data,
        allowing users to update settings through the options flow.

        Args:
            hass: The Home Assistant instance.
            entry: The config entry providing data and options.
        """
        self.hass = hass
        self.entry = entry

        # Merge data and options (options override data)
        conf = {**entry.data, **entry.options}

        self._core = TimezoneTodSensorCore(
            name=conf[CONF_NAME],
            is_child=conf.get(CONF_IS_CHILD, False),
            start_time=conf.get(CONF_START_TIME),
            end_time=conf.get(CONF_END_TIME),
            start_offset=timedelta(seconds=conf.get(CONF_START_OFFSET, 0)),
            end_offset=timedelta(seconds=conf.get(CONF_END_OFFSET, 0)),
            timezone_str=conf.get(CONF_TIMEZONE),
            parent_entity_id=conf.get(CONF_PARENT_ENTITY),
            start_ref=conf.get(CONF_START_REF, "start"),
            end_ref=conf.get(CONF_END_REF, "end"),
        )

        self._attr_name = self._core.name
        self._attr_unique_id = entry.entry_id
        self._unsub_update = None
        self._unsub_debounce = None
        
        # Cache icon-relevant config to avoid repeated dict merging
        self._conf_start_time = conf.get(CONF_START_TIME, "")
        self._conf_end_time = conf.get(CONF_END_TIME, "")

    @property
    def is_on(self) -> bool:
        """Return True if the sensor is currently active.

        Returns:
            bool: The active state determined by the core logic.
        """
        return self._core.is_on(dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes of the sensor.

        Provides detailed timing information in both local and UTC timezones,
        which is useful for:
        - Debugging sensor behavior
        - Creating automation templates
        - Displaying timing information in the UI
        
        Returns None if boundaries haven't been calculated yet (e.g., during
        initial setup or if parent sensor is not available).

        Returns:
            dict[str, Any] | None: Attribute dictionary with timing info, or None if not yet calculated.
        """
        if (
            not self._core.calculated_start_utc
            or not self._core.calculated_end_utc
            or not self._core.next_update_utc
        ):
            return None

        local_tz = dt_util.get_default_time_zone()

        return {
            ATTR_START_TIME_LOCAL: self._core.calculated_start_utc.astimezone(
                local_tz
            ).isoformat(),
            ATTR_END_TIME_LOCAL: self._core.calculated_end_utc.astimezone(
                local_tz
            ).isoformat(),
            ATTR_NEXT_UPDATE_LOCAL: self._core.next_update_utc.astimezone(
                local_tz
            ).isoformat(),
            ATTR_START_TIME_UTC: self._core.calculated_start_utc.isoformat(),
            ATTR_END_TIME_UTC: self._core.calculated_end_utc.isoformat(),
            ATTR_NEXT_UPDATE_UTC: self._core.next_update_utc.isoformat(),
            ATTR_IS_CHILD: self._core.is_child,
            ATTR_PARENT_ENTITY: self._core.parent_entity_id or "No Parent",
            ATTR_TIMEZONE: self._core.timezone_name or "Default (System)",
        }

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend based on configuration and state.
        
        Icon selection logic:
        - Child sensors: clock-check (on) / clock-edit-outline (off)
        - Solar sensors (sunrise/sunset): weather-sunny (on) / weather-night (off)
        - Time-based sensors: clock (on) / clock-outline (off)

        Returns:
            str: MDI icon string.
        """
        is_on = self.is_on

        if self._core.is_child:
            return "mdi:clock-check" if is_on else "mdi:clock-edit-outline"

        if any(event in (self._conf_start_time, self._conf_end_time) for event in ("sunrise", "sunset")):
            return "mdi:weather-sunny" if is_on else "mdi:weather-night"

        return "mdi:clock" if is_on else "mdi:clock-outline"

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity being removed from Home Assistant.

        Called when the sensor is being removed from HA, either because:
        - The integration is being unloaded
        - The config entry is being deleted
        - Home Assistant is shutting down
        
        Ensures proper cleanup by canceling any pending timer callbacks
        to prevent orphaned tasks or memory leaks.
        """
        await super().async_will_remove_from_hass()
        self._cancel_timer()

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant.

        Called when the sensor is first added to HA. This method:
        1. Registers cleanup callbacks for proper shutdown
        2. Sets up state change listeners for child sensors to track their parent
        3. Performs the initial boundary calculation and schedules the first update
        
        For child sensors, a state change listener is registered to monitor the
        parent entity and trigger updates when the parent's boundaries change.
        """
        await super().async_added_to_hass()

        # Track timer for cleanup on removal
        self.async_on_remove(self._cancel_timer)

        if self._core.is_child:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._core.parent_entity_id], self._handle_parent_update
                )
            )

        await self._update_and_reschedule()

    @callback
    def _handle_parent_update(self, _event: Event) -> None:
        """Callback for parent entity changes with debounce logic.
        
        This callback is triggered whenever the parent entity's state changes.
        To avoid excessive recalculations when the parent updates multiple times
        in quick succession (e.g., during initialization), a 0.1 second debounce
        is applied. Each new parent update cancels the previous pending update
        and schedules a new one.

        Args:
            _event: The state change event from the parent entity (unused).
        """
        _LOGGER.debug(
            "%s: Parent %s changed, scheduling debounced update.",
            self.name,
            self._core.parent_entity_id,
        )
        if self._unsub_debounce:
            self._unsub_debounce()
        self._unsub_debounce = async_call_later(
            self.hass, 0.1, self._scheduled_update
        )

    def _cancel_timer(self) -> None:
        """Cancel any pending scheduled update timer.
        
        This method is called during cleanup to prevent orphaned callbacks.
        It safely cancels the timer subscription if one exists and clears
        the reference to prevent double-cancellation.
        
        This is important for:
        - Proper shutdown when the sensor is removed
        - Preventing duplicate timers when rescheduling updates
        - Avoiding memory leaks from uncanceled callbacks
        """
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

    @callback
    def _scheduled_update(self, _now: datetime) -> None:
        """Callback for the scheduled point-in-time transition.
        
        This callback is invoked by Home Assistant's event loop at the exact
        time when the sensor should transition state (either turn on or off).
        It creates an async task to perform the boundary recalculation and
        state update.

        Args:
            _now: The current time provided by the timer event (unused, we use utcnow()).
        """
        self.hass.async_create_task(self._update_and_reschedule())

    async def _update_and_reschedule(self) -> None:
        """The main calculation loop.

        This is the core update method that:
        1. Gathers required data (current time, parent attributes for child sensors)
        2. Calls the core logic to recalculate time boundaries
        3. Updates the sensor's state in Home Assistant
        4. Schedules the next update at the calculated transition time
        
        For child sensors, this method validates that the parent entity exists
        and has the required UTC time attributes before proceeding. If the parent
        is not ready, the update is skipped (it will be retried when the parent
        updates).
        
        For root sensors, this method provides a sun event callback to resolve
        sunrise/sunset times if configured.
        """
        now_utc = dt_util.utcnow()
        parent_attrs = None

        if self._core.is_child:
            parent_state = self.hass.states.get(self._core.parent_entity_id)
            if not parent_state:
                _LOGGER.debug(
                    "%s: Parent %s not yet available.",
                    self.name,
                    self._core.parent_entity_id,
                )
                return

            if ATTR_START_TIME_UTC not in parent_state.attributes:
                _LOGGER.debug(
                    "%s: Parent %s has no UTC attributes yet.",
                    self.name,
                    self._core.parent_entity_id,
                )
                return

            parent_attrs = parent_state.attributes

        def get_sun_dt(event: str, target_date: date) -> datetime | None:
            """Wrapper for Home Assistant sun event calculation.
            
            Provides a simple interface for the core logic to request sunrise/sunset
            times without depending on Home Assistant directly. This maintains the
            separation between the framework-agnostic core and the HA integration.

            Args:
                event: Solar event name ('sunrise' or 'sunset').
                target_date: The date for which to calculate the event.

            Returns:
                datetime | None: The UTC datetime of the event or None if calculation failed.
            """
            return get_astral_event_date(self.hass, event, target_date)

        success = self._core.update_boundaries(
            now_utc=now_utc,
            default_timezone=dt_util.get_default_time_zone(),
            sun_event_callback=get_sun_dt,
            parent_attributes=parent_attrs,
        )

        if not success:
            _LOGGER.debug("Failed to calculate boundaries for %s", self.name)
            return

        self.async_write_ha_state()

        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

        if self._core.next_update_utc:
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, self._scheduled_update, self._core.next_update_utc
            )
