"""Tests for US region support and const helper functions."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.const import (
    CONF_COUNTRY,
    CONF_STORE_KEY,
    DOMAIN,
    language_for_country,
    tld_for_country,
)
from custom_components.lidl.coordinator import LidlDataUpdateCoordinator

# ---------------------------------------------------------------------------
# Unit tests for const helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("DE", "de-DE"),
        ("AT", "at-AT"),
        ("FR", "fr-FR"),
        ("GB", "en-GB"),  # special case
        ("US", "en-US"),  # special case — must NOT be "us-US"
        ("de", "de-DE"),  # lowercase input
        ("us", "en-US"),  # lowercase input
        ("gb", "en-GB"),  # lowercase input
    ],
)
def test_language_for_country(country: str, expected: str) -> None:
    """language_for_country must return correct Accept-Language tags."""
    assert language_for_country(country) == expected


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("DE", "de"),
        ("AT", "at"),
        ("FR", "fr"),
        ("GB", "com"),  # lidl.com
        ("US", "com"),  # lidl.com
        ("de", "de"),
        ("us", "com"),
    ],
)
def test_tld_for_country(country: str, expected: str) -> None:
    """tld_for_country must return correct TLD strings."""
    assert tld_for_country(country) == expected


# ---------------------------------------------------------------------------
# Integration: coordinator properties for US
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_coordinator_us_configuration_url_no_store(hass) -> None:
    """Coordinator without a store address must use lidl.com for US."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTRY: "US", CONF_STORE_KEY: "US1595"},
        options={},
    )
    entry.add_to_hass(hass)
    coordinator = LidlDataUpdateCoordinator(hass, entry)
    # No store address is loaded yet, so it falls back to the generic URL
    assert "lidl.com" in coordinator.configuration_url


async def test_coordinator_us_account_configuration_url(hass) -> None:
    """account_configuration_url for US must use lidl.com and en-US language."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTRY: "US", CONF_STORE_KEY: "US1595"},
        options={},
    )
    entry.add_to_hass(hass)
    coordinator = LidlDataUpdateCoordinator(hass, entry)
    url = coordinator.account_configuration_url
    assert "lidl.com" in url, f"Expected lidl.com in URL, got: {url}"
    assert "en-US" in url, f"Expected en-US language in URL, got: {url}"
    assert "us-US" not in url, f"Unexpected 'us-US' in URL: {url}"


async def test_coordinator_us_language_in_headers(hass) -> None:
    """Verify that US coordinator uses en-US, not us-US, for Accept-Language."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTRY: "US", CONF_STORE_KEY: "US1595"},
        options={},
    )
    entry.add_to_hass(hass)
    coordinator = LidlDataUpdateCoordinator(hass, entry)
    lang = language_for_country(coordinator.country)
    assert lang == "en-US"
    assert lang != "us-US"
