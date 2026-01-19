# entity.py

from __future__ import annotations
from datetime import time, timedelta, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, Any, Dict


class TimezoneTodSensorCore:
    """
    Core logic for the Timezone Time of Day sensor.
    This class remains framework-agnostic for testing.
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

    # --- Properties ---
    @property
    def name(self) -> str:
        return self._name

    @property
    def is_child(self) -> bool:
        return self._is_child

    @property
    def calculated_start_utc(self) -> Optional[datetime]:
        return self._calculated_start_utc

    @property
    def calculated_end_utc(self) -> Optional[datetime]:
        return self._calculated_end_utc

    @property
    def next_update_utc(self) -> Optional[datetime]:
        return self._next_update_utc

    @property
    def parent_entity_id(self) -> Optional[str]:
        return self._parent_entity_id

    @property
    def start_offset(self) -> timedelta:
        return self._start_offset

    @property
    def end_offset(self) -> timedelta:
        return self._end_offset

    @property
    def timezone_name(self) -> Optional[str]:
        """Return the timezone name (either configured or inherited)."""
        return self._resolved_timezone_str

    def is_on(self, now_utc: datetime) -> bool:
        """Determines if the sensor is 'on' now."""
        if not self._calculated_start_utc or not self._calculated_end_utc:
            return False

        # We've normalized boundaries so that start < end
        # (even if it crosses midnight, end is simply +1 day)
        return self._calculated_start_utc <= now_utc < self._calculated_end_utc

    def update_boundaries(
        self,
        now_utc: datetime,
        default_timezone: tzinfo,
        sun_event_callback: Optional[callable] = None,
        parent_attributes: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Calculates start/end datetimes.
        If 'now' is past the current window, it calculates for the next window.
        """

        # 1. Determine Timezone
        if not self._is_child:
            # For root sensors, the resolved zone is what was configured
            self._resolved_timezone_str = self._configured_timezone_str or str(
                default_timezone
            )
 
        tz = default_timezone
        if not self._is_child and self._configured_timezone_str:
            try:
                tz = ZoneInfo(self._configured_timezone_str)
            except (ZoneInfoNotFoundError, ValueError):
                tz = default_timezone

        # 2. Handle Child Logic (Inherits absolute UTC times)
        if self._is_child:
            if not parent_attributes:
                return False

            parent_tz = parent_attributes.get("timezone")
            if parent_tz:
                self._resolved_timezone_str = parent_tz
                tz = parent_tz

            try:
                # 1. Get Parent absolute boundaries
                p_start = datetime.fromisoformat(
                    parent_attributes.get("start_time_utc")
                )
                p_end = datetime.fromisoformat(parent_attributes.get("end_time_utc"))
                if not p_start or not p_end:
                    return False

                # 2. Determine which parent point to anchor to
                ref_s = p_start if self._start_ref == "start" else p_end
                ref_e = p_start if self._end_ref == "start" else p_end

                # 3. Apply offsets to the chosen anchor
                self._calculated_start_utc = ref_s + self._start_offset
                self._calculated_end_utc = ref_e + self._end_offset

                # Handle potential crossing (e.g. if offsets result in start > end)
                if self._calculated_end_utc <= self._calculated_start_utc:
                    # If the logic creates a zero or negative window,
                    # we don't roll over days (it's a sub-window logic error)
                    return False

                self._calculate_next_update(now_utc)
                return True
            except (ValueError, TypeError):
                return False

        # 3. Handle Root Logic (Calculates from scratch)
        # Use current local date in the TARGET timezone as a starting point
        local_now = now_utc.astimezone(tz)
        target_date = local_now.date()

        def get_window(ref_date):
            """Helper to resolve boundaries for a specific date."""
            s = self._resolve_time(
                self._configured_start, ref_date, tz, sun_event_callback
            )
            e = self._resolve_time(
                self._configured_end, ref_date, tz, sun_event_callback
            )

            # Apply offsets immediately
            s += self._start_offset
            e += self._end_offset

            # Handle cross-midnight (e.g., 22:00 to 06:00)
            if e <= s:
                e += timedelta(days=1)
            return s, e

        try:
            # Step A: Start with the current calendar date
            current_ref_date = target_date
            start_utc, end_utc = get_window(current_ref_date)

            # Step B: Ensure we aren't looking at a window that already ended
            # We use a while loop to handle extreme offsets or edge cases
            # boundary is [start, end), so now_utc >= end_utc means this window is finished.
            while now_utc >= end_utc:
                current_ref_date += timedelta(days=1)
                start_utc, end_utc = get_window(current_ref_date)

            # Step C: Check if we are BEFORE the current day's window.
            # If so, we might still be in the tail-end of "yesterday's" window
            # (only relevant for periods crossing midnight).
            if now_utc < start_utc:
                prev_start, prev_end = get_window(target_date - timedelta(days=1))
                if prev_start <= now_utc < prev_end:
                    start_utc, end_utc = prev_start, prev_end

            self._calculated_start_utc = start_utc
            self._calculated_end_utc = end_utc
            self._calculate_next_update(now_utc)
            return True

        except Exception:
            return False

    def _resolve_time(
        self, config_val: str, ref_date: any, tz: tzinfo, sun_callback: callable
    ) -> datetime:
        """Converts a config string (time or sun event) into a UTC datetime."""
        # Handle Sun Events
        if config_val in ("sunrise", "sunset"):
            if not sun_callback:
                raise ValueError("Sun callback missing")
            # Returns a UTC datetime for that event on that specific date
            dt = sun_callback(config_val, ref_date)
            if not dt:
                raise ValueError(f"Could not calculate {config_val}")
            return dt

        # Handle Clock Time (HH:MM:SS)
        # 1. Parse string to time object
        try:
            # We use a simple split to support HH:MM or HH:MM:SS
            parts = [int(p) for p in config_val.split(":")]
            t = time(*parts)
        except Exception:
            raise ValueError(f"Invalid time: {config_val}")

        # 2. Combine with reference date and timezone
        local_dt = datetime.combine(ref_date, t).replace(tzinfo=tz)
        return local_dt.astimezone(ZoneInfo("UTC"))

    def _calculate_next_update(self, now_utc: datetime) -> None:
        """Determines when the state will next transition."""
        if now_utc < self._calculated_start_utc:
            self._next_update_utc = self._calculated_start_utc
        elif now_utc < self._calculated_end_utc:
            self._next_update_utc = self._calculated_end_utc
        else:
            # If we are past the current window, the next update is the start of the next cycle
            # This is a fallback; usually update_boundaries is called again.
            self._next_update_utc = self._calculated_start_utc + timedelta(days=1)
