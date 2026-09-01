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


async def test_coordinator_preserve_personal_data_on_force_update(
    hass: HomeAssistant,
) -> None:
    """Test preserving cached personal data when card_number options update without refresh_token."""
    from custom_components.lidl.const import CONF_CARD_NUMBER

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTRY: "DE", CONF_STORE_KEY: "123"},
        options={CONF_CARD_NUMBER: "77490000000000000"},
    )
    entry.add_to_hass(hass)

    coordinator = LidlDataUpdateCoordinator(hass, entry)
    coordinator.data = {
        "coupons": [{"id": "c1", "title": "Coupon 1", "activated": True}],
        "last_receipt": {"total": 10.5, "currency": "EUR"},
        "loyalty_id": "old_id",
    }

    with patch(
        "custom_components.lidl.api.LidlAPIClient.get_offers",
        return_value=[],
    ):
        res = await coordinator._async_update_data()
        assert res["loyalty_id"] == "77490000000000000"
        assert len(res["coupons"]) == 1
        assert res["last_receipt"]["total"] == 10.5


async def test_coordinator_auto_activate_coupons(
    hass: HomeAssistant,
) -> None:
    """Test auto-activating coupons during personal data fetch."""
    from custom_components.lidl.const import (
        CONF_AUTO_ACTIVATE_COUPONS,
        CONF_REFRESH_TOKEN,
        CONF_SKIP_SPECIAL_COUPONS,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_COUNTRY: "DE",
            CONF_STORE_KEY: "123",
            CONF_REFRESH_TOKEN: "mock_refresh",
        },
        options={
            CONF_AUTO_ACTIVATE_COUPONS: True,
            CONF_SKIP_SPECIAL_COUPONS: True,
        },
    )
    entry.add_to_hass(hass)

    coordinator = LidlDataUpdateCoordinator(hass, entry)

    mock_promotions_response = {
        "sections": [
            {
                "name": "StoreCoupons",
                "coupons": [
                    {
                        "id": "coupon_1",
                        "title": "Coupon 1",
                        "isActivated": False,
                        "isSpecial": False,
                    },
                    {
                        "id": "coupon_special",
                        "title": "Special Coupon",
                        "isActivated": False,
                        "isSpecial": True,
                    },
                ],
            }
        ]
    }

    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self._json_data = json_data
            self.status_code = status_code

        def json(self):
            return self._json_data

    with (
        patch.object(
            coordinator,
            "_get_access_and_id_token",
            return_value=("mock_access", "mock_id"),
        ),
        patch("curl_cffi.requests.get") as mock_get,
        patch("curl_cffi.requests.post") as mock_post,
    ):
        mock_get.side_effect = lambda url, **kwargs: (
            MockResponse(mock_promotions_response)
            if "promotionslist" in url
            else MockResponse({})
        )
        mock_post.return_value = MockResponse({}, status_code=200)

        personal_data = coordinator._fetch_personal_data()

        activation_posts = [
            call for call in mock_post.call_args_list if "/activation" in call[0][0]
        ]
        assert len(activation_posts) == 1
        assert "coupon_1/activation" in activation_posts[0][0][0]
        # coupon_1 should now be marked activated in the returned list
        c1 = next(c for c in personal_data["coupons"] if c["id"] == "coupon_1")
        assert c1["activated"] is True
        cs = next(c for c in personal_data["coupons"] if c["id"] == "coupon_special")
        assert cs["activated"] is False


