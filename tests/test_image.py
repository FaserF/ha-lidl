"""Test the Lidl Weekly Offers loyalty card QR image entity."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.const import CONF_COUNTRY, CONF_STORE_KEY, DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_loyalty_card_qr_image_state_and_content(hass: HomeAssistant) -> None:
    """Test loyalty card QR code image entity state and image rendering."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={
            CONF_COUNTRY: "DE",
            CONF_STORE_KEY: "123",
            "refresh_token": "mock_refresh_token",
        },
        options={},
    )
    entry.add_to_hass(hass)

    mock_data = {
        "offers": [],
        "preview_offers": [],
        "loyalty_id": "1234567890",
        "user_profile": {
            "user_name": "Test User",
            "email": "test@example.com",
            "country": "DE",
            "registration_date": "2024-01-01",
        },
    }

    with patch(
        "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
        return_value=mock_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("image.lidl_plus_account_de_loyalty_card_qr_code")
        assert state is not None
        assert state.state != "unknown"
        assert "T" in state.state  # ISO datetime string timestamp

        assert state.attributes["loyalty_id"] == "1234567890"
        assert state.attributes["user_name"] == "Test User"
        assert state.attributes["email"] == "test@example.com"
