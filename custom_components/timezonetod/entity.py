"""Core Logic for Timezone Time of Day Sensor"""

from __future__ import annotations
from datetime import time, timedelta, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any
from collections.abc import Callable


class TimezoneTodSensorCore:
    """Core logic for the Timezone Time of Day sensor.

    This class provides framework-agnostic logic for calculating time-of-day
    boundaries, making it suitable for both Home Assistant and independent unit testing.
    It supports root sensors (fixed/solar) and child sensors (relational to parent).
    """

    def __init__(
        self,
        name: str,
        *,
        is_child: bool = False,
        start_time: str | None = None,
        end_time: str | None = None,
        start_offset: timedelta | None = None,
        end_offset: timedelta | None = None,
        timezone_str: str | None = None,
        parent_entity_id: str | None = None,
        start_ref: str | None = "start",
        end_ref: str | None = "end",
    ) -> None:
        """Initialize the core Time of Day sensor logic.
        
        This constructor sets up the sensor's configuration and initializes the
        calculated boundary timestamps to None. The sensor can operate in two modes:
        
        **Root Mode** (is_child=False):
        - Uses start_time, end_time, and timezone_str to define boundaries
        - Times can be fixed (HH:MM:SS) or solar events (sunrise/sunset)
        - Offsets are applied to the configured times
        
        **Child Mode** (is_child=True):
        - Inherits boundaries from parent_entity_id
        - Uses start_ref/end_ref to determine which parent boundary to reference
        - Applies offsets relative to the parent's boundaries
        
        Args:
            name: Human-readable name of the sensor.
            is_child: True if this sensor inherits boundaries from a parent.
            start_time: Start time string (HH:MM:SS or 'sunrise'/'sunset'). Required for root sensors.
            end_time: End time string (HH:MM:SS or 'sunrise'/'sunset'). Required for root sensors.
            start_offset: Timedelta to offset the start time. Defaults to zero.
            end_offset: Timedelta to offset the end time. Defaults to zero.
            timezone_str: IANA timezone string (e.g., 'UTC' or 'Europe/London'). Optional for root sensors.
            parent_entity_id: The entity ID of the parent sensor. Required if is_child is True.
            start_ref: Whether child start relates to parent 'start' or 'end'. Defaults to 'start'.
            end_ref: Whether child end relates to parent 'start' or 'end'. Defaults to 'end'.
        """
        self._name = name
        self._is_child = is_child
        self._configured_start = start_time
        self._configured_end = end_time
        self._start_offset = start_offset or timedelta(0)
        self._end_offset = end_offset or timedelta(0)
        self._start_ref = start_ref
        self._end_ref = end_ref
        self._configured_timezone_str = timezone_str
        self._resolved_timezone_str = timezone_str
        self._parent_entity_id = parent_entity_id

        self._calculated_start_utc: datetime | None = None
        self._calculated_end_utc: datetime | None = None
        self._next_update_utc: datetime | None = None

    @property
    def name(self) -> str:
        """Return the sensor name.
        
        Returns:
            str: The human-readable name provided during initialization.
        """
        return self._name

    @property
    def is_child(self) -> bool:
        """Return True if this is a child sensor.
        
        Child sensors derive their boundaries from a parent sensor rather than
        defining their own schedule.
        
        Returns:
            bool: True if this sensor is a child, False if it's a root sensor.
        """
        return self._is_child

    @property
    def calculated_start_utc(self) -> datetime | None:
        """Return the calculated start time in UTC.
        
        This is the actual start boundary computed by update_boundaries(),
        including any applied offsets. Returns None if boundaries haven't
        been calculated yet.
        
        Returns:
            datetime | None: The start time in UTC, or None if not yet calculated.
        """
        return self._calculated_start_utc

    @property
    def calculated_end_utc(self) -> datetime | None:
        """Return the calculated end time in UTC.
        
        This is the actual end boundary computed by update_boundaries(),
        including any applied offsets. Returns None if boundaries haven't
        been calculated yet.
        
        Returns:
            datetime | None: The end time in UTC, or None if not yet calculated.
        """
        return self._calculated_end_utc

    @property
    def next_update_utc(self) -> datetime | None:
        """Return the timestamp for the next scheduled state transition.
        
        This is when the sensor will next change state (either turning on or off).
        Used by the Home Assistant wrapper to schedule the next update callback.
        
        Returns:
            datetime | None: The next transition time in UTC, or None if not calculated.
        """
        return self._next_update_utc

    @property
    def parent_entity_id(self) -> str | None:
        """Return the entity ID of the parent sensor.
        
        Only applicable for child sensors. Root sensors return None.
        
        Returns:
            str | None: The parent entity ID, or None if this is a root sensor.
        """
        return self._parent_entity_id

    @property
    def start_offset(self) -> timedelta:
        """Return the start offset.
        
        The offset applied to the start boundary, either to the configured time
        (root sensors) or to the parent's reference point (child sensors).
        
        Returns:
            timedelta: The start offset (may be positive, negative, or zero).
        """
        return self._start_offset

    @property
    def end_offset(self) -> timedelta:
        """Return the end offset.
        
        The offset applied to the end boundary, either to the configured time
        (root sensors) or to the parent's reference point (child sensors).
        
        Returns:
            timedelta: The end offset (may be positive, negative, or zero).
        """
        return self._end_offset

    @property
    def timezone_name(self) -> str | None:
        """Return the active timezone name (either configured or inherited).
        
        For root sensors, this is the configured timezone or the system default.
        For child sensors, this is inherited from the parent sensor.
        
        Returns:
            str | None: The IANA timezone string, or None if not yet resolved.
        """
        return self._resolved_timezone_str

    def is_on(self, now_utc: datetime) -> bool:
        """Check if the sensor is 'on' at the provided UTC time.
        
        The sensor is considered 'on' if the current time falls within the
        half-open interval [start, end). This means the sensor turns on at
        exactly the start time and turns off at exactly the end time.
        
        Args:
            now_utc: The current time in UTC to check against boundaries.

        Returns:
            bool: True if now_utc falls within the calculated [start, end) window,
                  False otherwise or if boundaries haven't been calculated.
        """
        if not self._calculated_start_utc or not self._calculated_end_utc:
            return False

        return self._calculated_start_utc <= now_utc < self._calculated_end_utc

    def update_boundaries(
        self,
        now_utc: datetime,
        default_timezone: tzinfo,
        sun_event_callback: Callable | None = None,
        parent_attributes: dict[str, Any] | None = None,
    ) -> bool:
        """Recalculate the start, end, and next transition timestamps.
        
        This is the core calculation method that determines when the sensor should
        be on or off. It handles both root and child sensor logic:
        
        **Root Sensors:**
        - Resolves configured times (fixed or solar) for the current date
        - Applies offsets to the resolved times
        - Handles midnight crossings (when end < start, adds 1 day to end)
        - Searches forward up to 365 days if current time is past the end
        - Checks previous day's window if current time is before today's start
        
        **Child Sensors:**
        - Extracts parent's start/end times from parent_attributes
        - Applies offsets relative to the configured reference points
        - Validates that end > start after offsets are applied
        - Inherits timezone from parent
        
        After calculating boundaries, this method also determines the next
        transition time for scheduling future updates.

        Args:
            now_utc: The current time in UTC.
            default_timezone: Fallback timezone info if none is configured.
            sun_event_callback: Function to retrieve UTC datetime for solar events.
                               Required for root sensors using sunrise/sunset.
            parent_attributes: State attributes from a parent sensor.
                              Required for child sensors.

        Returns:
            bool: True if calculation was successful, False if validation failed
                  or required data was missing.
        """
        # 1. Determine Timezone
        if not self._is_child:
            self._resolved_timezone_str = self._configured_timezone_str or str(
                default_timezone
            )

        tz = default_timezone
        if not self._is_child and self._configured_timezone_str:
            try:
                tz = ZoneInfo(self._configured_timezone_str)
            except (ZoneInfoNotFoundError, ValueError):
                tz = default_timezone

        # 2. Handle Child Logic
        if self._is_child:
            if not parent_attributes:
                return False

            parent_tz_str = parent_attributes.get("timezone")
            if parent_tz_str:
                self._resolved_timezone_str = parent_tz_str
                try:
                    tz = ZoneInfo(parent_tz_str)
                except (ZoneInfoNotFoundError, ValueError):
                    tz = default_timezone

            try:
                start_time_str = parent_attributes.get("start_time_utc")
                end_time_str = parent_attributes.get("end_time_utc")
                if start_time_str is None or end_time_str is None:
                    return False

                p_start = datetime.fromisoformat(start_time_str)
                p_end = datetime.fromisoformat(end_time_str)

                ref_s = p_start if self._start_ref == "start" else p_end
                ref_e = p_start if self._end_ref == "start" else p_end

                self._calculated_start_utc = ref_s + self._start_offset
                self._calculated_end_utc = ref_e + self._end_offset

                if self._calculated_end_utc <= self._calculated_start_utc:
                    return False

                self._calculate_next_update(now_utc)
                return True
            except (ValueError, TypeError):
                return False

        # 3. Handle Root Logic
        local_now = now_utc.astimezone(tz)
        target_date = local_now.date()

        def get_window(ref_date):
            """Helper to resolve boundaries for a specific date."""
            if self._configured_start is None or self._configured_end is None:
                raise ValueError("Start or end time is not configured")
            s = self._resolve_time(
                self._configured_start, ref_date, tz, sun_event_callback
            )
            e = self._resolve_time(
                self._configured_end, ref_date, tz, sun_event_callback
            )

            s += self._start_offset
            e += self._end_offset

            if e <= s:
                e += timedelta(days=1)
            return s, e

        try:
            current_ref_date = target_date
            start_utc, end_utc = get_window(current_ref_date)

            for _ in range(365):
                if now_utc >= end_utc:
                    current_ref_date += timedelta(days=1)
                    start_utc, end_utc = get_window(current_ref_date)
                else:
                    break

            if now_utc < start_utc:
                prev_start, prev_end = get_window(current_ref_date - timedelta(days=1))
                if prev_start <= now_utc < prev_end:
                    start_utc, end_utc = prev_start, prev_end

            self._calculated_start_utc = start_utc
            self._calculated_end_utc = end_utc
            self._calculate_next_update(now_utc)
            return True

        except (ValueError, TypeError):
            return False

    def _resolve_time(
        self, config_val: str, ref_date: Any, tz: tzinfo, sun_callback: Callable
    ) -> datetime:
        """Resolve a configuration string into a UTC datetime for a specific date.
        
        Handles two types of time specifications:
        
        **Solar Events:**
        - 'sunrise' or 'sunset': Calls sun_callback to get the event time
        - Returns the UTC datetime of the solar event for ref_date
        
        **Fixed Times:**
        - HH:MM or HH:MM:SS format
        - Parses the time and combines it with ref_date in the target timezone
        - Converts the result to UTC
        
        Args:
            config_val: The time string (e.g., '08:00:00' or 'sunset').
            ref_date: The date to apply the time to.
            tz: The target timezone info.
            sun_callback: Callback function to fetch solar event datetimes.

        Returns:
            datetime: An aware UTC datetime object.

        Raises:
            ValueError: If the sun callback is missing for solar events,
                       if the solar event cannot be calculated,
                       or if the time format is invalid.
        """
        if config_val in ("sunrise", "sunset"):
            if not sun_callback:
                raise ValueError("Sun callback missing")
            dt = sun_callback(config_val, ref_date)
            if not dt:
                raise ValueError(f"Could not calculate {config_val}")
            return dt

        try:
            parts = [int(p) for p in config_val.split(":")]
            if len(parts) == 2:
                t = time(parts[0], parts[1])
            elif len(parts) == 3:
                t = time(parts[0], parts[1], parts[2])
            else:
                raise ValueError(f"Invalid time format: {config_val}")
        except Exception as exc:
            raise ValueError(f"Invalid time: {config_val}") from exc

        local_dt = datetime.combine(ref_date, t).replace(tzinfo=tz)
        return local_dt.astimezone(ZoneInfo("UTC"))

    def _calculate_next_update(self, now_utc: datetime) -> None:
        """Calculate the next timestamp at which the sensor state will change.
        
        Determines when to schedule the next update based on the current time
        and the calculated boundaries:
        
        - If now < start: Next update is at start (sensor will turn on)
        - If start <= now < end: Next update is at end (sensor will turn off)
        - If now >= end: Next update is at start + 1 day (next day's start)
        
        The result is stored in _next_update_utc for use by the HA wrapper
        to schedule the next state update callback.

        Args:
            now_utc: The current time in UTC.
        """
        if self._calculated_start_utc is None or self._calculated_end_utc is None:
            self._next_update_utc = None
            return

        if now_utc < self._calculated_start_utc:
            self._next_update_utc = self._calculated_start_utc
        elif now_utc < self._calculated_end_utc:
            self._next_update_utc = self._calculated_end_utc
        else:
            self._next_update_utc = self._calculated_start_utc + timedelta(days=1)
