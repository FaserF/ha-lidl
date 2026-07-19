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
