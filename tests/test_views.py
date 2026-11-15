
"""Test the Lidl Plus HTTP views."""

from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import hass_client

from custom_components.lidl.const import DOMAIN
from custom_components.lidl.views import LidlReceiptView

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
async def authenticated_client(hass: HomeAssistant):
    """Return an authenticated HTTP test client."""
    client = await hass_client(hass)

    user = await hass.auth.async_create_user("Test User")
    refresh_token = await hass.auth.async_create_refresh_token(user)
    access_token = hass.auth.async_create_access_token(refresh_token)

    hass.http.register_view(LidlReceiptView(hass))

    return client, {
        "Authorization": f"Bearer {access_token}",
    }


async def test_receipt_view_success(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test successfully retrieving receipt details."""
    client, headers = authenticated_client

    receipt = {
        "id": "r1",
        "date": "2026-11-12T08:11:56",
        "store": "Zorneding",
        "store_code": "DE3965",
        "items": [
            {
                "name": "Milk",
                "code": "123456",
                "quantity": 2,
                "unit_price": 1.29,
                "total": 2.58,
            },
            {
                "name": "Bread",
                "code": "654321",
                "quantity": 1,
                "unit_price": 1.49,
                "total": 1.49,
            },
        ],
    }

    coordinator = Mock()
    coordinator.fetch_receipt_details.return_value = receipt

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await client.get(
        "/api/lidl/test_entry/receipts/r1",
        headers=headers,
    )

    assert response.status == 200

    result = await response.json()

    assert result == {
        "receipt_id": "r1",
        "receipt": receipt,
    }

    coordinator.fetch_receipt_details.assert_called_once_with("r1")


async def test_receipt_view_account_not_found(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test retrieving a receipt when the Lidl account does not exist."""
    client, headers = authenticated_client

    response = await client.get(
        "/api/lidl/unknown_entry/receipts/r1",
        headers=headers,
    )

    assert response.status == 404

    result = await response.json()

    assert result == {
        "error": "Lidl account not found",
    }


async def test_receipt_view_receipt_not_found(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test handling an unknown receipt ID."""
    client, headers = authenticated_client

    coordinator = Mock()
    coordinator.fetch_receipt_details.side_effect = ValueError(
        "Unknown receipt ID: r999"
    )

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await client.get(
        "/api/lidl/test_entry/receipts/r999",
        headers=headers,
    )

    assert response.status == 404

    result = await response.json()

    assert result == {
        "error": "Receipt ID not found",
    }

    coordinator.fetch_receipt_details.assert_called_once_with("r999")


async def test_receipt_view_api_failure(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test handling an unexpected Lidl API failure."""
    client, headers = authenticated_client

    coordinator = Mock()
    coordinator.fetch_receipt_details.side_effect = RuntimeError(
        "Lidl API unavailable"
    )

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await client.get(
        "/api/lidl/test_entry/receipts/r1",
        headers=headers,
    )

    assert response.status == 502

    result = await response.json()

    assert result == {
        "error": "Failed to retrieve receipt from Lidl",
    }

    coordinator.fetch_receipt_details.assert_called_once_with("r1")


async def test_receipt_view_unexpected_exception(
    hass: HomeAssistant,
    authenticated_client,
) -> None:
    """Test handling an unexpected exception during receipt retrieval."""
    client, headers = authenticated_client

    coordinator = Mock()
    coordinator.fetch_receipt_details.side_effect = Exception(
        "Unexpected internal error"
    )

    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    response = await client.get(
        "/api/lidl/test_entry/receipts/r1",
        headers=headers,
    )

    assert response.status == 502

    result = await response.json()

    assert result == {
        "error": "Failed to retrieve receipt from Lidl",
    }
