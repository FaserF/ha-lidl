"""Test the Lidl Weekly Offers coordinator."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.api import Offer, PriceBox
from custom_components.lidl.const import CONF_COUNTRY, CONF_STORE_KEY, DOMAIN
from custom_components.lidl.coordinator import LidlDataUpdateCoordinator

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_coordinator_fetch_success(hass: HomeAssistant) -> None:
    """Test successful Lidl offers fetch and parsing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTRY: "DE", CONF_STORE_KEY: "123"},
        options={},
    )
    entry.add_to_hass(hass)

    coordinator = LidlDataUpdateCoordinator(hass, entry)

    # Mock response data with active/preview dates
    today = dt_util.now().date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    next_week = today + timedelta(days=7)

    mock_offer_current = Offer(
        id="offer_current",
        title="Milk",
        brand="Milbona",
        category="Dairy",
        imageUrl="https://lidl.com/milk.png",
        startValidityDate=yesterday.isoformat(),
        endValidityDate=tomorrow.isoformat(),
        priceBox=PriceBox(priceSymbol="€", largePartNumeric=1.29),
    )

    mock_offer_preview = Offer(
        id="offer_preview",
        title="Butter",
        brand="Milbona",
        category="Dairy",
        imageUrl="https://lidl.com/butter.png",
        startValidityDate=tomorrow.isoformat(),
        endValidityDate=next_week.isoformat(),
        priceBox=PriceBox(priceSymbol="€", largePartNumeric=2.19),
    )

    with patch(
        "custom_components.lidl.api.LidlAPIClient.get_offers",
        return_value=[mock_offer_current, mock_offer_preview],
    ):
        res = await coordinator._async_update_data()
        assert len(res["offers"]) == 1
        assert res["offers"][0]["title"] == "Milk"
        assert res["offers"][0]["price"] == "1.29 €"

        assert len(res["preview_offers"]) == 1
        assert res["preview_offers"][0]["title"] == "Butter"
        assert res["preview_offers"][0]["price"] == "2.19 €"


async def test_coordinator_fetch_failure_backoff(hass: HomeAssistant) -> None:
    """Test coordinator handles errors and applies backoff."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTRY: "DE", CONF_STORE_KEY: "123"},
        options={},
    )
    entry.add_to_hass(hass)

    coordinator = LidlDataUpdateCoordinator(hass, entry)

    with patch(
        "custom_components.lidl.api.LidlAPIClient.get_offers",
        side_effect=RuntimeError("API error"),
    ):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator._consecutive_failures == 1
        assert coordinator._backoff_until is not None
