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
    CONF_AUTO_ACTIVATE_COUPONS,
    CONF_CARD_NUMBER,
    CONF_COUNTRY,
    CONF_PRODUCT_FILTERS,
    CONF_REFRESH_TOKEN,
    CONF_SKIP_SPECIAL_COUPONS,
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
    configuration_url: str

    def __init__(self, hass: HomeAssistant, entry: config_entries.ConfigEntry) -> None:
        """Initialize coordinator."""
        config = {**entry.data, **entry.options}
        self.store_key: str = config[CONF_STORE_KEY]
        self.country: str = config[CONF_COUNTRY]
        self.refresh_token: str | None = config.get(CONF_REFRESH_TOKEN)
        self.auto_activate_coupons: bool = config.get(CONF_AUTO_ACTIVATE_COUPONS, False)
        self.skip_special_coupons: bool = config.get(CONF_SKIP_SPECIAL_COUPONS, True)
        self.card_number: str | None = config.get(CONF_CARD_NUMBER)
        self.product_filters: list[str] = config.get(CONF_PRODUCT_FILTERS, [])
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

    @property
    def account_configuration_url(self) -> str:
        """Return dynamic country-specific Lidl Plus web account configuration URL."""
        country_lower = self.country.lower()
        tld = "com" if country_lower == "gb" else country_lower
        client_name_map = {
            "de": "GermanyEcommerceClient",
            "at": "AustriaEcommerceClient",
            "ch": "SwitzerlandEcommerceClient",
            "nl": "NetherlandsEcommerceClient",
            "be": "BelgiumEcommerceClient",
            "fr": "FranceEcommerceClient",
            "es": "SpainEcommerceClient",
            "it": "ItalyEcommerceClient",
            "gb": "UkEcommerceClient",
        }
        client_id = client_name_map.get(
            country_lower, f"{self.country.title()}EcommerceClient"
        )
        return f"https://www.lidl.{tld}/mla/?country_code={country_lower}&language={country_lower}-{self.country}&client_id={client_id}"

    @property
    def account_key(self) -> str:
        """Return unique key for the Lidl Plus account per country."""
        if not self.refresh_token:
            return f"account_{self.country.lower()}"
        token_prefix = self.refresh_token[:16]
        return f"account_{self.country.lower()}_{token_prefix}"

    @property
    def is_data_valid(self) -> bool:
        """Return True if cached data is still valid for the current week (until Sunday 23:59:59)."""
        if not self.data:
            return False

        now = dt_util.now()
        current_monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if self._last_success and self._last_success >= current_monday:
            return True

        valid_until = self.data.get("valid_until")
        if valid_until:
            try:
                val_date = dt_util.parse_date(str(valid_until).split("T")[0])
                if val_date and val_date >= now.date():
                    return True
            except Exception:  # noqa: BLE001
                pass

        return False

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
            elif self.data:
                for key in ("coupons", "last_receipt", "user_profile"):
                    if key in self.data:
                        data[key] = self.data[key]
                data["loyalty_id"] = self.card_number or self.data.get("loyalty_id")
            elif self.card_number:
                data["loyalty_id"] = self.card_number

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

            # If we have valid cached data for the current week, fall back to it so entities stay available
            if self.is_data_valid and self.data:
                _LOGGER.warning(
                    "Lidl store %s: fetch failed, but cached data for the current week is valid – continuing with cached data. Error: %s",
                    self.store_key,
                    err,
                )
                return self.data

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

            # --- Loyalty ID & Customer Profile (Extracted from JWT access_token & id_token) ---
            loyalty_id = None
            user_name = None
            user_email = None
            user_country = None
            reg_date = None

            # Try parsing access_token first (contains name, given_name, family_name, email, etc.)
            for token_str in [access_token, id_token]:
                if not token_str:
                    continue
                try:
                    parts = token_str.split(".")
                    if len(parts) >= 2:
                        payload_b64 = parts[1]
                        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

                        if not loyalty_id:
                            loyalty_id = (
                                payload.get("sub")
                                or payload.get("loyalty_id")
                                or payload.get("number")
                            )

                        if not user_name:
                            given = payload.get("given_name") or payload.get("name", "")
                            family = payload.get("family_name", "")
                            if given or family:
                                user_name = f"{given} {family}".strip()

                        if not user_email:
                            user_email = payload.get("email")

                        if not user_country:
                            user_country = payload.get(
                                "address_country"
                            ) or payload.get("country")

                        if not reg_date:
                            reg_date = payload.get("registration_date") or payload.get(
                                "registrationDate"
                            )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to parse JWT token for user profile: %s", exc
                    )

            result["loyalty_id"] = self.card_number or (
                str(loyalty_id) if loyalty_id else None
            )
            result["user_profile"] = {
                "user_name": user_name,
                "email": user_email,
                "country": user_country,
                "registration_date": reg_date,
            }

            # --- Coupons ---
            try:
                coupon_list: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                today_str = dt_util.now().date().isoformat()

                # 1. User Segments & Home Logged Promotions (Personalized & Segmented offers)
                seg_header = ""
                try:
                    r_seg = requests.get(
                        f"https://segments.lidlplus.com/api/v1/usersegments/{self.country}",
                        headers={"Authorization": f"Bearer {access_token}"},
                        impersonate="chrome110",
                        timeout=10,
                    )
                    if r_seg.status_code == 200:
                        segments = r_seg.json()
                        if isinstance(segments, list):
                            seg_header = ",".join(
                                str(s) for s in segments if s is not None
                            )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("Failed to fetch Lidl Plus user segments: %s", exc)

                try:
                    home_headers = dict(headers)
                    if seg_header:
                        home_headers["Segment-ids"] = seg_header
                    home_payload = {
                        "storeId": self.store_key,
                        "modules": [
                            {"moduleName": "promotions", "aggregateVersion": 4}
                        ],
                    }
                    r_home = requests.post(
                        f"https://home.lidlplus.com/api/v2/{self.country}/home/logged",
                        headers=home_headers,
                        json=home_payload,
                        impersonate="chrome110",
                        timeout=15,
                    )
                    if r_home.status_code == 200:
                        home_data = r_home.json()
                        promo_module = (
                            home_data.get("promotions", {})
                            if isinstance(home_data, dict)
                            else {}
                        )
                        sections = (
                            promo_module.get("sections", [])
                            if isinstance(promo_module, dict)
                            else []
                        )
                        for s in sections:
                            sec_name = (
                                s.get("name")
                                or s.get("title")
                                or s.get("header")
                                or "AllStores"
                            )
                            for c in s.get("promotions", []) + s.get("coupons", []):
                                cid = str(
                                    c.get("id") or c.get("promotionId", "")
                                ).strip()
                                if not cid or cid in seen_ids:
                                    continue

                                avail = c.get("availability", {})
                                if (
                                    isinstance(avail, dict)
                                    and avail.get("apologizeStatus", False)
                                ) or c.get("apologizeStatus", False):
                                    continue

                                validity = c.get("validity", {})
                                start_raw = (
                                    validity.get("start")
                                    if isinstance(validity, dict)
                                    else (
                                        c.get("startValidityDate") or c.get("startDate")
                                    )
                                )
                                end_raw = (
                                    validity.get("end")
                                    if isinstance(validity, dict)
                                    else (c.get("endValidityDate") or c.get("endDate"))
                                )
                                start_date = start_raw[:10] if start_raw else None
                                end_date = end_raw[:10] if end_raw else None

                                if end_date and end_date < today_str:
                                    continue
                                if start_date and start_date > today_str:
                                    continue

                                discount_info = c.get("discount", {})
                                discount_val = (
                                    discount_info.get("title")
                                    if isinstance(discount_info, dict)
                                    else (
                                        discount_info
                                        or c.get("discountTitle")
                                        or c.get("offerTitle")
                                    )
                                )
                                desc = c.get("description")
                                if not desc and isinstance(discount_info, dict):
                                    desc = discount_info.get("description")

                                image_url = (
                                    c.get("image")
                                    or c.get("imageUrl")
                                    or (
                                        c.get("images", [{}])[0].get("url")
                                        if isinstance(c.get("images"), list)
                                        and c.get("images")
                                        and isinstance(c.get("images")[0], dict)
                                        else None
                                    )
                                )
                                c_type = c.get("type") or "Standard"
                                special_obj = c.get("specialPromotion")
                                special_tag = (
                                    special_obj.get("tag")
                                    if isinstance(special_obj, dict)
                                    else None
                                )
                                is_online = bool(
                                    c.get("isOnlineShop", False)
                                ) or sec_name.lower() in ("onlineshop", "online")
                                is_act = bool(
                                    c.get("isActivated", False)
                                    or c.get("activated", False)
                                )
                                is_special = bool(
                                    c.get("isSpecial", False)
                                    or special_tag
                                    or c_type in ("Special", "AssignablePromotion")
                                )

                                if self.auto_activate_coupons and not is_act:
                                    if is_special and self.skip_special_coupons:
                                        _LOGGER.info(
                                            "Skipping special selection coupon %s based on configuration",
                                            cid,
                                        )
                                    else:
                                        try:
                                            r_act = requests.post(
                                                f"https://coupons.lidlplus.com/app/api/v1/promotions/{cid}/activation",
                                                headers=headers,
                                                json={},
                                                impersonate="chrome110",
                                                timeout=15,
                                            )
                                            if r_act.status_code in (200, 201, 204):
                                                is_act = True
                                                _LOGGER.info(
                                                    "Auto-activated Lidl Plus coupon %s",
                                                    cid,
                                                )
                                        except Exception as exc:  # noqa: BLE001
                                            _LOGGER.warning(
                                                "Failed to auto-activate coupon %s: %s",
                                                cid,
                                                exc,
                                            )

                                seen_ids.add(cid)
                                coupon_list.append(
                                    {
                                        "id": cid,
                                        "title": c.get("title")
                                        or c.get("name")
                                        or desc,
                                        "description": desc,
                                        "discount": discount_val,
                                        "start_date": start_date,
                                        "end_date": end_date,
                                        "activated": is_act,
                                        "image_url": image_url,
                                        "type": c_type,
                                        "section": sec_name,
                                        "is_online_shop": is_online,
                                        "is_special": is_special,
                                    }
                                )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to fetch Lidl Plus Home Logged coupons: %s", exc
                    )

                # 2. Standard Lidl Plus Coupons (V2 API)
                try:
                    r_v2 = requests.get(
                        f"https://coupons.lidlplus.com/api/v2/{self.country}",
                        headers=headers,
                        impersonate="chrome110",
                        timeout=15,
                    )
                    if r_v2.status_code == 200:
                        v2_data = r_v2.json()
                        v2_sections = (
                            v2_data.get("sections", [])
                            if isinstance(v2_data, dict)
                            else []
                        )
                        for s in v2_sections:
                            sec_name = s.get("name") or s.get("title") or "AllStores"
                            for c in s.get("coupons", []):
                                cid = str(c.get("id", "")).strip()
                                if not cid or cid in seen_ids:
                                    continue

                                avail = c.get("availability", {})
                                if (
                                    isinstance(avail, dict)
                                    and avail.get("apologizeStatus", False)
                                ) or c.get("apologizeStatus", False):
                                    continue

                                validity = c.get("validity", {})
                                start_raw = (
                                    c.get("startValidityDate")
                                    or (
                                        validity.get("start")
                                        if isinstance(validity, dict)
                                        else None
                                    )
                                    or c.get("startDate")
                                )
                                end_raw = (
                                    c.get("endValidityDate")
                                    or (
                                        validity.get("end")
                                        if isinstance(validity, dict)
                                        else None
                                    )
                                    or c.get("endDate")
                                )
                                start_date = start_raw[:10] if start_raw else None
                                end_date = end_raw[:10] if end_raw else None

                                if end_date and end_date < today_str:
                                    continue
                                if start_date and start_date > today_str:
                                    continue

                                discount_info = c.get("discount", {})
                                discount_val = (
                                    discount_info.get("title")
                                    if isinstance(discount_info, dict)
                                    else (
                                        discount_info
                                        or c.get("discountTitle")
                                        or c.get("offerTitle")
                                    )
                                )
                                desc = c.get("description")
                                if not desc and isinstance(discount_info, dict):
                                    desc = discount_info.get("description")

                                image_url = c.get("image") or c.get("imageUrl")
                                c_type = c.get("type", "Standard")
                                is_online = bool(
                                    c.get("isOnlineShop", False)
                                ) or sec_name.lower() in ("onlineshop", "online")
                                is_act = bool(
                                    c.get("isActivated", False)
                                    or c.get("activated", False)
                                )
                                is_special = bool(
                                    c.get("isSpecial", False)
                                    or c_type in ("Special", "AssignablePromotion")
                                )

                                if self.auto_activate_coupons and not is_act:
                                    if is_special and self.skip_special_coupons:
                                        _LOGGER.info(
                                            "Skipping special selection coupon %s based on configuration",
                                            cid,
                                        )
                                    else:
                                        try:
                                            r_act = requests.post(
                                                f"https://coupons.lidlplus.com/api/v1/{self.country}/{cid}/activation",
                                                headers=headers,
                                                impersonate="chrome110",
                                                timeout=15,
                                            )
                                            if r_act.status_code in (200, 201, 204):
                                                is_act = True
                                                _LOGGER.info(
                                                    "Auto-activated Lidl Plus coupon %s",
                                                    cid,
                                                )
                                        except Exception as exc:  # noqa: BLE001
                                            _LOGGER.warning(
                                                "Failed to auto-activate coupon %s: %s",
                                                cid,
                                                exc,
                                            )

                                seen_ids.add(cid)
                                coupon_list.append(
                                    {
                                        "id": cid,
                                        "title": c.get("title")
                                        or c.get("name")
                                        or desc,
                                        "description": desc,
                                        "discount": discount_val,
                                        "start_date": start_date,
                                        "end_date": end_date,
                                        "activated": is_act,
                                        "image_url": image_url,
                                        "type": c_type,
                                        "section": sec_name,
                                        "is_online_shop": is_online,
                                        "is_special": is_special,
                                    }
                                )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("Failed to fetch Lidl Plus V2 coupons: %s", exc)

                # 3. V1 Promotions list
                try:
                    r_v1 = requests.get(
                        "https://coupons.lidlplus.com/app/api/v1/promotionslist",
                        headers=headers,
                        impersonate="chrome110",
                        timeout=15,
                    )
                    if r_v1.status_code == 200:
                        c_data = r_v1.json()
                        sections = (
                            c_data.get("sections", [])
                            if isinstance(c_data, dict)
                            else []
                        )
                        for s in sections:
                            sec_name = s.get("name") or s.get("title") or "AllStores"
                            for c in s.get("coupons", []) + s.get("promotions", []):
                                cid = str(
                                    c.get("id") or c.get("promotionId", "")
                                ).strip()
                                if not cid or cid in seen_ids:
                                    continue

                                avail = c.get("availability", {})
                                if (
                                    isinstance(avail, dict)
                                    and avail.get("apologizeStatus", False)
                                ) or c.get("apologizeStatus", False):
                                    continue

                                validity = c.get("validity", {})
                                start_raw = (
                                    validity.get("start")
                                    if isinstance(validity, dict)
                                    else c.get("startValidityDate")
                                )
                                end_raw = (
                                    validity.get("end")
                                    if isinstance(validity, dict)
                                    else c.get("endValidityDate")
                                )
                                start_date = start_raw[:10] if start_raw else None
                                end_date = end_raw[:10] if end_raw else None

                                if end_date and end_date < today_str:
                                    continue
                                if start_date and start_date > today_str:
                                    continue

                                discount_info = c.get("discount", {})
                                discount_val = (
                                    discount_info.get("title")
                                    if isinstance(discount_info, dict)
                                    else (
                                        discount_info
                                        or c.get("discountTitle")
                                        or c.get("offerTitle")
                                    )
                                )
                                desc = c.get("description")
                                if not desc and isinstance(discount_info, dict):
                                    desc = discount_info.get("description")

                                image_url = c.get("image") or c.get("imageUrl")
                                c_type = c.get("type") or "Standard"
                                is_online = bool(
                                    c.get("isOnlineShop", False)
                                ) or sec_name.lower() in ("onlineshop", "online")
                                is_act = bool(
                                    c.get("isActivated", False)
                                    or c.get("activated", False)
                                )
                                is_special = bool(
                                    c.get("isSpecial", False)
                                    or c_type in ("Special", "AssignablePromotion")
                                )

                                if self.auto_activate_coupons and not is_act:
                                    if is_special and self.skip_special_coupons:
                                        _LOGGER.info(
                                            "Skipping special selection coupon %s based on configuration",
                                            cid,
                                        )
                                    else:
                                        try:
                                            act_payload: dict[str, Any] = {}
                                            r_act = requests.post(
                                                f"https://coupons.lidlplus.com/app/api/v1/promotions/{cid}/activation",
                                                headers=headers,
                                                json=act_payload,
                                                impersonate="chrome110",
                                                timeout=15,
                                            )
                                            if r_act.status_code in (200, 201, 204):
                                                is_act = True
                                                _LOGGER.info(
                                                    "Auto-activated Lidl Plus coupon %s",
                                                    cid,
                                                )
                                        except Exception as exc:  # noqa: BLE001
                                            _LOGGER.warning(
                                                "Failed to auto-activate coupon %s: %s",
                                                cid,
                                                exc,
                                            )

                                seen_ids.add(cid)
                                coupon_list.append(
                                    {
                                        "id": cid,
                                        "title": c.get("title") or desc,
                                        "description": desc,
                                        "discount": discount_val,
                                        "start_date": start_date,
                                        "end_date": end_date,
                                        "activated": is_act,
                                        "image_url": image_url,
                                        "type": c_type,
                                        "section": sec_name,
                                        "is_online_shop": is_online,
                                        "is_special": is_special,
                                    }
                                )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("Failed to fetch Lidl Plus V1 promotions: %s", exc)

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
                        store_code = latest.get("storeCode")
                        store_name = None
                        if store_code:
                            try:
                                r_store = requests.get(
                                    f"https://stores.lidlplus.com/api/v1/{self.country}/{store_code}",
                                    headers=headers,
                                    impersonate="chrome110",
                                    timeout=5,
                                )
                                if r_store.status_code == 200:
                                    st_data = r_store.json()
                                    s_name = st_data.get("name")
                                    s_locality = st_data.get("locality")
                                    if (
                                        s_name
                                        and s_locality
                                        and s_locality not in s_name
                                    ):
                                        store_name = f"{s_locality} - {s_name}"
                                    else:
                                        store_name = s_name or s_locality
                            except Exception as exc:  # noqa: BLE001
                                _LOGGER.debug(
                                    "Failed to resolve store name for %s: %s",
                                    store_code,
                                    exc,
                                )

                        currency = latest.get("currency", {})
                        curr_code = (
                            currency.get("code")
                            if isinstance(currency, dict)
                            else str(currency)
                        )
                        curr_symbol = (
                            currency.get("symbol", curr_code)
                            if isinstance(currency, dict)
                            else curr_code
                        )
                        total_val = latest.get("totalAmount")
                        formatted_total = (
                            f"{total_val:.2f} {curr_symbol}".replace(".", ",")
                            if isinstance(total_val, (int, float))
                            else f"{total_val} {curr_symbol}".strip()
                        )
                        result["last_receipt"] = {
                            "id": tid,
                            "date": latest.get("date"),
                            "store": store_name or store_code,
                            "store_code": store_code,
                            "total": total_val,
                            "currency": curr_code,
                            "total_amount_formatted": formatted_total,
                            "articles_count": latest.get("articlesCount", 0),
                            "coupons_used_count": latest.get("couponsUsedCount", 0),
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
            seen_ids: set[str] = set()
            today_str = dt_util.now().date().isoformat()

            # 1. Activate Home Logged & Segmented promotions
            seg_header = ""
            try:
                r_seg = requests.get(
                    f"https://segments.lidlplus.com/api/v1/usersegments/{self.country}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    impersonate="chrome110",
                    timeout=10,
                )
                if r_seg.status_code == 200:
                    segments = r_seg.json()
                    if isinstance(segments, list):
                        seg_header = ",".join(str(s) for s in segments if s is not None)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to fetch Lidl Plus user segments for activation: %s", exc
                )

            try:
                home_headers = dict(headers)
                if seg_header:
                    home_headers["Segment-ids"] = seg_header
                home_payload = {
                    "storeId": self.store_key,
                    "modules": [{"moduleName": "promotions", "aggregateVersion": 4}],
                }
                r_home = requests.post(
                    f"https://home.lidlplus.com/api/v2/{self.country}/home/logged",
                    headers=home_headers,
                    json=home_payload,
                    impersonate="chrome110",
                    timeout=15,
                )
                if r_home.status_code == 200:
                    home_data = r_home.json()
                    promo_module = (
                        home_data.get("promotions", {})
                        if isinstance(home_data, dict)
                        else {}
                    )
                    sections = (
                        promo_module.get("sections", [])
                        if isinstance(promo_module, dict)
                        else []
                    )
                    for s in sections:
                        for c in s.get("promotions", []) + s.get("coupons", []):
                            cid = str(c.get("id") or c.get("promotionId", "")).strip()
                            if not cid or cid in seen_ids:
                                continue
                            seen_ids.add(cid)

                            avail = c.get("availability", {})
                            if (
                                isinstance(avail, dict)
                                and avail.get("apologizeStatus", False)
                            ) or c.get("apologizeStatus", False):
                                continue

                            validity = c.get("validity", {})
                            start_raw = (
                                validity.get("start")
                                if isinstance(validity, dict)
                                else (c.get("startValidityDate") or c.get("startDate"))
                            )
                            end_raw = (
                                validity.get("end")
                                if isinstance(validity, dict)
                                else (c.get("endValidityDate") or c.get("endDate"))
                            )
                            start_date = start_raw[:10] if start_raw else None
                            end_date = end_raw[:10] if end_raw else None
                            if end_date and end_date < today_str:
                                continue
                            if start_date and start_date > today_str:
                                continue

                            is_act = bool(
                                c.get("isActivated", False) or c.get("activated", False)
                            )
                            c_type = c.get("type") or "Standard"
                            special_obj = c.get("specialPromotion")
                            special_tag = (
                                special_obj.get("tag")
                                if isinstance(special_obj, dict)
                                else None
                            )
                            is_special = bool(
                                c.get("isSpecial", False)
                                or special_tag
                                or c_type in ("Special", "AssignablePromotion")
                            )

                            if not is_act:
                                if is_special and self.skip_special_coupons:
                                    _LOGGER.info(
                                        "Skipping special selection coupon %s based on configuration",
                                        cid,
                                    )
                                    continue
                                try:
                                    r_act = requests.post(
                                        f"https://coupons.lidlplus.com/app/api/v1/promotions/{cid}/activation",
                                        headers=headers,
                                        json={},
                                        impersonate="chrome110",
                                        timeout=15,
                                    )
                                    if r_act.status_code in (200, 201, 204):
                                        activated += 1
                                        _LOGGER.info(
                                            "Activated Lidl Plus coupon %s", cid
                                        )
                                except Exception as exc:  # noqa: BLE001
                                    _LOGGER.warning(
                                        "Failed to activate coupon %s: %s",
                                        cid,
                                        exc,
                                    )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to fetch/activate Lidl Plus Home Logged coupons: %s", exc
                )

            # 2. Activate V2 coupons
            try:
                r_v2 = requests.get(
                    f"https://coupons.lidlplus.com/api/v2/{self.country}",
                    headers=headers,
                    impersonate="chrome110",
                    timeout=15,
                )
                if r_v2.status_code == 200:
                    v2_data = r_v2.json()
                    v2_sections = (
                        v2_data.get("sections", []) if isinstance(v2_data, dict) else []
                    )
                    for s in v2_sections:
                        for c in s.get("coupons", []):
                            cid = str(c.get("id", "")).strip()
                            if not cid or cid in seen_ids:
                                continue
                            seen_ids.add(cid)

                            avail = c.get("availability", {})
                            if (
                                isinstance(avail, dict)
                                and avail.get("apologizeStatus", False)
                            ) or c.get("apologizeStatus", False):
                                continue

                            validity = c.get("validity", {})
                            start_raw = (
                                c.get("startValidityDate")
                                or (
                                    validity.get("start")
                                    if isinstance(validity, dict)
                                    else None
                                )
                                or c.get("startDate")
                            )
                            end_raw = (
                                c.get("endValidityDate")
                                or (
                                    validity.get("end")
                                    if isinstance(validity, dict)
                                    else None
                                )
                                or c.get("endDate")
                            )
                            start_date = start_raw[:10] if start_raw else None
                            end_date = end_raw[:10] if end_raw else None
                            if end_date and end_date < today_str:
                                continue
                            if start_date and start_date > today_str:
                                continue

                            is_act = bool(
                                c.get("isActivated", False) or c.get("activated", False)
                            )
                            c_type = c.get("type", "Standard")
                            is_special = bool(
                                c.get("isSpecial", False)
                                or c_type in ("Special", "AssignablePromotion")
                            )

                            if not is_act:
                                if is_special and self.skip_special_coupons:
                                    _LOGGER.info(
                                        "Skipping special selection coupon %s based on configuration",
                                        cid,
                                    )
                                    continue
                                try:
                                    r_act = requests.post(
                                        f"https://coupons.lidlplus.com/api/v1/{self.country}/{cid}/activation",
                                        headers=headers,
                                        impersonate="chrome110",
                                        timeout=15,
                                    )
                                    if r_act.status_code in (200, 201, 204):
                                        activated += 1
                                        _LOGGER.info(
                                            "Activated Lidl Plus coupon %s", cid
                                        )
                                except Exception as exc:  # noqa: BLE001
                                    _LOGGER.warning(
                                        "Failed to activate coupon %s: %s",
                                        cid,
                                        exc,
                                    )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to fetch/activate Lidl Plus V2 coupons: %s", exc
                )

            # 2. Activate V1 promotions
            try:
                r_v1 = requests.get(
                    "https://coupons.lidlplus.com/app/api/v1/promotionslist",
                    headers=headers,
                    impersonate="chrome110",
                    timeout=15,
                )
                if r_v1.status_code == 200:
                    c_data = r_v1.json()
                    sections = (
                        c_data.get("sections", []) if isinstance(c_data, dict) else []
                    )
                    for s in sections:
                        for c in s.get("coupons", []) + s.get("promotions", []):
                            cid = str(c.get("id") or c.get("promotionId", "")).strip()
                            if not cid or cid in seen_ids:
                                continue
                            seen_ids.add(cid)

                            avail = c.get("availability", {})
                            if (
                                isinstance(avail, dict)
                                and avail.get("apologizeStatus", False)
                            ) or c.get("apologizeStatus", False):
                                continue

                            validity = c.get("validity", {})
                            start_raw = (
                                validity.get("start")
                                if isinstance(validity, dict)
                                else c.get("startValidityDate")
                            )
                            end_raw = (
                                validity.get("end")
                                if isinstance(validity, dict)
                                else c.get("endValidityDate")
                            )
                            start_date = start_raw[:10] if start_raw else None
                            end_date = end_raw[:10] if end_raw else None
                            if end_date and end_date < today_str:
                                continue
                            if start_date and start_date > today_str:
                                continue

                            is_act = bool(
                                c.get("isActivated", False) or c.get("activated", False)
                            )
                            c_type = c.get("type") or "Standard"
                            is_special = bool(
                                c.get("isSpecial", False)
                                or c_type in ("Special", "AssignablePromotion")
                            )

                            if not is_act:
                                if is_special and self.skip_special_coupons:
                                    _LOGGER.info(
                                        "Skipping special selection coupon %s based on configuration",
                                        cid,
                                    )
                                    continue

                                try:
                                    payload: dict[str, Any] = {}
                                    r_act = requests.post(
                                        f"https://coupons.lidlplus.com/app/api/v1/promotions/{cid}/activation",
                                        headers=headers,
                                        json=payload,
                                        impersonate="chrome110",
                                        timeout=15,
                                    )
                                    if r_act.status_code in (200, 201, 204):
                                        activated += 1
                                        _LOGGER.info(
                                            "Activated Lidl Plus coupon %s", cid
                                        )
                                except Exception as exc:  # noqa: BLE001
                                    _LOGGER.warning(
                                        "Failed to activate coupon %s: %s",
                                        cid,
                                        exc,
                                    )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to fetch/activate Lidl Plus V1 promotions: %s", exc
                )

        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to activate Lidl Plus coupons: %s", exc)

        return activated
