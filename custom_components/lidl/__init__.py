"""Lidl Weekly Offers – Home Assistant Custom Component."""

from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant import config_entries, core
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_COUNTRY,
    CONF_STORE_KEY,
    DISCOVERY_RADIUS_KM,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import LidlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Lidl Plus API supported country codes
_SUPPORTED_COUNTRIES = {"DE", "AT", "ES", "FR", "NL", "PL"}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in km between two GPS coordinates."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def async_setup(hass: core.HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Lidl integration.

    When 'lidl:' is listed in configuration.yaml (zero-entry bootstrap),
    this is the only hook HA calls.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("_discovery_scheduled"):
        domain_data["_discovery_scheduled"] = True

        async def _on_ha_started(event: core.Event) -> None:  # noqa: RUF100
            await _async_discover_stores(hass)

        if hass.is_running:
            hass.async_create_task(_async_discover_stores(hass))
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)

    return True


async def _async_discover_stores(hass: core.HomeAssistant) -> None:
    """Search for the nearest Lidl store and trigger integration discovery."""
    ha_lat = hass.config.latitude
    ha_lon = hass.config.longitude

    if not ha_lat or not ha_lon:
        _LOGGER.debug("Lidl discovery: HA home location not set, skipping")
        return

    # Build search query: ZIP code is most reliable for the store API.
    zip_code: str = getattr(hass.config, "zip_code", "") or ""
    location_name: str = hass.config.location_name or ""
    query = zip_code.strip() or location_name.strip()
    if not query:
        _LOGGER.debug(
            "Lidl discovery: no ZIP code or location_name configured, skipping"
        )
        return

    # Derive country from HA system setting; fall back to "DE" if unsupported
    ha_country: str = (getattr(hass.config, "country", None) or "DE").upper()
    country = ha_country if ha_country in _SUPPORTED_COUNTRIES else "DE"

    _LOGGER.debug(
        "Lidl discovery: searching stores (country: %s)", country
    )

    from .api import LidlAPIClient, Store

    try:
        client = LidlAPIClient(country=country)
        stores: list[Store] = await hass.async_add_executor_job(
            client.search_stores, query
        )
    except Exception as exc:
        _LOGGER.debug("Lidl discovery: API error during search: %s", exc)
        return

    configured_keys = {
        entry.data.get(CONF_STORE_KEY)
        for entry in hass.config_entries.async_entries(DOMAIN)
    }

    # Collect ALL stores within radius (including already-configured ones)
    # so we can determine the true geographic nearest before deciding.
    candidates: list[tuple[float, Store]] = []
    for store in stores:
        if not store.store_key:
            continue

        dist = DISCOVERY_RADIUS_KM  # default if no coords available
        if (
            store.location is not None
            and store.location.latitude is not None
            and store.location.longitude is not None
        ):
            try:
                dist = _haversine_km(
                    ha_lat,
                    ha_lon,
                    store.location.latitude,
                    store.location.longitude,
                )
            except (TypeError, ValueError):
                pass  # keep default distance → included

        if dist <= DISCOVERY_RADIUS_KM:
            candidates.append((dist, store))

    if not candidates:
        _LOGGER.debug(
            "Lidl discovery: no stores found within %.0f km", DISCOVERY_RADIUS_KM
        )
        return

    candidates.sort(key=lambda t: t[0])
    nearest_dist, nearest = candidates[0]

    # If the geographically nearest store is already configured, stop entirely.
    if nearest.store_key in configured_keys:
        _LOGGER.debug(
            "Lidl discovery: nearest store %s is already configured, skipping discovery",
            nearest.store_key,
        )
        return

    _LOGGER.debug(
        "Lidl discovery: triggering flow for nearest store %s (%s, %.1f km)",
        nearest.store_key,
        nearest.name,
        nearest_dist,
    )
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={
                CONF_STORE_KEY: nearest.store_key,
                CONF_COUNTRY: country,
                "name": nearest.name,
                "address": nearest.address,
                "postal_code": nearest.postal_code,
                "city": nearest.locality,
            },
        )
    )


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

    domain_data = hass.data[DOMAIN]
    if not domain_data.get("_discovery_scheduled"):
        domain_data["_discovery_scheduled"] = True

        async def _on_ha_started(event: core.Event) -> None:  # noqa: RUF100
            await _async_discover_stores(hass)

        if hass.is_running:
            hass.async_create_task(_async_discover_stores(hass))
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)

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
