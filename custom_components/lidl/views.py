"""HTTP views for Lidl Plus."""

from __future__ import annotations

import logging

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import LidlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class LidlReceiptView(HomeAssistantView):
    """Expose Lidl Plus receipt details."""

    url = "/api/lidl/{entry_id}/receipts/{receipt_id}"
    name = "api:lidl:receipt"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(
        self,
        request,
        entry_id: str,
        receipt_id: str,
    ):
        """Return the details of a receipt."""

        coordinator: LidlDataUpdateCoordinator | None = (
            self.hass.data.get(DOMAIN, {}).get(entry_id)
        )

        if coordinator is None:
            return self.json(
                {"error": "Lidl account not found"},
                status_code=404,
            )

        try:
            receipt = await self.hass.async_add_executor_job(
                coordinator.fetch_receipt_details,
                receipt_id,
            )

            return self.json({
                "receipt_id": receipt_id,
                "receipt": receipt,
            })

        except ValueError:
            return self.json(
                {"error": "Receipt ID not found"},
                status_code=404,
            )

        except Exception:
            _LOGGER.exception(
                "Failed to retrieve Lidl receipt %s",
                receipt_id,
            )

            return self.json(
                {"error": "Failed to retrieve receipt from Lidl"},
                status_code=502,
            )
