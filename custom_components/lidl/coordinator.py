"""Data Update Coordinator for the Lidl Weekly Offers integration."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import storage
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from lidlplus import LidlPlusApi

from .api import LidlAPIClient, Offer
from .const import (
    CONF_COUNTRY,
    CONF_REFRESH_TOKEN,
    CONF_STORE_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

MIN_UPDATE_INTERVAL = 1
ISSUE_ID_CONNECTION = "connection_error"


class LidlDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage fetching Lidl weekly offers."""

    config_entry: config_entries.ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: config_entries.ConfigEntry) -> None:
        """Initialize coordinator."""
        config = {**entry.data, **entry.options}
        self.store_key: str = config[CONF_STORE_KEY]
        self.country: str = config[CONF_COUNTRY]
        self.refresh_token: str | None = config.get(CONF_REFRESH_TOKEN)
        self.config_entry = entry

        # Anti-ban state
        self._backoff_until: datetime | None = None
        self._consecutive_failures = 0
        self._last_success: datetime | None = None
        self._issue_created = False
        self._force_update = False

        self.store: storage.Store = storage.Store(hass, 1, f"{DOMAIN}_{self.store_key}")

        interval_hours = max(
            MIN_UPDATE_INTERVAL,
            config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )

        # Construct configuration URL dynamically
        self.configuration_url = f"https://www.lidl.{self.country.lower()}/"

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Lidl {self.store_key}",
            update_interval=timedelta(hours=interval_hours),
        )

    async def async_load_cache(self) -> None:
        """Load cached data from HA storage (restart-resistance)."""
        cache = await self.store.async_load()
        if cache:
            required_keys = {"offers", "preview_offers"}
            if not required_keys.issubset(cache.keys()):
                _LOGGER.info(
                    "Lidl cache for store %s is outdated – discarding",
                    self.store_key,
                )
                await self.store.async_remove()
                return

            self.data = cache
            if "last_success" in cache:
                try:
                    self._last_success = dt_util.parse_datetime(cache["last_success"])
                except (ValueError, TypeError):
                    self._last_success = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and split Lidl offers."""
        # Backoff guard
        if (
            not self._force_update
            and self._backoff_until
            and dt_util.now() < self._backoff_until
        ):
            _LOGGER.debug(
                "Skipping Lidl update for store %s – backoff active until %s",
                self.store_key,
                self._backoff_until,
            )
            return self.data

        # Skip if last fetch was very recent
        if not self._force_update and self._last_success is not None:
            time_since = dt_util.now() - self._last_success
            effective_interval = self.update_interval or timedelta(
                hours=DEFAULT_UPDATE_INTERVAL
            )
            if time_since < (effective_interval - timedelta(minutes=5)):
                _LOGGER.info(
                    "Skipping Lidl update for store %s: last success was %d min ago",
                    self.store_key,
                    int(time_since.total_seconds() / 60),
                )
                return self.data

        try:
            domain_data = self.hass.data.setdefault(DOMAIN, {})
            fetch_lock: asyncio.Lock = domain_data.setdefault(
                "fetch_lock", asyncio.Lock()
            )

            async with fetch_lock:
                is_first_fetch = self._last_success is None
                if not self._force_update and not is_first_fetch:
                    jitter = random.uniform(5.0, 15.0)
                    _LOGGER.debug(
                        "Lidl store %s: waiting %.1f s jitter before fetch",
                        self.store_key,
                        jitter,
                    )
                    await asyncio.sleep(jitter)
                else:
                    self._force_update = False

                client = LidlAPIClient(country=self.country)
                offers_list: list[Offer] = await self.hass.async_add_executor_job(
                    client.get_offers, self.store_key
                )

            # Split offers into current and preview based on validity dates
            today_str = dt_util.now().date().isoformat()
            current_offers = []
            preview_offers = []

            for offer in offers_list:
                offer_dict = {
                    "id": offer.id,
                    "title": offer.title,
                    "brand": offer.brand,
                    "category": offer.category,
                    "image_url": offer.image_url,
                    "start_date": offer.start_validity_date[:10]
                    if offer.start_validity_date
                    else None,
                    "end_date": offer.end_validity_date[:10]
                    if offer.end_validity_date
                    else None,
                    "price": offer.price_box.price_val if offer.price_box else "-",
                    "old_price": offer.price_box.old_price_val
                    if offer.price_box
                    else "-",
                    "discount": (offer.price_box.discount_message or "-")
                    if offer.price_box
                    else "-",
                    "packaging": offer.packaging,
                    "price_per_unit": offer.price_per_unit,
                }

                start_date = offer_dict["start_date"]
                if start_date and start_date > today_str:
                    preview_offers.append(offer_dict)
                else:
                    current_offers.append(offer_dict)

            self._last_success = dt_util.now()
            self._consecutive_failures = 0
            data: dict[str, Any] = {
                "offers": current_offers,
                "preview_offers": preview_offers,
                "last_success": self._last_success.isoformat(),
            }

            # Fetch personal Lidl Plus data if authenticated
            if self.refresh_token:
                personal = await self.hass.async_add_executor_job(
                    self._fetch_personal_data
                )
                data.update(personal)

            await self.store.async_save(data)

            if self._issue_created:
                ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID_CONNECTION)
                self._issue_created = False

            return data

        except Exception as err:
            self._consecutive_failures += 1
            status = getattr(err, "status_code", getattr(err, "status", None))
            err_str = str(err).lower()
            if status in (403, 429) or "403" in err_str or "429" in err_str:
                backoff_hours = min(24, self._consecutive_failures * 2)
                self._backoff_until = dt_util.now() + timedelta(hours=backoff_hours)
                _LOGGER.error(
                    "Lidl store %s: rate-limited / blocked. Backing off %d h.",
                    self.store_key,
                    backoff_hours,
                )
            else:
                backoff_minutes = min(240, self._consecutive_failures * 30)
                self._backoff_until = dt_util.now() + timedelta(minutes=backoff_minutes)
                _LOGGER.warning(
                    "Lidl store %s: fetch failed (consecutive: %d). Backing off for %d min. Error: %s",
                    self.store_key,
                    self._consecutive_failures,
                    backoff_minutes,
                    err,
                )

            if self._last_success and (dt_util.now() - self._last_success) > timedelta(
                hours=24
            ):
                if not self._issue_created:
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        ISSUE_ID_CONNECTION,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="connection_error",
                    )
                    self._issue_created = True

            raise UpdateFailed(f"Error communicating with Lidl API: {err}") from err

    def force_update(self) -> None:
        """Force update on next cycle."""
        self._force_update = True
        self._backoff_until = None

    def _get_lidl_plus_api(self) -> LidlPlusApi:
        """Instantiate a LidlPlusApi client using the stored refresh token."""
        lang = self.country.lower()
        return LidlPlusApi(
            language=lang, country=self.country, refresh_token=self.refresh_token
        )

    def _fetch_personal_data(self) -> dict[str, Any]:
        """Synchronously fetch coupons, last receipt and loyalty ID from Lidl Plus."""
        result: dict[str, Any] = {}
        try:
            api = self._get_lidl_plus_api()

            # --- Coupons ---
            try:
                raw_coupons = api.coupons()
                coupon_list = []
                for c in raw_coupons:
                    coupon_list.append(
                        {
                            "id": c.get("id"),
                            "title": c.get("title") or c.get("description"),
                            "description": c.get("description"),
                            "discount": c.get("discountValue") or c.get("discount"),
                            "start_date": c.get("startDate"),
                            "end_date": c.get("endDate"),
                            "activated": c.get("activated", False),
                        }
                    )
                result["coupons"] = coupon_list
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch Lidl Plus coupons: %s", exc)
                result["coupons"] = []

            # --- Loyalty ID ---
            try:
                result["loyalty_id"] = api.loyalty_id
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch Lidl Plus loyalty ID: %s", exc)
                result["loyalty_id"] = None

            # --- Last Receipt ---
            try:
                tickets = api.tickets()
                if tickets:
                    latest = api.ticket(tickets[0]["id"])
                    items = []
                    for item in latest.get("itemsLine", []):
                        items.append(
                            {
                                "name": item.get("description"),
                                "quantity": item.get("quantity"),
                                "price": item.get("currentUnitPrice"),
                            }
                        )
                    result["last_receipt"] = {
                        "id": latest.get("id"),
                        "date": latest.get("date"),
                        "store": latest.get("store", {}).get("name"),
                        "total": latest.get("totalAmount"),
                        "currency": latest.get("currency"),
                        "items": items,
                    }
                else:
                    result["last_receipt"] = None
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch Lidl Plus last receipt: %s", exc)
                result["last_receipt"] = None

        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to initialise Lidl Plus API client: %s", exc)

        return result

    def activate_all_coupons(self) -> int:
        """Activate all available (non-activated) Lidl Plus coupons. Returns count activated."""
        api = self._get_lidl_plus_api()
        activated = 0
        coupons = api.coupons()
        for coupon in coupons:
            cid = coupon.get("id")
            if cid and not coupon.get("activated", False):
                try:
                    api.activate_coupon(cid)
                    activated += 1
                    _LOGGER.debug("Activated Lidl Plus coupon %s", cid)
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("Failed to activate coupon %s: %s", cid, exc)
        return activated