async def test_fetch_v2_and_v1_coupons_deduplication_and_filtering(
    hass: HomeAssistant,
) -> None:
    """Test fetching V2 coupons, deduplicating IDs and filtering expired/apologize coupons."""
    from custom_components.lidl.const import (
        CONF_AUTO_ACTIVATE_COUPONS,
        CONF_REFRESH_TOKEN,
        CONF_SKIP_SPECIAL_COUPONS,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_COUNTRY: "ES",
            CONF_STORE_KEY: "ES7019",
            CONF_REFRESH_TOKEN: "mock_refresh",
        },
        options={
            CONF_AUTO_ACTIVATE_COUPONS: False,
            CONF_SKIP_SPECIAL_COUPONS: False,
        },
    )
    entry.add_to_hass(hass)

    coordinator = LidlDataUpdateCoordinator(hass, entry)

    mock_v2_response = {
        "sections": [
            {
                "name": "AllStores",
                "coupons": [
                    {
                        "id": "c_v2_store",
                        "title": "Fresh Meat Discount",
                        "isActivated": False,
                        "discount": {"title": "-30%"},
                        "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                    },
                    {
                        "id": "c_v2_expired",
                        "title": "Old Coupon",
                        "isActivated": False,
                        "validity": {"start": "2020-01-01", "end": "2020-01-02"},
                    },
                    {
                        "id": "c_v2_apologize",
                        "title": "Apologize Coupon",
                        "isActivated": False,
                        "availability": {"apologizeStatus": True},
                    },
                ],
            },
            {
                "name": "OnlineShop",
                "coupons": [
                    {
                        "id": "c_v2_online",
                        "title": "Online Only Discount",
                        "isActivated": True,
                        "isOnlineShop": True,
                        "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                    },
                    {
                        "id": "c_v2_store",  # duplicate in another section
                        "title": "Fresh Meat Discount Duplicate",
                        "isActivated": False,
                        "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                    },
                ],
            },
        ]
    }

    mock_v1_response = {
        "sections": [
            {
                "name": "Promotions",
                "promotions": [
                    {
                        "promotionId": "c_v1_promo",
                        "title": "Special Selection Promo",
                        "isActivated": False,
                        "isSpecial": True,
                        "type": "AssignablePromotion",
                        "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                    },
                    {
                        "promotionId": "c_v2_store",  # duplicate in V1
                        "title": "Fresh Meat Duplicate in V1",
                        "isActivated": False,
                        "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                    },
                ],
            }
        ]
    }

    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self._json_data = json_data
            self.status_code = status_code

        def json(self):
            return self._json_data

    with (
        patch.object(
            coordinator,
            "_get_access_and_id_token",
            return_value=("mock_access", "mock_id"),
        ),
        patch("curl_cffi.requests.get") as mock_get,
    ):

        def _mock_get(url, **kwargs):
            if "promotionslist" in url:
                return MockResponse(mock_v1_response)
            if "/api/v2/ES" in url:
                return MockResponse(mock_v2_response)
            return MockResponse({})

        mock_get.side_effect = _mock_get

        personal_data = coordinator._fetch_personal_data()
        coupons = personal_data["coupons"]

        # Only 3 valid deduplicated coupons: c_v2_store, c_v2_online, c_v1_promo
        assert len(coupons) == 3
        coupon_ids = [c["id"] for c in coupons]
        assert coupon_ids == ["c_v2_store", "c_v2_online", "c_v1_promo"]

        c_online = next(c for c in coupons if c["id"] == "c_v2_online")
        assert c_online["is_online_shop"] is True
        assert c_online["activated"] is True

        c_store = next(c for c in coupons if c["id"] == "c_v2_store")
        assert c_store["is_online_shop"] is False
        assert c_store["discount"] == "-30%"

        c_promo = next(c for c in coupons if c["id"] == "c_v1_promo")
        assert c_promo["is_special"] is True


async def test_fetch_home_logged_and_segmented_coupons(
    hass: HomeAssistant,
) -> None:
    """Test fetching personalized coupons from home/logged using user segments."""
    from custom_components.lidl.const import (
        CONF_AUTO_ACTIVATE_COUPONS,
        CONF_REFRESH_TOKEN,
        CONF_SKIP_SPECIAL_COUPONS,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_COUNTRY: "ES",
            CONF_STORE_KEY: "ES7019",
            CONF_REFRESH_TOKEN: "mock_refresh",
        },
        options={
            CONF_AUTO_ACTIVATE_COUPONS: False,
            CONF_SKIP_SPECIAL_COUPONS: False,
        },
    )
    entry.add_to_hass(hass)

    coordinator = LidlDataUpdateCoordinator(hass, entry)

    mock_home_response = {
        "promotions": {
            "sections": [
                {
                    "name": "PersonalizedSection",
                    "promotions": [
                        {
                            "id": "promo_pan",
                            "title": "Cupón Pan",
                            "discount": {
                                "title": "-15%",
                                "description": "Compra mín. de 100€",
                            },
                            "specialPromotion": {"tag": "CUPÓN PAN🥖🥐"},
                            "isActivated": False,
                            "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                        },
                        {
                            "id": "promo_scratch",
                            "title": "Premio Rasca Plus",
                            "discount": {"title": "-70%"},
                            "specialPromotion": {"tag": "PREMIO"},
                            "isActivated": True,
                            "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                        },
                    ],
                }
            ]
        }
    }

    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self._json_data = json_data
            self.status_code = status_code

        def json(self):
            return self._json_data

    with (
        patch.object(
            coordinator,
            "_get_access_and_id_token",
            return_value=("mock_access", "mock_id"),
        ),
        patch("curl_cffi.requests.get") as mock_get,
        patch("curl_cffi.requests.post") as mock_post,
    ):

        def _mock_get(url, **kwargs):
            if "usersegments" in url:
                return MockResponse(["seg1", "seg2"])
            return MockResponse({})

        def _mock_post(url, **kwargs):
            if "home/logged" in url:
                assert kwargs.get("headers", {}).get("Segment-ids") == "seg1,seg2"
                assert kwargs.get("json", {}).get("storeId") == "ES7019"
                return MockResponse(mock_home_response)
            return MockResponse({})

        mock_get.side_effect = _mock_get
        mock_post.side_effect = _mock_post

        personal_data = coordinator._fetch_personal_data()
        coupons = personal_data["coupons"]

        assert len(coupons) == 2
        pan = next(c for c in coupons if c["id"] == "promo_pan")
        assert pan["title"] == "Cupón Pan"
        assert pan["discount"] == "-15%"
        assert pan["description"] == "Compra mín. de 100€"
        assert pan["is_special"] is True
        assert pan["activated"] is False

        scratch = next(c for c in coupons if c["id"] == "promo_scratch")
        assert scratch["is_special"] is True
        assert scratch["activated"] is True


async def test_activate_all_coupons_with_home_logged(
    hass: HomeAssistant,
) -> None:
    """Test activating all coupons including segmented/home logged promotions."""
    from custom_components.lidl.const import (
        CONF_AUTO_ACTIVATE_COUPONS,
        CONF_REFRESH_TOKEN,
        CONF_SKIP_SPECIAL_COUPONS,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_COUNTRY: "ES",
            CONF_STORE_KEY: "ES7019",
            CONF_REFRESH_TOKEN: "mock_refresh",
        },
        options={
            CONF_AUTO_ACTIVATE_COUPONS: False,
            CONF_SKIP_SPECIAL_COUPONS: False,
        },
    )
    entry.add_to_hass(hass)

    coordinator = LidlDataUpdateCoordinator(hass, entry)

    mock_home_response = {
        "promotions": {
            "sections": [
                {
                    "name": "PersonalizedSection",
                    "promotions": [
                        {
                            "id": "promo_pan",
                            "title": "Cupón Pan",
                            "discount": {"title": "-15%"},
                            "specialPromotion": {"tag": "CUPÓN PAN🥖🥐"},
                            "isActivated": False,
                            "validity": {"start": "2020-01-01", "end": "2099-12-31"},
                        }
                    ],
                }
            ]
        }
    }

    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self._json_data = json_data
            self.status_code = status_code

        def json(self):
            return self._json_data

    with (
        patch.object(
            coordinator,
            "_get_access_and_id_token",
            return_value=("mock_access", "mock_id"),
        ),
        patch("curl_cffi.requests.get") as mock_get,
        patch("curl_cffi.requests.post") as mock_post,
    ):
        mock_get.side_effect = lambda url, **kwargs: (
            MockResponse(["seg1"]) if "usersegments" in url else MockResponse({})
        )

        def _mock_post(url, **kwargs):
            if "home/logged" in url:
                return MockResponse(mock_home_response)
            if "promo_pan/activation" in url:
                return MockResponse({}, status_code=200)
            return MockResponse({})

        mock_post.side_effect = _mock_post

        activated_count = coordinator.activate_all_coupons()
        assert activated_count == 1
