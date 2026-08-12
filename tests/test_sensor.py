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


async def test_personal_coupon_sensors(hass: HomeAssistant) -> None:
    """Test activated and available coupon sensors when logged in."""
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
        "coupons": [
            {
                "id": "c1",
                "title": "Activated Coupon",
                "activated": True,
                "is_online_shop": False,
            },
            {
                "id": "c2",
                "title": "Available Store Coupon",
                "activated": False,
                "is_online_shop": False,
            },
            {
                "id": "c3",
                "title": "Available Online Coupon",
                "activated": False,
                "is_online_shop": True,
            },
        ],
    }

    with patch(
        "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
        return_value=mock_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Check Activated Coupons Sensor
        act_state = hass.states.get("sensor.lidl_plus_account_de_activated_coupons")
        assert act_state is not None
        assert act_state.state == "1"
        assert len(act_state.attributes["coupons"]) == 1
        assert act_state.attributes["coupons"][0]["title"] == "Activated Coupon"

        # Check Available Coupons Sensor
        avail_state = hass.states.get("sensor.lidl_plus_account_de_available_coupons")
        assert avail_state is not None
        assert avail_state.state == "2"
        assert avail_state.attributes["store_coupons_count"] == 1
        assert avail_state.attributes["online_coupons_count"] == 1
        assert avail_state.attributes["special_coupons_count"] == 0
        assert avail_state.attributes["standard_coupons_count"] == 2


async def test_last_receipt_sensor(hass: HomeAssistant) -> None:
    """Test last receipt sensor attributes."""
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
        "last_receipt": {
            "id": "r1",
            "date": "2025-07-05T10:28:16+00:00",
            "store": "Zorneding",
            "store_code": "DE3965",
            "total": 11.07,
            "currency": "EUR",
            "total_amount_formatted": "11,07 €",
            "articles_count": 8,
            "coupons_used_count": 1,
        },
    }

    with patch(
        "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
        return_value=mock_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.lidl_plus_account_de_last_receipt")
        assert state is not None
        assert state.state == "11.07 EUR"
        assert state.attributes["store_code"] == "DE3965"
        assert state.attributes["articles_count"] == 8
        assert state.attributes["coupons_used_count"] == 1
        assert state.attributes["total_amount_formatted"] == "11,07 €"
