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


async def test_account_sensors_persist_after_reload(hass: HomeAssistant) -> None:
    """Test account sensors persist when config entry is reloaded."""
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
            }
        ],
    }

    with patch(
        "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
        return_value=mock_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert (
            hass.states.get("sensor.lidl_plus_account_de_activated_coupons") is not None
        )

        # Reload entry (as happens when saving options)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.lidl_plus_account_de_activated_coupons")
        assert state is not None
        assert state.state == "1"


async def test_product_filter_sensor(hass: HomeAssistant) -> None:
    """Test product filter sensor matching and attributes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Store 123",
        data={
            CONF_COUNTRY: "DE",
            CONF_STORE_KEY: "123",
        },
        options={
            "product_filters": ["milbona", "pizza"],
        },
    )
    entry.add_to_hass(hass)

    mock_data = {
        "offers": [
            {
                "id": "1",
                "title": "Milbona Gouda jung",
                "brand": "Milbona",
                "category": "Käse",
                "packaging": "400g Packung",
                "price": "2.49 €",
                "price_per_unit": "6.23 €/kg",
                "image_url": "https://example.com/cheese.jpg",
                "end_date": "2026-08-30",
            },
            {
                "id": "2",
                "title": "Milbona Butter",
                "brand": "Milbona",
                "category": "Molkerei",
                "packaging": "250g",
                "price": "1.89 €",
                "price_per_unit": "7.56 €/kg",
                "image_url": "https://example.com/butter.jpg",
                "end_date": "2026-08-30",
            },
        ],
        "preview_offers": [],
    }

    with patch(
        "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
        return_value=mock_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Match found: Milbona (best price is 1.89 €)
        milbona_state = hass.states.get("sensor.lidl_store_123_offer_milbona")
        assert milbona_state is not None
        assert milbona_state.state == "1.89 €"
        assert milbona_state.attributes["on_sale"] is True
        assert milbona_state.attributes["match_count"] == 2
        assert milbona_state.attributes["best_price"] == "1.89 €"
        assert milbona_state.attributes["filter"] == "milbona"
        assert milbona_state.attributes["product_title"] == "Milbona Butter"
        assert milbona_state.attributes["category"] == "Molkerei"
        assert milbona_state.attributes["base_price"] == "7.56 €/kg"
        assert milbona_state.attributes["valid_until"] == "2026-08-30"
        assert (
            milbona_state.attributes["picture_link"] == "https://example.com/butter.jpg"
        )
        assert len(milbona_state.attributes["matches"]) == 2

        # No match: pizza
        pizza_state = hass.states.get("sensor.lidl_store_123_offer_pizza")
        assert pizza_state is not None
        assert pizza_state.state == "Nicht im Angebot"
        assert pizza_state.attributes["on_sale"] is False
        assert pizza_state.attributes["match_count"] == 0
        assert pizza_state.attributes["best_price"] is None
        assert pizza_state.attributes["product_title"] is None
        assert len(pizza_state.attributes["matches"]) == 0
