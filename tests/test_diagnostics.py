"""Test the Lidl Weekly Offers diagnostics."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.const import CONF_COUNTRY, CONF_STORE_KEY, DOMAIN
from custom_components.lidl.diagnostics import async_get_config_entry_diagnostics

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_diagnostics(hass: HomeAssistant) -> None:
    """Test diagnostics generation and data redact."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={
            CONF_COUNTRY: "DE",
            CONF_STORE_KEY: "123",
            "password": "secret_id",
        },
        options={},
        entry_id="test_entry_id",
    )
    entry.add_to_hass(hass)

    mock_data = {
        "offers": [],
        "preview_offers": [],
    }

    with patch(
        "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
        return_value=mock_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        res = await async_get_config_entry_diagnostics(hass, entry)
        assert res["entry"]["title"] == "Lidl Store 123"
        # Secret password should be redacted
        assert res["entry"]["data"].get("password") != "secret_id"
