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



def test_us_store_search_by_postal_code_and_city() -> None:
    """Test searching US stores with full postal code, 5-digit ZIP, and city name."""
    from custom_components.lidl.api import LidlAPIClient

    client = LidlAPIClient(country="US")
    mock_stores_payload = [
        {
            "storeKey": "US1595",
            "name": "Idylwood Plaza",
            "address": "7511 Leesburg Pike",
            "postalCode": "22043-2105",
            "locality": "Falls Church",
            "state": "Virginia",
            "province": "",
        },
        {
            "storeKey": "US1590",
            "name": "Grand Street",
            "address": "408 Grand St",
            "postalCode": "10002-4702",
            "locality": "New York",
            "state": "New York",
            "province": "USA TOTAL",
        },
    ]

    with patch.object(client, "_request", return_value=mock_stores_payload):
        # 5-digit ZIP search (prefix)
        res_5digit = client.search_stores("22043")
        assert len(res_5digit) == 1
        assert res_5digit[0].store_key == "US1595"

        # Full ZIP+4 search
        res_full = client.search_stores("22043-2105")
        assert len(res_full) == 1
        assert res_full[0].store_key == "US1595"

        # ZIP+4 with space instead of hyphen
        res_space = client.search_stores("22043 2105")
        assert len(res_space) == 1
        assert res_space[0].store_key == "US1595"

        # City search
        res_city = client.search_stores("Falls Church")
        assert len(res_city) == 1
        assert res_city[0].store_key == "US1595"

        # State search
        res_state = client.search_stores("Virginia")
        assert len(res_state) == 1
        assert res_state[0].store_key == "US1595"
