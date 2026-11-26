"""Test the Lidl Weekly Offers button."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.const import CONF_COUNTRY, CONF_STORE_KEY, DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_button_press(hass: HomeAssistant) -> None:
    """Test button entity press triggers update."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={CONF_COUNTRY: "DE", CONF_STORE_KEY: "123"},
        options={},
    )
    entry.add_to_hass(hass)

    mock_data = {
        "offers": [],
        "preview_offers": [],
    }

    with (
        patch(
            "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
            return_value=mock_data,
        ) as mock_update,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Try to press the button
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.lidl_store_123_force_update"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # The mock_update should have been called twice: once for setup, once for button press
        assert mock_update.call_count == 2


async def test_deactivate_coupons_button(hass: HomeAssistant) -> None:
    """Test LidlDeactivateCouponsButton calls deactivate_all_coupons and refreshes."""
    from custom_components.lidl.const import CONF_REFRESH_TOKEN
    from custom_components.lidl.coordinator import LidlDataUpdateCoordinator

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={
            CONF_COUNTRY: "BE",
            CONF_STORE_KEY: "BE123",
            CONF_REFRESH_TOKEN: "tok_1234567890abcdef",
        },
        options={},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
            return_value={"offers": [], "preview_offers": [], "coupons": []},
        ) as mock_update,
        patch.object(
            LidlDataUpdateCoordinator, "deactivate_all_coupons", return_value=3
        ) as mock_deact,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.lidl_plus_account_be_deactivate_all_coupons"},
            blocking=True,
        )
        await hass.async_block_till_done()

        mock_deact.assert_called_once()
        assert mock_update.call_count == 2
