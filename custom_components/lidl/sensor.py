"""Lidl Weekly Offers sensor platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import LidlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up Lidl Weekly Offers sensors from a config entry."""
    coordinator: LidlDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[Any] = [
        LidlOffersSensor(coordinator),
        LidlOffersPreviewSensor(coordinator),
    ]

    if coordinator.refresh_token:
        entities += [
            LidlCouponsSensor(coordinator),
            LidlLastReceiptSensor(coordinator),
            LidlLoyaltyIdSensor(coordinator),
        ]

    async_add_entities(entities, update_before_add=False)


class LidlOffersSensor(CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity):
    """Represents current Lidl weekly offers."""

    _attr_icon = "mdi:cart-percent"
    _attr_native_unit_of_measurement = "items"
    _attr_has_entity_name = True
    _attr_name = "Offers"
    _unrecorded_attributes = frozenset({"discounts"})

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._store_key = coordinator.store_key
        self._attr_unique_id = f"lidl_{self._store_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    @property
    def native_value(self) -> int | None:
        """Return the number of current offers."""
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.get("offers", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of current offers."""
        data = self.coordinator.data or {}
        config_data = self.coordinator.config_entry.data
        return {
            "store_key": self._store_key,
            "store_name": config_data.get("name"),
            "store_address": config_data.get("address"),
            "store_postal_code": config_data.get("postal_code"),
            "store_city": config_data.get("city"),
            "store_country": config_data.get("country"),
            "discounts": data.get("offers", []),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return self.coordinator.data is not None


class LidlOffersPreviewSensor(
    CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity
):
    """Represents upcoming Lidl weekly offers (preview)."""

    _attr_icon = "mdi:calendar-arrow-right"
    _attr_native_unit_of_measurement = "items"
    _attr_has_entity_name = True
    _attr_name = "Offers Preview"
    _unrecorded_attributes = frozenset({"discounts"})

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._store_key = coordinator.store_key
        self._attr_unique_id = f"lidl_{self._store_key}_preview"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    @property
    def native_value(self) -> int | None:
        """Return the number of preview offers."""
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.get("preview_offers", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of preview offers."""
        data = self.coordinator.data or {}
        config_data = self.coordinator.config_entry.data
        return {
            "store_key": self._store_key,
            "store_name": config_data.get("name"),
            "store_address": config_data.get("address"),
            "store_postal_code": config_data.get("postal_code"),
            "store_city": config_data.get("city"),
            "store_country": config_data.get("country"),
            "discounts": data.get("preview_offers", []),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return self.coordinator.data is not None


class LidlCouponsSensor(CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity):
    """Represents available Lidl Plus personal coupons."""

    _attr_icon = "mdi:ticket-percent"
    _attr_native_unit_of_measurement = "items"
    _attr_has_entity_name = True
    _attr_name = "Coupons"
    _unrecorded_attributes = frozenset({"coupons"})

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._store_key = coordinator.store_key
        self._attr_unique_id = f"lidl_{self._store_key}_coupons"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    @property
    def native_value(self) -> int | None:
        """Return the number of available coupons."""
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.get("coupons", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return coupon details."""
        data = self.coordinator.data or {}
        return {
            "coupons": data.get("coupons", []),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return self.coordinator.data is not None and "coupons" in self.coordinator.data


class LidlLastReceiptSensor(CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity):
    """Represents the last Lidl Plus purchase receipt."""

    _attr_icon = "mdi:receipt"
    _attr_has_entity_name = True
    _attr_name = "Last Receipt"
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._store_key = coordinator.store_key
        self._attr_unique_id = f"lidl_{self._store_key}_last_receipt"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    @property
    def native_value(self) -> str | None:
        """Return the total amount of the last receipt."""
        if not self.coordinator.data:
            return None
        receipt = self.coordinator.data.get("last_receipt")
        if not receipt:
            return None
        total = receipt.get("total")
        currency = receipt.get("currency", "")
        return f"{total} {currency}".strip() if total is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return receipt details."""
        data = self.coordinator.data or {}
        receipt = data.get("last_receipt") or {}
        return {
            "date": receipt.get("date"),
            "store": receipt.get("store"),
            "total": receipt.get("total"),
            "currency": receipt.get("currency"),
            "items": receipt.get("items", []),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return (
            self.coordinator.data is not None
            and "last_receipt" in self.coordinator.data
        )


class LidlLoyaltyIdSensor(CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity):
    """Represents the Lidl Plus loyalty card ID."""

    _attr_icon = "mdi:card-account-details"
    _attr_has_entity_name = True
    _attr_name = "Loyalty Card ID"

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._store_key = coordinator.store_key
        self._attr_unique_id = f"lidl_{self._store_key}_loyalty_id"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    @property
    def native_value(self) -> str | None:
        """Return the loyalty card ID."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("loyalty_id")

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return (
            self.coordinator.data is not None and "loyalty_id" in self.coordinator.data
        )
