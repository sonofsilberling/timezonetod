import unittest
from datetime import datetime, time, timedelta, date
from zoneinfo import ZoneInfo
from custom_components.timezonetod.entity import TimezoneTodSensorCore

# Mock Sun Callback
def mock_sun_callback(event, ref_date):
    """
    Simulates sunrise at 06:00 UTC and sunset at 18:00 UTC 
    for any given date.
    """
    if event == "sunrise":
        return datetime.combine(ref_date, time(6, 0)).replace(tzinfo=ZoneInfo("UTC"))
    if event == "sunset":
        return datetime.combine(ref_date, time(18, 0)).replace(tzinfo=ZoneInfo("UTC"))
    return None

class TestTimezoneTodCore(unittest.TestCase):

    def setUp(self):
        self.utc = ZoneInfo("UTC")
        self.london = ZoneInfo("Europe/London")
        # Standard Parent Window for testing children: 09:00 to 17:00 UTC
        self.parent_attrs = {
            "start_time_utc": "2026-01-01T09:00:00+00:00",
            "end_time_utc": "2026-01-01T17:00:00+00:00"
        }        

    def test_simple_day_window(self):
        """Test a standard 09:00 to 17:00 window."""
        core = TimezoneTodSensorCore(
            name="Work Hours",
            start_time="09:00:00",
            end_time="17:00:00"
        )
        
        # 10:00 AM UTC on a Monday
        now = datetime(2024, 1, 1, 10, 0, tzinfo=self.utc)
        core.update_boundaries(now, self.utc)
        
        self.assertTrue(core.is_on(now))
        self.assertEqual(core.calculated_start_utc, datetime(2024, 1, 1, 9, 0, tzinfo=self.utc))

    def test_cross_midnight_yesterday(self):
        """Test 22:00 to 06:00, checking at 01:00 AM (the 'yesterday' logic)."""
        core = TimezoneTodSensorCore(
            name="Night",
            start_time="22:00:00",
            end_time="06:00:00"
        )
        
        # Tuesday at 01:00 AM. 
        # This should still be "On" because it's part of Monday's 22:00 window.
        now = datetime(2024, 1, 2, 1, 0, tzinfo=self.utc)
        core.update_boundaries(now, self.utc)
        
        self.assertTrue(core.is_on(now))
        # Start should be Monday 22:00
        self.assertEqual(core.calculated_start_utc.day, 1) 
        self.assertEqual(core.calculated_start_utc.hour, 22)

    def test_sun_events(self):
        """Test sunrise to sunset using the mock callback."""
        core = TimezoneTodSensorCore(
            name="Daylight",
            start_time="sunrise",
            end_time="sunset"
        )
        
        now = datetime(2024, 1, 1, 12, 0, tzinfo=self.utc)
        core.update_boundaries(now, self.utc, sun_event_callback=mock_sun_callback)
        
        self.assertTrue(core.is_on(now))
        self.assertEqual(core.calculated_start_utc.hour, 6) # Mock sunrise
        self.assertEqual(core.calculated_end_utc.hour, 18)  # Mock sunset

    def test_child_offsets(self):
        """Test child inheriting from parent with a 1-hour (3600s) offset."""
        core = TimezoneTodSensorCore(
            name="Post-Work",
            is_child=True,
            parent_entity_id="binary_sensor.work_hours",
            start_offset=timedelta(hours=1),
            end_offset=timedelta(hours=1)
        )
        
        parent_attrs = {
            "start_time_utc": "2024-01-01T09:00:00+00:00",
            "end_time_utc": "2024-01-01T17:00:00+00:00"
        }
        
        now = datetime(2024, 1, 1, 10, 30, tzinfo=self.utc)
        core.update_boundaries(now, self.utc, parent_attributes=parent_attrs)
        
        # Parent starts at 09:00, Child with +1h offset starts at 10:00
        self.assertEqual(core.calculated_start_utc.hour, 10)
        self.assertTrue(core.is_on(now))

    def test_while_loop_downtime_recovery(self):
        """
        Test the 'While' loop: Simulate system coming back online 
        3 days after the last known window.
        """
        core = TimezoneTodSensorCore(
            name="Daily Brief",
            start_time="08:00:00",
            end_time="09:00:00"
        )
        
        # Current time is Thursday.
        now = datetime(2024, 1, 4, 8, 30, tzinfo=self.utc)
        
        # We trigger update. The logic should skip Mon, Tue, Wed 
        # and find Thursday's window.
        core.update_boundaries(now, self.utc)
        
        self.assertEqual(core.calculated_start_utc.day, 4)
        self.assertTrue(core.is_on(now))

    def test_timezone_shift(self):
        """Test that a sensor in New York behaves correctly vs UTC now."""
        # NYC is UTC-5
        core = TimezoneTodSensorCore(
            name="NYC Morning",
            start_time="08:00:00",
            end_time="10:00:00",
            timezone_str="America/New_York"
        )
        
        # It is 13:30 UTC. 
        # In NYC, it is 08:30 AM (13:30 - 5 hours). Sensor should be ON.
        now_utc = datetime(2024, 1, 1, 13, 30, tzinfo=self.utc)
        core.update_boundaries(now_utc, self.utc)
        
        self.assertTrue(core.is_on(now_utc))

    def test_relational_first_30_mins(self):
        """Example 1: Sensor runs for the first 30 minutes of the parent."""
        core = TimezoneTodSensorCore(
            name="First 30 Mins",
            is_child=True,
            parent_entity_id="binary_sensor.parent",
            start_ref="start",
            start_offset=timedelta(seconds=0),
            end_ref="start",
            end_offset=timedelta(seconds=1800) # 30 mins
        )
        
        now = datetime(2026, 1, 1, 9, 15, tzinfo=self.utc)
        core.update_boundaries(now, self.utc, parent_attributes=self.parent_attrs)
        
        self.assertEqual(core.calculated_start_utc.hour, 9)
        self.assertEqual(core.calculated_start_utc.minute, 0)
        self.assertEqual(core.calculated_end_utc.minute, 30)
        self.assertTrue(core.is_on(now))
        # Verify it turns off after 30 mins
        self.assertFalse(core.is_on(now + timedelta(minutes=20)))

    def test_relational_last_20_mins(self):
        """Example 2: Sensor runs for the last 20 minutes of the parent."""
        core = TimezoneTodSensorCore(
            name="Last 20 Mins",
            is_child=True,
            parent_entity_id="binary_sensor.parent",
            start_ref="end",
            start_offset=timedelta(seconds=-1200), # 20 mins before end
            end_ref="end",
            end_offset=timedelta(seconds=0)
        )
        
        now = datetime(2026, 1, 1, 16, 50, tzinfo=self.utc)
        core.update_boundaries(now, self.utc, parent_attributes=self.parent_attrs)
        
        self.assertEqual(core.calculated_start_utc.hour, 16)
        self.assertEqual(core.calculated_start_utc.minute, 40)
        self.assertEqual(core.calculated_end_utc.hour, 17)
        self.assertTrue(core.is_on(now))

    def test_relational_middle_window(self):
        """Example 3: Starts 30m after parent start, ends 20m before parent end."""
        core = TimezoneTodSensorCore(
            name="Middle Hole",
            is_child=True,
            parent_entity_id="binary_sensor.parent",
            start_ref="start",
            start_offset=timedelta(seconds=1800),
            end_ref="end",
            end_offset=timedelta(seconds=-1200)
        )
        
        now = datetime(2026, 1, 1, 12, 0, tzinfo=self.utc)
        core.update_boundaries(now, self.utc, parent_attributes=self.parent_attrs)
        
        self.assertEqual(core.calculated_start_utc.minute, 30) # 09:30
        self.assertEqual(core.calculated_end_utc.minute, 40)   # 16:40
        self.assertTrue(core.is_on(now))

    def test_relational_cross_midnight_parent(self):
        """Test relational logic when the parent crosses midnight (22:00 to 06:00)."""
        midnight_parent = {
            "start_time_utc": "2026-01-01T22:00:00+00:00",
            "end_time_utc": "2026-01-02T06:00:00+00:00"
        }
        
        # Child: Run for 1 hour starting 30 mins before parent ends (05:30 to 06:30)
        core = TimezoneTodSensorCore(
            name="End Cycle",
            is_child=True,
            parent_entity_id="binary_sensor.parent",
            start_ref="end",
            start_offset=timedelta(seconds=-1800),
            end_ref="end",
            end_offset=timedelta(seconds=1800)
        )
        
        now = datetime(2026, 1, 2, 5, 45, tzinfo=self.utc)
        core.update_boundaries(now, self.utc, parent_attributes=midnight_parent)
        
        self.assertEqual(core.calculated_start_utc.day, 2)
        self.assertEqual(core.calculated_start_utc.hour, 5)
        self.assertEqual(core.calculated_start_utc.minute, 30)
        self.assertTrue(core.is_on(now))

    def test_invalid_relational_range(self):
        """Verify that if offsets create an end < start, the update returns False."""
        core = TimezoneTodSensorCore(
            name="Impossible Sensor",
            is_child=True,
            parent_entity_id="binary_sensor.parent",
            start_ref="end",
            end_ref="start" # End happens before start
        )
        
        now = datetime(2026, 1, 1, 12, 0, tzinfo=self.utc)
        # Should return False because ref_e (09:00) < ref_s (17:00)
        success = core.update_boundaries(now, self.utc, parent_attributes=self.parent_attrs)
        self.assertFalse(success)        
    

if __name__ == "__main__":
    unittest.main()