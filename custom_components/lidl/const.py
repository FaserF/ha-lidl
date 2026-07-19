"""Constants for the Lidl Weekly Offers integration."""

DOMAIN = "lidl"
ATTRIBUTION = "Data provided by Lidl Plus API"
PLATFORMS = ["sensor", "button"]

CONF_STORE_KEY = "store_key"
CONF_COUNTRY = "country"
CONF_LANGUAGE = "language"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_REFRESH_TOKEN = "refresh_token"

DEFAULT_UPDATE_INTERVAL = 24  # hours
MIN_UPDATE_INTERVAL = 1  # hours
MAX_UPDATE_INTERVAL = 168  # hours (1 week)

# Sensor attributes
ATTR_DISCOUNTS = "discounts"
ATTR_VALID_DATE = "valid_until"
ATTR_VALID_FROM = "valid_from"
