"""Lidl Weekly Offers – Home Assistant Custom Component."""

from __future__ import annotations

import logging

from homeassistant import config_entries, core
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import CONF_STORE_KEY, DOMAIN, PLATFORMS
from .coordinator import LidlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up Lidl Weekly Offers from a config entry."""
    _LOGGER.debug(
        "Setting up Lidl Weekly Offers entry: %s (store_key: %s)",
        entry.entry_id,
        entry.data.get(CONF_STORE_KEY),
    )
    hass.data.setdefault(DOMAIN, {})

    coordinator = LidlDataUpdateCoordinator(hass, entry)
    await coordinator.async_load_cache()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        if not coordinator.data:
            raise ConfigEntryNotReady(
                f"Cannot connect to Lidl API for store {coordinator.store_key}: {err}"
            ) from err
        _LOGGER.warning(
            "Initial Lidl update failed for store %s, using cached data. Error: %s",
            coordinator.store_key,
            err,
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Finished setting up Lidl Weekly Offers entry: %s", entry.entry_id)
    return True


async def _async_update_options(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Reload the entry when options change."""
    _LOGGER.debug(
        "Reloading Lidl entry %s due to option updates. New options: %s",
        entry.entry_id,
        entry.options,
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Lidl Weekly Offers entry: %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    _LOGGER.debug("Unload result for Lidl entry %s: %s", entry.entry_id, unload_ok)
    return unload_ok
