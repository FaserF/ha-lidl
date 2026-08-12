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

        # Construct configuration URL dynamically pointing directly to the store/prospekt page
        city = entry.data.get("city", "")
        address = entry.data.get("address", "")

        if city and address:
            import re

            def slugify(text: str) -> str:
                # Replace German umlauts
                text = text.lower()
                text = (
                    text.replace("ä", "ae")
                    .replace("ö", "oe")
                    .replace("ü", "ue")
                    .replace("ß", "ss")
                )
                # Remove special chars and replace spaces/slashes with dashes
                text = re.sub(r"[^a-z0-9\s-]", "", text)
                text = re.sub(r"[\s/]+", "-", text)
                # Remove trailing or double dashes
                return re.sub(r"-+", "-", text).strip("-")

            slug_city = slugify(city)
            slug_address = slugify(address)
            lang = self.country.lower()

            # Map country codes to their localized store path segment
            path_mapping = {
                "de": "filialen",
                "at": "filialen",
                "ch": "filialen",
                "es": "tiendas",
                "it": "punti-vendita",
                "fr": "supermarches",
                "nl": "filialen",
                "be": "filialen",
                "pl": "sklepy",
                "gb": "stores",
                "ie": "stores",
                "pt": "lojas",
                "ro": "magazine",
                "cz": "prodejny",
                "sk": "predajne",
                "hu": "aruhazak",
                "hr": "trgovine",
                "si": "trgovine",
                "bg": "magazini",
                "gr": "katastimata",
                "dk": "butikker",
                "se": "butiker",
                "fi": "myymalat",
            }
            path_segment = path_mapping.get(lang, "filialen")
            tld = "com" if lang == "gb" else lang

            self.configuration_url = f"https://www.lidl.{tld}/s/{lang}-{self.country}/{path_segment}/{slug_city}/{slug_address}/"
        else:
            tld = "com" if self.country.lower() == "gb" else self.country.lower()
            self.configuration_url = f"https://www.lidl.{tld}/"

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
            has_personal = self.refresh_token is None or (
                self.data and "coupons" in self.data
            )
            if has_personal:
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

    def _get_access_and_id_token(self) -> tuple[str, str]:
        """Exchange stored refresh_token for a fresh access_token and id_token via curl_cffi."""
        import base64

        from curl_cffi import requests

        if not self.refresh_token:
            raise ValueError("Refresh token missing")

        auth_header = base64.b64encode(b"LidlPlusNativeClient:secret").decode()
        res = requests.post(
            "https://accounts.lidl.com/connect/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "LidlPlus/17.0.5 Android okhttp/4.12.0",
            },
            impersonate="chrome110",
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
        return data["access_token"], data.get("id_token", "")

    def _fetch_personal_data(self) -> dict[str, Any]:
        """Fetch coupons, last receipt and loyalty ID from Lidl Plus using curl_cffi."""
        import base64
        import json

        from curl_cffi import requests

        result: dict[str, Any] = {}
        if not self.refresh_token:
            return result

        try:
            access_token, id_token = self._get_access_and_id_token()

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Country": self.country,
                "Accept-Language": f"{self.country.lower()}-{self.country}",
                "App-Version": "17.0.5",
                "Operating-System": "Android",
                "App": "com.lidlplus.app",
            }

            # --- Loyalty ID (Extracted from JWT id_token) ---
            loyalty_id = None
            if id_token:
                try:
                    parts = id_token.split(".")
                    if len(parts) >= 2:
                        payload_b64 = parts[1]
                        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                        loyalty_id = (
                            payload.get("sub")
                            or payload.get("loyalty_id")
                            or payload.get("number")
                        )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to parse JWT id_token for loyalty ID: %s", exc
                    )

            result["loyalty_id"] = str(loyalty_id) if loyalty_id else None

            # --- Coupons ---
            try:
                r_coupons = requests.get(
                    "https://coupons.lidlplus.com/app/api/v1/promotionslist",
                    headers=headers,
                    impersonate="chrome110",
                    timeout=15,
                )
                coupon_list = []
                if r_coupons.status_code == 200:
                    c_data = r_coupons.json()
                    sections = c_data.get("sections", [])
                    for s in sections:
                        for c in s.get("coupons", []) + s.get("promotions", []):
                            cid = c.get("id") or c.get("promotionId")
                            discount_info = c.get("discount", {})
                            discount_val = (
                                discount_info.get("title")
                                if isinstance(discount_info, dict)
                                else str(discount_info)
                            )
                            validity = c.get("validity", {})
                            start_date = (
                                validity.get("start")
                                if isinstance(validity, dict)
                                else None
                            )
                            end_date = (
                                validity.get("end")
                                if isinstance(validity, dict)
                                else None
                            )
                            image_url = c.get("image")
                            c_type = c.get("type")
                            sec_name = s.get("name", "AllStores")
                            is_online = (
                                c.get("isOnlineShop", False) or sec_name == "OnlineShop"
                            )
                            coupon_list.append(
                                {
                                    "id": cid,
                                    "title": c.get("title") or c.get("description"),
                                    "description": c.get("description"),
                                    "discount": discount_val,
                                    "start_date": start_date[:10]
                                    if start_date
                                    else None,
                                    "end_date": end_date[:10] if end_date else None,
                                    "activated": c.get("isActivated", False)
                                    or c.get("activated", False),
                                    "image_url": image_url,
                                    "type": c_type,
                                    "section": sec_name,
                                    "is_online_shop": is_online,
                                }
                            )
                result["coupons"] = coupon_list
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch Lidl Plus coupons: %s", exc)
                result["coupons"] = []

            # --- Last Receipt (Tickets) ---
            try:
                r_tickets = requests.get(
                    f"https://tickets.lidlplus.com/api/v2/{self.country}/tickets?pageNumber=1",
                    headers=headers,
                    impersonate="chrome110",
                    timeout=15,
                )
                if r_tickets.status_code == 200:
                    t_data = r_tickets.json()
                    tickets_list = t_data.get("tickets", [])
                    if tickets_list:
                        latest = tickets_list[0]
                        tid = latest.get("id")
                        # Fetch single ticket details
                        r_single = requests.get(
                            f"https://tickets.lidlplus.com/api/v2/{self.country}/tickets/{tid}",
                            headers=headers,
                            impersonate="chrome110",
                            timeout=15,
                        )
                        items = []
                        store_name = None
                        if r_single.status_code == 200:
                            s_data = r_single.json()
                            store_name = s_data.get("store", {}).get("name")
                            for item in s_data.get("itemsLine", []):
                                items.append(
                                    {
                                        "name": item.get("description"),
                                        "quantity": item.get("quantity"),
                                        "price": item.get("currentUnitPrice"),
                                    }
                                )
                        currency = latest.get("currency", {})
                        curr_code = (
                            currency.get("code")
                            if isinstance(currency, dict)
                            else str(currency)
                        )
                        result["last_receipt"] = {
                            "id": tid,
                            "date": latest.get("date"),
                            "store": store_name or latest.get("storeCode"),
                            "total": latest.get("totalAmount"),
                            "currency": curr_code,
                            "items": items,
                        }
                    else:
                        result["last_receipt"] = None
                else:
                    result["last_receipt"] = None
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch Lidl Plus last receipt: %s", exc)
                result["last_receipt"] = None

        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to fetch Lidl Plus personal data: %s", exc)

        return result

    def activate_all_coupons(self) -> int:
        """Activate all available (non-activated) Lidl Plus coupons. Returns count activated."""
        from curl_cffi import requests

        activated = 0
        if not self.refresh_token:
            return activated

        try:
            access_token, _ = self._get_access_and_id_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Country": self.country,
                "Accept-Language": f"{self.country.lower()}-{self.country}",
                "App-Version": "17.0.5",
                "Operating-System": "Android",
                "App": "com.lidlplus.app",
            }

            r_coupons = requests.get(
                "https://coupons.lidlplus.com/app/api/v1/promotionslist",
                headers=headers,
                impersonate="chrome110",
                timeout=15,
            )
            if r_coupons.status_code == 200:
                c_data = r_coupons.json()
                for s in c_data.get("sections", []):
                    for c in s.get("coupons", []) + s.get("promotions", []):
                        cid = c.get("id") or c.get("promotionId")
                        is_act = c.get("isActivated", False) or c.get(
                            "activated", False
                        )
                        if cid and not is_act:
                            try:
                                r_act = requests.post(
                                    f"https://coupons.lidlplus.com/app/api/v1/promotions/{cid}/activation",
                                    headers=headers,
                                    impersonate="chrome110",
                                    timeout=15,
                                )
                                if r_act.status_code in (200, 201, 204):
                                    activated += 1
                                    _LOGGER.info("Activated Lidl Plus coupon %s", cid)
                            except Exception as exc:  # noqa: BLE001
                                _LOGGER.warning(
                                    "Failed to activate coupon %s: %s", cid, exc
                                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to activate Lidl Plus coupons: %s", exc)

        return activated
