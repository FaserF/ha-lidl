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
        account_created_dict: dict[str, str] = hass.data[DOMAIN].setdefault(
            "_created_account_entities", {}
        )
        if (
            coordinator.account_key not in account_created_dict
            or account_created_dict[coordinator.account_key] == entry.entry_id
        ):
            account_created_dict[coordinator.account_key] = entry.entry_id
            entities += [
                LidlActivatedCouponsSensor(coordinator),
                LidlAvailableCouponsSensor(coordinator),
                LidlLastReceiptSensor(coordinator),
            ]

    for product_filter in coordinator.product_filters:
        entities.append(LidlProductFilterSensor(coordinator, product_filter))

    async_add_entities(entities, update_before_add=False)


class LidlProductFilterSensor(
    CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity
):
    """Represents a product filter offer sensor."""

    _attr_icon = "mdi:tag-search"
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: LidlDataUpdateCoordinator, product_filter: str
    ) -> None:
        """Initialize product filter sensor."""
        super().__init__(coordinator)
        self._store_key = coordinator.store_key
        self._filter = product_filter
        import re

        clean_slug = re.sub(r"[^a-z0-9_]+", "_", product_filter.lower()).strip("_")
        self._attr_name = f"Offer {product_filter}"
        self._attr_unique_id = f"lidl_{self._store_key}_filter_{clean_slug}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    def _get_matches(self) -> list[dict[str, Any]]:
        """Return list of matching offers for this filter."""
        if not self.coordinator.data:
            return []
        offers = self.coordinator.data.get("offers", [])
        filter_term = self._filter.lower().strip()
        if not filter_term:
            return []

        matches: list[dict[str, Any]] = []
        for offer in offers:
            searchable_text = " ".join(
                str(offer.get(field) or "")
                for field in (
                    "title",
                    "brand",
                    "category",
                    "packaging",
                    "price_per_unit",
                    "discount",
                )
            ).lower()
            if filter_term in searchable_text:
                matches.append(offer)
        return matches

    def _parse_price(self, price_str: str | None) -> float | None:
        """Parse numeric price float from string (e.g. '1.49 €', '1,49 €', '1.49')."""
        if not price_str or price_str == "-":
            return None
        import re

        cleaned = price_str.replace("€", "").replace("$", "").replace("£", "").strip()
        match = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                return None
        return None

    @property
    def native_value(self) -> str:
        """Return best price found or 'Nicht im Angebot'."""
        matches = self._get_matches()
        if not matches:
            return "Nicht im Angebot"

        # Find best price among matching offers
        best_price = None
        best_price_numeric = float("inf")

        for m in matches:
            price_val = m.get("price")
            if price_val and price_val != "-":
                num = self._parse_price(str(price_val))
                if num is not None and num < best_price_numeric:
                    best_price_numeric = num
                    best_price = str(price_val)
                elif best_price is None:
                    best_price = str(price_val)

        return best_price if best_price is not None else "Nicht im Angebot"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose product filter attributes."""
        matches = self._get_matches()
        on_sale = len(matches) > 0

        best_match: dict[str, Any] = {}
        best_price = None
        best_price_numeric = float("inf")

        if matches:
            for m in matches:
                price_val = m.get("price")
                if price_val and price_val != "-":
                    num = self._parse_price(str(price_val))
                    if num is not None and num < best_price_numeric:
                        best_price_numeric = num
                        best_price = str(price_val)
                        best_match = m
                    elif not best_match:
                        best_match = m
            if not best_match:
                best_match = matches[0]
            if best_price is None:
                best_price = best_match.get("price")

        return {
            "filter": self._filter,
            "on_sale": on_sale,
            "match_count": len(matches),
            "best_price": best_price,
            "base_price": best_match.get("price_per_unit"),
            "product_title": best_match.get("title"),
            "category": best_match.get("category"),
            "valid_until": best_match.get("end_date"),
            "picture_link": best_match.get("image_url"),
            "matches": matches,
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return self.coordinator.data is not None


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


class LidlActivatedCouponsSensor(
    CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity
):
    """Represents currently activated Lidl Plus coupons."""

    _attr_icon = "mdi:ticket-confirmation"
    _attr_native_unit_of_measurement = "items"
    _attr_has_entity_name = True
    _attr_name = "Activated Coupons"
    _unrecorded_attributes = frozenset({"coupons"})

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._account_key = coordinator.account_key
        self._attr_unique_id = f"lidl_{self._account_key}_activated_coupons"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._account_key)},
            name=f"Lidl Plus Account ({coordinator.country})",
            manufacturer="Lidl",
            model="Lidl Plus Customer Account",
            configuration_url=coordinator.account_configuration_url,
        )

    @property
    def _activated_coupons(self) -> list[dict[str, Any]]:
        """Filter activated coupons from data."""
        if not self.coordinator.data:
            return []
        coupons: list[dict[str, Any]] = self.coordinator.data.get("coupons", [])
        return [c for c in coupons if c.get("activated", False)]

    @property
    def native_value(self) -> int | None:
        """Return the number of activated coupons."""
        if not self.coordinator.data:
            return None
        return len(self._activated_coupons)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of activated coupons."""
        return {
            "coupons": self._activated_coupons,
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return self.coordinator.data is not None and "coupons" in self.coordinator.data


class LidlAvailableCouponsSensor(
    CoordinatorEntity[LidlDataUpdateCoordinator], SensorEntity
):
    """Represents available (non-activated) Lidl Plus coupons."""

    _attr_icon = "mdi:ticket-percent"
    _attr_native_unit_of_measurement = "items"
    _attr_has_entity_name = True
    _attr_name = "Available Coupons"
    _unrecorded_attributes = frozenset(
        {
            "coupons",
            "store_coupons",
            "online_coupons",
            "special_coupons",
            "standard_coupons",
        }
    )

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._account_key = coordinator.account_key
        self._attr_unique_id = f"lidl_{self._account_key}_available_coupons"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._account_key)},
            name=f"Lidl Plus Account ({coordinator.country})",
            manufacturer="Lidl",
            model="Lidl Plus Customer Account",
            configuration_url=coordinator.account_configuration_url,
        )

    @property
    def _available_coupons(self) -> list[dict[str, Any]]:
        """Filter non-activated coupons from data."""
        if not self.coordinator.data:
            return []
        coupons: list[dict[str, Any]] = self.coordinator.data.get("coupons", [])
        return [c for c in coupons if not c.get("activated", False)]

    @property
    def native_value(self) -> int | None:
        """Return the number of available coupons."""
        if not self.coordinator.data:
            return None
        return len(self._available_coupons)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of available coupons."""
        available = self._available_coupons
        store_coupons = [c for c in available if not c.get("is_online_shop", False)]
        online_coupons = [c for c in available if c.get("is_online_shop", False)]
        special_coupons = [c for c in available if c.get("is_special", False)]
        standard_coupons = [c for c in available if not c.get("is_special", False)]

        return {
            "coupons": available,
            "store_coupons": store_coupons,
            "online_coupons": online_coupons,
            "special_coupons": special_coupons,
            "standard_coupons": standard_coupons,
            "store_coupons_count": len(store_coupons),
            "online_coupons_count": len(online_coupons),
            "special_coupons_count": len(special_coupons),
            "standard_coupons_count": len(standard_coupons),
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

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._account_key = coordinator.account_key
        self._attr_unique_id = f"lidl_{self._account_key}_last_receipt"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._account_key)},
            name=f"Lidl Plus Account ({coordinator.country})",
            manufacturer="Lidl",
            model="Lidl Plus Customer Account",
            configuration_url=coordinator.account_configuration_url,
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
            "store_code": receipt.get("store_code"),
            "total": receipt.get("total"),
            "currency": receipt.get("currency"),
            "total_amount_formatted": receipt.get("total_amount_formatted"),
            "articles_count": receipt.get("articles_count"),
            "coupons_used_count": receipt.get("coupons_used_count"),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return (
            self.coordinator.data is not None
            and "last_receipt" in self.coordinator.data
        )
