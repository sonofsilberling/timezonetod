# /config/custom_components/timezonetod/const.py

"""Constants for the Timezone Time of Day integration."""

# This is the domain of your integration. It must match your folder name.
DOMAIN = "timezonetod"

# --- Configuration Constants ---
# These are the keys used in your config_flow and config_entry data.
CONF_START_TIME = "start_time"
CONF_END_TIME = "end_time"
CONF_START_OFFSET = "start_offset"
CONF_END_OFFSET = "end_offset"
CONF_TIMEZONE = "timezone"
CONF_PARENT_ENTITY = "parent_entity"
CONF_IS_CHILD = "is_child"
CONF_START_REF = "start_ref"
CONF_END_REF = "end_ref"

# Reference options
REF_START = "start"
REF_END = "end"

# --- Attribute Constants ---
# These are the keys for the extra_state_attributes your sensor will have.
# Using constants for these is good practice for consistency.
ATTR_START_TIME_LOCAL = "start_time_local"
ATTR_END_TIME_LOCAL = "end_time_local"
ATTR_NEXT_UPDATE_LOCAL = "next_update_local"
ATTR_START_TIME_UTC = "start_time_utc"
ATTR_END_TIME_UTC = "end_time_utc"
ATTR_NEXT_UPDATE_UTC = "next_update_utc"
ATTR_IS_CHILD = "is_child"
ATTR_PARENT_ENTITY = "parent_entity"
ATTR_TIMEZONE = "timezone"