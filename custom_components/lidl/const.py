"""Constants for the Lidl Weekly Offers integration."""

DOMAIN = "lidl"
ATTRIBUTION = "Data provided by Lidl Plus API"
PLATFORMS = ["sensor", "button", "image"]

CONF_STORE_KEY = "store_key"
CONF_COUNTRY = "country"
CONF_LANGUAGE = "language"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_AUTO_ACTIVATE_COUPONS = "auto_activate_coupons"
CONF_SKIP_SPECIAL_COUPONS = "skip_special_coupons"
CONF_CARD_NUMBER = "card_number"
CONF_PRODUCT_FILTERS = "product_filters"

DEFAULT_UPDATE_INTERVAL = 24  # hours
MIN_UPDATE_INTERVAL = 1  # hours
MAX_UPDATE_INTERVAL = 168  # hours (1 week)

# Auto-discovery
DISCOVERY_RADIUS_KM = 20.0

# Sensor attributes
ATTR_DISCOUNTS = "discounts"
ATTR_VALID_DATE = "valid_until"
ATTR_VALID_FROM = "valid_from"

# Countries whose language tag differs from their country code.
# Format: country_code (upper) -> Accept-Language value
_COUNTRY_LANGUAGE_OVERRIDES: dict[str, str] = {
    "US": "en-US",
    "GB": "en-GB",
}

# Countries that use "com" as their TLD (lidl.com) instead of lidl.<cc>
_COUNTRY_TLD_OVERRIDES: dict[str, str] = {
    "US": "com",
    "GB": "com",
}


def language_for_country(country: str) -> str:
    """Return the Accept-Language / language tag for a Lidl Plus country code."""
    country_upper = country.upper()
    if country_upper in _COUNTRY_LANGUAGE_OVERRIDES:
        return _COUNTRY_LANGUAGE_OVERRIDES[country_upper]
    cc = country_upper.lower()
    return f"{cc}-{country_upper}"


def tld_for_country(country: str) -> str:
    """Return the top-level domain for the Lidl website of a given country."""
    country_upper = country.upper()
    if country_upper in _COUNTRY_TLD_OVERRIDES:
        return _COUNTRY_TLD_OVERRIDES[country_upper]
    return country_upper.lower()
