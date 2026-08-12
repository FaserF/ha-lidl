"""Lidl Weekly Offers image platform."""

from __future__ import annotations

import io
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.image import ImageEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, DOMAIN
from .coordinator import LidlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up Lidl Weekly Offers image entities from a config entry."""
    coordinator: LidlDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    if coordinator.refresh_token:
        account_images_set = hass.data[DOMAIN].setdefault(
            "_created_account_images", set()
        )
        if coordinator.account_key not in account_images_set:
            account_images_set.add(coordinator.account_key)
            async_add_entities(
                [LidlLoyaltyCardQrImage(hass, coordinator)], update_before_add=False
            )


class LidlLoyaltyCardQrImage(CoordinatorEntity[LidlDataUpdateCoordinator], ImageEntity):
    """Represents the Lidl Plus loyalty card QR code image entity."""

    _attr_icon = "mdi:qrcode-scan"
    _attr_has_entity_name = True
    _attr_name = "Loyalty Card QR Code"

    def __init__(
        self, hass: HomeAssistant, coordinator: LidlDataUpdateCoordinator
    ) -> None:
        """Initialize loyalty card QR image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)

        self._store_key = coordinator.store_key
        self._account_key = coordinator.account_key
        self._attr_unique_id = f"lidl_{self._account_key}_loyalty_card_qr"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._account_key)},
            name=f"Lidl Plus Account ({coordinator.country})",
            manufacturer="Lidl",
            model="Lidl Plus Customer Account",
            configuration_url=coordinator.account_configuration_url,
        )
        self._cached_png: bytes | None = None
        self._cached_id: str | None = None

    @property
    def loyalty_id(self) -> str | None:
        """Return loyalty card ID from coordinator data."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("loyalty_id")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for loyalty card."""
        data = self.coordinator.data or {}
        profile = data.get("user_profile") or {}
        return {
            "loyalty_id": self.loyalty_id,
            "user_name": profile.get("user_name"),
            "email": profile.get("email"),
            "country": profile.get("country"),
            "registration_date": profile.get("registration_date"),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has loyalty_id."""
        return self.coordinator.data is not None and bool(
            self.coordinator.data.get("loyalty_id")
        )

    def _generate_qr_png(self, text: str) -> bytes:
        """Generate PNG bytes of QR code for given loyalty ID."""
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    async def async_image(self) -> bytes | None:
        """Return bytes of loyalty card QR code image."""
        lid = self.loyalty_id
        if not lid:
            return None

        if self._cached_png is None or self._cached_id != lid:
            self._cached_png = await self.hass.async_add_executor_job(
                self._generate_qr_png, lid
            )
            self._cached_id = lid
            self._attr_image_last_updated = dt_util.now()

        return self._cached_png
