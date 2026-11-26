"""Tests for Lidl Plus coupon scoping, multilingual selection, and deactivation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidl.const import (
    CONF_AUTO_ACTIVATE_COUPONS,
    CONF_COUNTRY,
    CONF_FILTER_LOCAL_STORE,
    CONF_LANGUAGE,
    CONF_REFRESH_TOKEN,
    CONF_STORE_KEY,
    DOMAIN,
    language_for_country,
)
from custom_components.lidl.coordinator import LidlDataUpdateCoordinator
from custom_components.lidl.coupons import (
    deactivate_coupon,
    fetch_and_process_coupons,
    is_coupon_activatable,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _resp(payload: object = None, status_code: int = 200, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.json.return_value = payload if payload is not None else {}
    return r


def test_multilingual_belgium_language_override() -> None:
    """language_for_country defaults BE to nl-BE and honors explicit fr-BE/nl-BE preference."""
    assert language_for_country("BE") == "nl-BE"
    assert language_for_country("BE", "fr-BE") == "fr-BE"
    assert language_for_country("BE", "nl-BE") == "nl-BE"
    assert language_for_country("BE", "  ") == "nl-BE"


def test_is_coupon_activatable_skips_locked_and_non_combinable() -> None:
    """Locked, non-activatable, or non-combinable coupons are rejected before activation."""
    assert is_coupon_activatable({"isCombinable": False}, False, True) is False
    assert is_coupon_activatable({"isLocked": True}, False, True) is False
    assert (
        is_coupon_activatable({"availability": {"isActivatable": False}}, False, True)
        is False
    )
    assert is_coupon_activatable({"isActivated": False}, False, True) is True


def test_store_scoping_headers_and_filter_before_activate() -> None:
    """Only local-store eligible coupons are activated when filter_local_store=True."""
    captured_headers: list[dict[str, str]] = []
    activated_urls: list[str] = []

    home_payload = {
        "promotions": {
            "sections": [
                {
                    "name": "AllStores",
                    "promotions": [
                        {
                            "id": "flanders_local",
                            "title": "Flanders Local",
                            "stores": ["BE1001"],
                            "isActivated": False,
                        },
                        {
                            "id": "wallonia_only",
                            "title": "Wallonia Only",
                            "stores": ["BE9999"],
                            "isActivated": False,
                        },
                        {
                            "id": "non_combinable",
                            "title": "Cart Non Combinable",
                            "isCombinable": False,
                            "isActivated": False,
                        },
                    ],
                }
            ]
        }
    }

    def mock_get(url: str, **kwargs: object) -> MagicMock:
        hdrs = kwargs.get("headers", {})
        if isinstance(hdrs, dict):
            captured_headers.append(hdrs)
        if "usersegments" in url:
            return _resp(["segA", "segB"])
        return _resp({})

    def mock_post(url: str, **kwargs: object) -> MagicMock:
        hdrs = kwargs.get("headers", {})
        if isinstance(hdrs, dict):
            captured_headers.append(hdrs)
        if "/activation" in url:
            activated_urls.append(url)
        if "home/logged" in url:
            return _resp(home_payload)
        return _resp({})

    with (
        patch("custom_components.lidl.coupons.requests.get", side_effect=mock_get),
        patch("custom_components.lidl.coupons.requests.post", side_effect=mock_post),
    ):
        coupons, act_count, failed_count, _ = fetch_and_process_coupons(
            access_token="tok",
            country="BE",
            language="nl-BE",
            store_key="BE1001",
            store_name="Lidl Gent",
            store_city="Gent",
            today_str="2026-11-26",
            auto_activate=True,
            skip_special_coupons=True,
            filter_local_store=True,
        )

    assert act_count == 1
    assert failed_count == 0
    assert len(activated_urls) == 1
    assert "flanders_local/activation" in activated_urls[0]
    assert [c["id"] for c in coupons] == ["flanders_local", "non_combinable"]
    home_hdrs = [h for h in captured_headers if "store-id" in h]
    assert home_hdrs
    assert home_hdrs[0]["store-id"] == "BE1001"
    assert home_hdrs[0]["Accept-Language"] == "nl-BE"
    assert home_hdrs[0]["Segment-ids"] == "segA,segB"
    assert home_hdrs[0]["action-location"] == "app_couponslist"


def test_deactivate_coupon_v2_and_v1_fallback() -> None:
    """DELETE deactivates via v2 and falls back to v1 on 404."""
    with patch(
        "custom_components.lidl.coupons.requests.delete",
        side_effect=[_resp(status_code=404), _resp(status_code=204)],
    ) as mock_del:
        ok = deactivate_coupon("tok", "BE", "nl-BE", "BE1001", "c123")

    assert ok is True
    assert mock_del.call_count == 2
    assert "/v2/promotions/c123/activation" in mock_del.call_args_list[0][0][0]
    assert "/v1/promotions/c123/activation" in mock_del.call_args_list[1][0][0]


async def test_deactivate_services_and_language_option(hass: HomeAssistant) -> None:
    """Service calls deactivate_coupon and deactivate_all_coupons work end-to-end."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidl Gent",
        data={
            CONF_COUNTRY: "BE",
            CONF_STORE_KEY: "BE1001",
            CONF_REFRESH_TOKEN: "mock_refresh",
        },
        options={
            CONF_LANGUAGE: "nl-BE",
            CONF_AUTO_ACTIVATE_COUPONS: False,
            CONF_FILTER_LOCAL_STORE: True,
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.lidl.coordinator.LidlDataUpdateCoordinator._async_update_data",
            return_value={"offers": [], "preview_offers": [], "coupons": []},
        ),
        patch.object(
            LidlDataUpdateCoordinator, "deactivate_coupon", return_value=True
        ) as mock_single,
        patch.object(
            LidlDataUpdateCoordinator, "deactivate_all_coupons", return_value=2
        ) as mock_all,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coord = hass.data[DOMAIN][entry.entry_id]
        assert coord.language == "nl-BE"

        await hass.services.async_call(
            DOMAIN,
            "deactivate_coupon",
            {"coupon_id": "c_xyz", "entry_id": entry.entry_id},
            blocking=True,
        )
        mock_single.assert_called_once_with("c_xyz")

        await hass.services.async_call(
            DOMAIN,
            "deactivate_all_coupons",
            {"entry_id": entry.entry_id},
            blocking=True,
        )
        mock_all.assert_called_once()
