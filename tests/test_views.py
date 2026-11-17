
"""Test the Lidl Plus HTTP views."""

from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.lidl.const import DOMAIN
from custom_components.lidl.views import LidlReceiptView


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
async def authenticated_client(hass: HomeAssistant, hass_client):
    """Return an authenticated HTTP client."""
    await async_setup_component(hass, "http", {})

    hass.http.register_view(LidlReceiptView(hass))

    client = await hass_client()

    return client


async def test_receipt_view_success(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test successfully retrieving a receipt."""
    receipt = {
        "id": "r1",
        "date": "2026-11-15",
        "store": "Lidl Sheffield",
        "store_code": "1234",
        "items": [
            {
                "name": "Milk",
                "code": "123456",
                "quantity": "1",
                "unit_price": "1.25",
            }
        ],
    }

    coordinator = Mock()
    coordinator.fetch_receipt_details.return_value = receipt

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await authenticated_client.get(
        "/api/lidl/test_entry/receipts/r1"
    )

    assert response.status == 200
    assert await response.json() == {
        "receipt_id": "r1",
        "receipt": receipt,
    }

    coordinator.fetch_receipt_details.assert_called_once_with("r1")


async def test_receipt_view_account_not_found(
    authenticated_client,
) -> None:
    """Test requesting a receipt for an unknown Lidl account."""
    response = await authenticated_client.get(
        "/api/lidl/unknown_entry/receipts/r1"
    )

    assert response.status == 404
    assert await response.json() == {
        "error": "Lidl account not found",
    }


async def test_receipt_view_receipt_not_found(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test requesting a receipt that does not exist."""
    coordinator = Mock()
    coordinator.fetch_receipt_details.side_effect = ValueError(
        "Unknown receipt ID: r999"
    )

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await authenticated_client.get(
        "/api/lidl/test_entry/receipts/r999"
    )

    assert response.status == 404
    assert await response.json() == {
        "error": "Receipt ID not found",
    }

    coordinator.fetch_receipt_details.assert_called_once_with("r999")


async def test_receipt_view_api_failure(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test handling an unexpected Lidl API failure."""
    coordinator = Mock()
    coordinator.fetch_receipt_details.side_effect = RuntimeError(
        "Lidl API unavailable"
    )

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await authenticated_client.get(
        "/api/lidl/test_entry/receipts/r1"
    )

    assert response.status == 502
    assert await response.json() == {
        "error": "Failed to retrieve receipt from Lidl",
    }

    coordinator.fetch_receipt_details.assert_called_once_with("r1")


async def test_receipt_view_unexpected_exception(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test handling an unexpected exception."""
    coordinator = Mock()
    coordinator.fetch_receipt_details.side_effect = Exception(
        "Unexpected internal error"
    )

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await authenticated_client.get(
        "/api/lidl/test_entry/receipts/r1"
    )

    assert response.status == 502
    assert await response.json() == {
        "error": "Failed to retrieve receipt from Lidl",
    }

    coordinator.fetch_receipt_details.assert_called_once_with("r1")
