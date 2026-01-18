# binary_sensor.py

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
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from .entity import TimezoneTodSensorCore
from .const import (
    CONF_NAME,
    CONF_START_TIME,
    CONF_END_TIME,
    CONF_START_OFFSET,
    CONF_END_OFFSET,
    CONF_TIMEZONE,
    CONF_PARENT_ENTITY,
    CONF_IS_CHILD,
    ATTR_START_TIME_LOCAL,
    ATTR_END_TIME_LOCAL,
    ATTR_NEXT_UPDATE_LOCAL,
    ATTR_START_TIME_UTC,
    ATTR_END_TIME_UTC,
    ATTR_NEXT_UPDATE_UTC,
    ATTR_IS_CHILD,
    ATTR_PARENT_ENTITY,
    ATTR_TIMEZONE,
    CONF_START_REF,
    CONF_END_REF,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the TimezoneTodSensor binary sensor entry."""
    async_add_entities([TimezoneTodSensor(hass, entry)])


class TimezoneTodSensor(BinarySensorEntity):
    """The Home Assistant entity wrapper for the Timezone Time of Day Sensor."""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self.entry = entry

        # Merge data and options
        conf = {**entry.data, **entry.options}

        self._core = TimezoneTodSensorCore(
            name=conf[CONF_NAME],
            is_child=conf.get(CONF_IS_CHILD, False),
            start_time=conf.get(CONF_START_TIME),
            end_time=conf.get(CONF_END_TIME),
            start_offset=timedelta(seconds=conf.get(CONF_START_OFFSET, 0)),
            end_offset=timedelta(seconds=conf.get(CONF_END_OFFSET, 0)),
            start_ref=conf.get(CONF_START_REF, "start"),
            end_ref=conf.get(CONF_END_REF, "end"),
            timezone_str=conf.get(CONF_TIMEZONE),
            parent_entity_id=conf.get(CONF_PARENT_ENTITY),
        )

        self._attr_name = self._core.name
        self._attr_unique_id = entry.entry_id
        self._unsub_update = None

    @property
    def is_on(self) -> bool:
        """Return True if the sensor is on."""
        return self._core.is_on(dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes of the sensor."""
        if not self._core.calculated_start_utc or not self._core.calculated_end_utc:
            return None

        # Convert to the default local timezone for user-friendly display
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
            ATTR_PARENT_ENTITY: self._core.parent_entity_id,
            ATTR_TIMEZONE: self._core.timezone_name or "Default (System)",
        }

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        # 1. Child Sensor Icon
        if self._core.is_child:
            return "mdi:clock-edit-outline"  # "Edit" implies an adjustment/offset to a parent

        # 2. Sun-based Sensor Icon
        # Check if either start or end is a sun event
        conf = {**self.entry.data, **self.entry.options}
        start = conf.get(CONF_START_TIME, "")
        end = conf.get(CONF_END_TIME, "")

        if any(event in (start, end) for event in ("sunrise", "sunset")):
            return "mdi:sun-clock"

        # 3. Default Time-based Sensor Icon
        return "mdi:clock-outline"

    async def async_added_to_hass(self) -> None:
        """Handle entity which is added to Home Assistant."""
        await super().async_added_to_hass()

        if self._core.is_child:
            # Listen to parent state changes
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._core.parent_entity_id], self._handle_parent_update
                )
            )

        # Initial calculation
        await self._update_and_reschedule()

    @callback
    def _handle_parent_update(self, event: Event) -> None:
        """Callback for parent entity changes."""
        _LOGGER.debug(
            "%s: Parent %s changed, scheduling debounced update.",
            self.name,
            self._core.parent_entity_id,
        )
        # Check if the event actually contains a state change (not just attributes)
        # but in our case, we usually WANT to trigger on attribute changes.

        # We use async_create_task to run our debounced update
        self.hass.async_create_task(self._debounced_update())

    async def _debounced_update(self) -> None:
        """Wait for the state machine to settle and then update."""
        # 100ms is usually enough for the parent's write to finish and propagate
        await asyncio.sleep(0.1)
        await self._update_and_reschedule()

    @callback
    def _scheduled_update(self, _now: datetime) -> None:
        """Callback for the scheduled point-in-time transition."""
        self.hass.async_create_task(self._update_and_reschedule())

    async def _update_and_reschedule(self) -> None:
        """Main calculation loop."""
        now_utc = dt_util.utcnow()
        parent_attrs = None

        # 1. Gather Parent Data if child
        if self._core.is_child:
            parent_state = self.hass.states.get(self._core.parent_entity_id)
            # GUARD: Ensure parent exists and has the required attributes
            if not parent_state:
                _LOGGER.debug(
                    "%s: Parent %s not yet available.",
                    self.name,
                    self._core.parent_entity_id,
                )
                return

            # GUARD: Check for our specific UTC attributes
            if ATTR_START_TIME_UTC not in parent_state.attributes:
                _LOGGER.debug(
                    "%s: Parent %s has no UTC attributes yet.",
                    self.name,
                    self._core.parent_entity_id,
                )
                # If the parent is a timezonetod sensor, it might still be calculating.
                # We stop here; when the parent finishes, it will trigger another event.
                return

            parent_attrs = parent_state.attributes

        # 2. Setup Sun Callback
        # We wrap HA's get_astral_event_date to match the Core's signature
        def get_sun_dt(event: str, target_date: date) -> datetime | None:
            return get_astral_event_date(self.hass, event, target_date)

        # 3. Update Core Logic
        success = self._core.update_boundaries(
            now_utc=now_utc,
            default_timezone=dt_util.get_default_time_zone(),
            sun_event_callback=get_sun_dt,
            parent_attributes=parent_attrs,
        )

        if not success:
            _LOGGER.error("Failed to calculate boundaries for %s", self.name)
            return

        # 4. Finalize HA State
        self.async_write_ha_state()

        # 5. Handle Timer
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

        if self._core.next_update_utc:
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, self._scheduled_update, self._core.next_update_utc
            )
