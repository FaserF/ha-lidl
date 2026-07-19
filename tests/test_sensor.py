"""Test the Lidl Weekly Offers sensors."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.const import CONF_COUNTRY, CONF_STORE_KEY, DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_sensors(hass: HomeAssistant) -> None:
    """Test successful sensors setup and state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={
            CONF_COUNTRY: "DE",
            CONF_STORE_KEY: "123",
            "name": "Store 123",
            "address": "Main St 1",
            "postal_code": "12345",
            "city": "Town",
        },
        options={},
    )
    entry.add_to_hass(hass)

    mock_data = {
        "offers": [
            {
                "id": "1",
                "title": "Milk",
                "brand": "Milbona",
                "category": "Dairy",
                "price": "1.29 €",
            }
        ],
        "preview_offers": [
            {
                "id": "2",
                "title": "Butter",
                "brand": "Milbona",
                "category": "Dairy",
                "price": "2.19 €",
            }
        ],
    }

    with patch(
        "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
        return_value=mock_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Check Offers Sensor
        state = hass.states.get("sensor.lidl_store_123_offers")
        assert state is not None
        assert state.state == "1"
        assert state.attributes["discounts"][0]["title"] == "Milk"
        assert state.attributes["store_name"] == "Store 123"
        assert state.attributes["store_address"] == "Main St 1"
        assert state.attributes["store_postal_code"] == "12345"
        assert state.attributes["store_city"] == "Town"
        assert state.attributes["store_country"] == "DE"

        # Check Offers Preview Sensor
        preview_state = hass.states.get("sensor.lidl_store_123_offers_preview")
        assert preview_state is not None
        assert preview_state.state == "1"
        assert preview_state.attributes["discounts"][0]["title"] == "Butter"
