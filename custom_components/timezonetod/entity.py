"""Core Logic for Timezone Time of Day Sensor"""

from __future__ import annotations
from datetime import time, timedelta, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, Any
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
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        start_offset: Optional[timedelta] = None,
        end_offset: Optional[timedelta] = None,
        timezone_str: Optional[str] = None,
        parent_entity_id: Optional[str] = None,
        start_ref: Optional[str] = "start",
        end_ref: Optional[str] = "end",
    ) -> None:
        """Initialize the core Time of Day sensor logic.

        Args:
            name: Human-readable name of the sensor.
            is_child: True if this sensor inherits boundaries from a parent.
            start_time: Start time string (HH:MM:SS or 'sunrise'/'sunset').
            end_time: End time string (HH:MM:SS or 'sunrise'/'sunset').
            start_offset: Timedelta to offset the start time.
            end_offset: Timedelta to offset the end time.
            timezone_str: IANA timezone string (e.g., 'UTC' or 'Europe/London').
            parent_entity_id: The entity ID of the parent sensor (if is_child is True).
            start_ref: Whether child start relates to parent 'start' or 'end'.
            end_ref: Whether child end relates to parent 'start' or 'end'.
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

        self._calculated_start_utc: Optional[datetime] = None
        self._calculated_end_utc: Optional[datetime] = None
        self._next_update_utc: Optional[datetime] = None

    @property
    def name(self) -> str:
        """Return the sensor name."""
        return self._name

    @property
    def is_child(self) -> bool:
        """Return True if this is a child sensor."""
        return self._is_child

    @property
    def calculated_start_utc(self) -> Optional[datetime]:
        """Return the calculated start time in UTC."""
        return self._calculated_start_utc

    @property
    def calculated_end_utc(self) -> Optional[datetime]:
        """Return the calculated end time in UTC."""
        return self._calculated_end_utc

    @property
    def next_update_utc(self) -> Optional[datetime]:
        """Return the timestamp for the next scheduled state transition."""
        return self._next_update_utc

    @property
    def parent_entity_id(self) -> Optional[str]:
        """Return the entity ID of the parent sensor."""
        return self._parent_entity_id

    @property
    def start_offset(self) -> timedelta:
        """Return the start offset."""
        return self._start_offset

    @property
    def end_offset(self) -> timedelta:
        """Return the end offset."""
        return self._end_offset

    @property
    def timezone_name(self) -> Optional[str]:
        """Return the active timezone name (either configured or inherited)."""
        return self._resolved_timezone_str

    def is_on(self, now_utc: datetime) -> bool:
        """Check if the sensor is 'on' at the provided UTC time.

        Args:
            now_utc: The current time in UTC to check against boundaries.

        Returns:
            bool: True if now_utc falls within the calculated [start, end) window.
        """
        if not self._calculated_start_utc or not self._calculated_end_utc:
            return False

        return self._calculated_start_utc <= now_utc < self._calculated_end_utc

    def update_boundaries(
        self,
        now_utc: datetime,
        default_timezone: tzinfo,
        sun_event_callback: Optional[Callable] = None,
        parent_attributes: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Recalculate the start, end, and next transition timestamps.

        Handles the transition logic for both root and child sensors,
        accounting for crossing midnight and relational offsets.

        Args:
            now_utc: The current time in UTC.
            default_timezone: Fallback timezone info if none is configured.
            sun_event_callback: Function to retrieve UTC datetime for solar events.
            parent_attributes: State attributes from a parent sensor.

        Returns:
            bool: True if calculation was successful, False otherwise.
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

            parent_tz = parent_attributes.get("timezone")
            if parent_tz:
                self._resolved_timezone_str = parent_tz
                tz = parent_tz

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

            while now_utc >= end_utc:
                current_ref_date += timedelta(days=1)
                start_utc, end_utc = get_window(current_ref_date)

            if now_utc < start_utc:
                prev_start, prev_end = get_window(target_date - timedelta(days=1))
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

        Args:
            config_val: The time string (e.g., '08:00:00' or 'sunset').
            ref_date: The date to apply the time to.
            tz: The target timezone info.
            sun_callback: Callback function to fetch solar event datetimes.

        Returns:
            datetime: An aware UTC datetime object.

        Raises:
            ValueError: If the sun callback is missing or the time format is invalid.
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
