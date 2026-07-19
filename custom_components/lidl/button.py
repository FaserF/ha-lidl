"""Lidl Weekly Offers button platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import LidlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up Lidl Weekly Offers buttons from a config entry."""
    coordinator: LidlDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[Any] = [LidlForceUpdateButton(coordinator)]

    if coordinator.refresh_token:
        entities.append(LidlActivateCouponsButton(coordinator))

    async_add_entities(entities, update_before_add=False)


class LidlForceUpdateButton(ButtonEntity):
    """Button to force update Lidl weekly offers."""

    _attr_icon = "mdi:refresh"
    _attr_has_entity_name = True
    _attr_name = "Force Update"

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize the button."""
        self.coordinator = coordinator
        self._store_key = coordinator.store_key
        self._attr_unique_id = f"lidl_{self._store_key}_force_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    async def async_press(self) -> None:
        """Press the button."""
        _LOGGER.info("Forcing Lidl weekly offers update for store %s", self._store_key)
        self.coordinator.force_update()
        await self.coordinator.async_request_refresh()


class LidlActivateCouponsButton(ButtonEntity):
    """Button to activate all available Lidl Plus coupons."""

    _attr_icon = "mdi:ticket-confirmation"
    _attr_has_entity_name = True
    _attr_name = "Activate All Coupons"

    def __init__(self, coordinator: LidlDataUpdateCoordinator) -> None:
        """Initialize the button."""
        self.coordinator = coordinator
        self._store_key = coordinator.store_key
        self._attr_unique_id = f"lidl_{self._store_key}_activate_coupons"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._store_key)},
            name=coordinator.config_entry.title,
            manufacturer="Lidl",
            model="Weekly Offers",
            configuration_url=coordinator.configuration_url,
        )

    async def async_press(self) -> None:
        """Activate all available Lidl Plus coupons."""
        _LOGGER.info("Activating all Lidl Plus coupons for store %s", self._store_key)
        count = await self.coordinator.hass.async_add_executor_job(
            self.coordinator.activate_all_coupons
        )
        _LOGGER.info("Activated %d Lidl Plus coupons", count)
        # Refresh to update coupon sensor state
        self.coordinator.force_update()
        await self.coordinator.async_request_refresh()
