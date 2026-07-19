"""Test the Lidl Weekly Offers config flow."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.api import Store
from custom_components.lidl.const import (
    CONF_COUNTRY,
    CONF_STORE_KEY,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_flow_user_setup(hass: HomeAssistant) -> None:
    """Test user setup step of the config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Mock search results
    mock_store = Store(
        storeKey="123",
        name="Store 123",
        address="Test Address",
        postalCode="12345",
        locality="Test City",
    )

    with patch(
        "custom_components.lidl.api.LidlAPIClient.search_stores",
        return_value=[mock_store],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTRY: "DE", "search_query": "Munich"},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "select_store"

        # Now select the store
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_STORE_KEY: "123"},
        )
        assert result["type"] == "create_entry"
        assert result["title"] == "Lidl Store 123"
        assert result["data"] == {
            CONF_COUNTRY: "DE",
            CONF_STORE_KEY: "123",
            "address": "Test Address",
            "city": "Test City",
            "name": "Store 123",
            "postal_code": "12345",
        }


async def test_flow_already_configured(hass: HomeAssistant) -> None:
    """Test config flow aborts when the same store is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={CONF_COUNTRY: "DE", CONF_STORE_KEY: "123"},
        unique_id="lidl_123",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    mock_store = Store(
        storeKey="123",
        name="Store 123",
        address="Test Address",
        postalCode="12345",
        locality="Test City",
    )
    with patch(
        "custom_components.lidl.api.LidlAPIClient.search_stores",
        return_value=[mock_store],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTRY: "DE", "search_query": "Munich"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_STORE_KEY: "123"},
        )
        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test options flow to configure update interval."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={CONF_COUNTRY: "DE", CONF_STORE_KEY: "123"},
        unique_id="lidl_123",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UPDATE_INTERVAL: 6},
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_UPDATE_INTERVAL: 6}
