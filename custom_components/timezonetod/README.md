# Timezone-aware Time of Day (ToD) for Home Assistant

A Home Assistant custom component to create binary sensors that track specific time windows. Unlike the built-in "Times of the Day" helper, this component supports **fixed timezones (e.g., UTC for utility tariffs)** and **relational child sensors**. The main use case for this component is to cater for 
utility night tariffs based on UTC times.

## Key Features

- **Timezone Awareness:** Define schedules in any IANA timezone (e.g., `Europe/London`, `UTC`, `America/New_York`) regardless of your Home Assistant server's local time. Perfect for utility tariffs that follow UTC.
- **Sun Event Support:** Use `sunrise` or `sunset` as start or end points. **Note:** Sunrise and Sunset times are based on home assistant's location and do not take into account the timezone of this component.
- **Relational Child Sensors:** Create "Sub-schedules" that are relative to a Parent sensor. 
  - *Example:* A sensor that runs for the first 30 minutes of your "Cheap Electricity" window.
  - *Example:* A sensor that starts 20 minutes before your "Work" window ends.
- **UI-Based Configuration:** Full support for Config Flow and Options Flow (edit your settings without restarting).
- **Dynamic Icons:** Automatically switches icons between clocks and suns based on your configuration.
- **Developer Ready:** Includes a standalone logic core (`entity.py`) with 100% pass-rate unit tests.

## Installation

### Manual Installation
1. Download the `timezonetod` folder.
2. Copy the folder to your Home Assistant `custom_components/` directory.
3. Restart Home Assistant.
4. Go to **Settings > Devices & Services > Helpers > Create Helper ** and search for "Time Zone based Times of the Day".

---

## Configuration

### Root Sensor
A Root Sensor is a standalone schedule.
- **Start/End Time:** Use `HH:MM:SS` or `sunrise`/`sunset`.
- **Timezone:** Select the timezone this schedule should follow. This is vital for UK users on tariffs (like Octopus) that stick to UTC during Daylight Savings (BST).

### Child Sensor
A Child Sensor inherits its boundaries from a Root Sensor.
- **Parent Entity:** Select any existing `timezonetod` root sensor.
- **Relational Anchors:**
    - **Start relates to:** Choose if the start offset applies to the parent's *Start* or *End*.
    - **End relates to:** Choose if the end offset applies to the parent's *Start* or *End*.
- **Offsets:** Measured in seconds. Use negative numbers for "before".

#### Example Use Cases for Children:
| Use Case | Start Anchor | Start Offset | End Anchor | End Offset |
| :--- | :--- | :--- | :--- | :--- |
| **First 30 mins of Parent** | Start | 0 | Start | 1800 |
| **Last 20 mins of Parent** | End | -1200 | End | 0 |
| **30m after Start to 20m before End** | Start | 1800 | End | -1200 |

---

##    Developer & Unit Testing
This integration is built with a decoupled logic core (`entity.py`), allowing the time calculation engine to be tested independently of the Home Assistant state machine.

To run the tests on your local machine or via SSH:
```bash
cd custom_components/timezonetod/
python3 test.py
```
This requires Python version 3.9 or later.

## Attributes
The sensor exposes several useful attributes for debugging and use in templates:
- start_time_local: The current window's start time in your HA local time.
- end_time_local: The current window's end time in your HA local time.
- start_time_utc: Absolute UTC timestamp for the window start.
- end_time_utc: Absolute UTC timestamp for the window end.
- timezone: The timezone being tracked.
- is_child: Boolean indicating if this is a relational sensor.