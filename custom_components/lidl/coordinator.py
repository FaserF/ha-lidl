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
    CONF_FILTER_LOCAL_STORE,
    CONF_LANGUAGE,
    CONF_PRODUCT_FILTERS,
    CONF_REFRESH_TOKEN,
    CONF_SKIP_SPECIAL_COUPONS,
    CONF_STORE_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    language_for_country,
    tld_for_country,
)
from .coupons import (
    deactivate_all_coupons as _deactivate_all_coupons,
)
from .coupons import (
    deactivate_coupon as _deactivate_coupon,
)
from .coupons import (
    fetch_and_process_coupons,
    is_coupon_for_store,
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
        self.language: str = language_for_country(
            self.country, config.get(CONF_LANGUAGE)
        )
        self.refresh_token: str | None = config.get(CONF_REFRESH_TOKEN)
        self.auto_activate_coupons: bool = config.get(CONF_AUTO_ACTIVATE_COUPONS, False)
        self.skip_special_coupons: bool = config.get(CONF_SKIP_SPECIAL_COUPONS, True)
        self.filter_local_store: bool = config.get(CONF_FILTER_LOCAL_STORE, False)
        self.card_number: str | None = config.get(CONF_CARD_NUMBER)
        self.product_filters: list[str] = config.get(CONF_PRODUCT_FILTERS, [])
        self.config_entry = entry

        # Anti-ban state
        self._backoff_until: datetime | None = None
        self._consecutive_failures = 0
        self._last_success: datetime | None = None
        self._issue_created = False
        self._force_update = False
        self.last_activation_result: dict[str, Any] = {
            "activated": 0,
            "failed": 0,
            "errors": [],
        }
        self.last_deactivation_result: dict[str, Any] = {
            "deactivated": 0,
            "failed": 0,
            "errors": [],
        }

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
            import unicodedata

            def slugify(text: str) -> str:
                # Transliterate language-specific special characters
                text = text.lower()
                text = (
                    text.replace("ä", "ae")
                    .replace("ö", "oe")
                    .replace("ü", "ue")
                    .replace("ß", "ss")
                    .replace("ł", "l")
                    .replace("ø", "oe")
                    .replace("æ", "ae")
                    .replace("å", "aa")
                )
                text = unicodedata.normalize("NFKD", text)
                text = "".join(c for c in text if not unicodedata.combining(c))
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
                "us": "stores",
            }
            path_segment = path_mapping.get(lang, "filialen")
            tld = tld_for_country(self.country)

            self.configuration_url = f"https://www.lidl.{tld}/s/{lang}-{self.country}/{path_segment}/{slug_city}/{slug_address}/"
        else:
            tld = tld_for_country(self.country)
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
        tld = tld_for_country(self.country)
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
            "us": "USAEcommerceClient",
            "pl": "PolandEcommerceClient",
            "cz": "CzechEcommerceClient",
            "sk": "SlovakiaEcommerceClient",
            "hu": "HungaryEcommerceClient",
            "ro": "RomaniaEcommerceClient",
            "bg": "BulgariaEcommerceClient",
            "hr": "CroatiaEcommerceClient",
            "si": "SloveniaEcommerceClient",
            "pt": "PortugalEcommerceClient",
            "gr": "GreeceEcommerceClient",
            "dk": "DenmarkEcommerceClient",
            "se": "SwedenEcommerceClient",
            "fi": "FinlandEcommerceClient",
            "ie": "IrelandEcommerceClient",
            "lt": "LithuaniaEcommerceClient",
            "lv": "LatviaEcommerceClient",
            "ee": "EstoniaEcommerceClient",
            "lu": "LuxembourgEcommerceClient",
        }
        client_id = client_name_map.get(country_lower)
        if not client_id:
            return f"https://www.lidl.{tld}/"
        return f"https://www.lidl.{tld}/mla/?country_code={country_lower}&language={self.language}&client_id={client_id}"

    @property
    def account_key(self) -> str:
        """Return unique key for the Lidl Plus account per country."""
        if not self.refresh_token:
            return f"account_{self.country.lower()}"
        token_prefix = self.refresh_token[:16]
        return f"account_{self.country.lower()}_{token_prefix}"

    def _is_coupon_for_store(
        self,
        c: dict[str, Any],
        sec_name: str,
        is_online: bool,
    ) -> tuple[bool, list[str]]:
        """Return whether coupon matches the local store, and list of specific store IDs."""
        return is_coupon_for_store(
            c,
            sec_name,
            is_online,
            self.store_key,
            self.config_entry.data.get("name"),
            self.config_entry.data.get("city"),
        )

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
                self.data and "coupons" in self.data and "receipts" in self.data
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

                client = LidlAPIClient(country=self.country, language=self.language)
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
                for key in (
                    "coupons",
                    "last_receipt",
                    "user_profile",
                    "receipts",
                    "receipt_ids",
                ):
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
                "Accept-Language": self.language,
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
                today_str = dt_util.now().date().isoformat()
                coupon_list, _, _, _ = fetch_and_process_coupons(
                    access_token=access_token,
                    country=self.country,
                    language=self.language,
                    store_key=self.store_key,
                    store_name=self.config_entry.data.get("name"),
                    store_city=self.config_entry.data.get("city"),
                    today_str=today_str,
                    auto_activate=self.auto_activate_coupons,
                    skip_special_coupons=self.skip_special_coupons,
                    filter_local_store=self.filter_local_store,
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
                        decimal_sep = (
                            "."
                            if self.country.upper() in ("US", "GB", "IE", "MT")
                            else ","
                        )
                        formatted_total = (
                            f"{total_val:.2f} {curr_symbol}".replace(".", decimal_sep)
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

            # --- All Receipts ---
            try:
                all_receipts = self._fetch_all_receipts(headers)
                result["receipts"] = all_receipts
                result["receipt_ids"] = [
                    str(r.get("id")).strip() for r in all_receipts if r.get("id")
                ]
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch Lidl Plus receipts: %s", exc)
                result["receipts"] = []
                result["receipt_ids"] = []

        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to fetch Lidl Plus personal data: %s", exc)

        return result

    def activate_all_coupons(self) -> int:
        """Activate all available (non-activated) Lidl Plus coupons. Returns count activated."""
        activated = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        if not self.refresh_token:
            return activated

        try:
            access_token, _ = self._get_access_and_id_token()
            today_str = dt_util.now().date().isoformat()
            _, activated, failed, errors = fetch_and_process_coupons(
                access_token=access_token,
                country=self.country,
                language=self.language,
                store_key=self.store_key,
                store_name=self.config_entry.data.get("name"),
                store_city=self.config_entry.data.get("city"),
                today_str=today_str,
                auto_activate=True,
                skip_special_coupons=self.skip_special_coupons,
                filter_local_store=self.filter_local_store,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to activate Lidl Plus coupons: %s", exc)

        self.last_activation_result = {
            "activated": activated,
            "failed": failed,
            "errors": errors,
        }
        _LOGGER.info(
            "Lidl Plus coupon activation finished: %d activated, %d failed",
            activated,
            failed,
        )
        return activated

    def deactivate_coupon(self, coupon_id: str) -> bool:
        """Deactivate a specific Lidl Plus coupon by ID."""
        if not self.refresh_token:
            return False
        try:
            access_token, _ = self._get_access_and_id_token()
            return _deactivate_coupon(
                access_token=access_token,
                country=self.country,
                language=self.language,
                store_key=self.store_key,
                coupon_id=coupon_id,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error(
                "Failed to deactivate Lidl Plus coupon %s: %s", coupon_id, exc
            )
            return False

    def deactivate_all_coupons(self) -> int:
        """Deactivate all currently activated Lidl Plus coupons. Returns count deactivated."""
        deactivated = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        if not self.refresh_token:
            return deactivated

        try:
            access_token, _ = self._get_access_and_id_token()
            today_str = dt_util.now().date().isoformat()
            deactivated, failed, errors = _deactivate_all_coupons(
                access_token=access_token,
                country=self.country,
                language=self.language,
                store_key=self.store_key,
                store_name=self.config_entry.data.get("name"),
                store_city=self.config_entry.data.get("city"),
                today_str=today_str,
                filter_local_store=self.filter_local_store,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to deactivate Lidl Plus coupons: %s", exc)

        self.last_deactivation_result = {
            "deactivated": deactivated,
            "failed": failed,
            "errors": errors,
        }
        _LOGGER.info(
            "Lidl Plus coupon deactivation finished: %d deactivated, %d failed",
            deactivated,
            failed,
        )
        return deactivated

    def _fetch_all_receipts(self, headers: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch all Lidl Plus receipt summaries."""
        from curl_cffi import requests

        receipts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        page = 1
        max_pages = 1000

        while page <= max_pages:
            response = requests.get(
                f"https://tickets.lidlplus.com/api/v2/{self.country}/tickets",
                params={
                    "pageNumber": page,
                    "onlyFavorite": "false",
                },
                headers=headers,
                impersonate="chrome110",
                timeout=15,
            )
            response.raise_for_status()

            data = response.json()
            page_receipts = data.get("tickets", [])

            if not page_receipts:
                break

            new_receipts = []

            for receipt in page_receipts:
                receipt_id = str(receipt.get("id", "")).strip()

                if not receipt_id or receipt_id in seen_ids:
                    continue

                seen_ids.add(receipt_id)
                new_receipts.append(receipt)
                receipts.append(receipt)

            # Prevent infinite pagination if the API repeats a page.
            if not new_receipts:
                break

            total_count = data.get("totalCount")
            if total_count is not None and len(receipts) >= int(total_count):
                break

            page += 1

        _LOGGER.info(
            "Retrieved %d Lidl Plus receipts for account %s",
            len(receipts),
            self.country,
        )

        return receipts

    def fetch_receipt_details(self, receipt_id: str) -> dict[str, Any]:
        """Fetch full Lidl receipt details and structured line items."""

        from curl_cffi import requests

        if not self.refresh_token:
            raise ValueError("Lidl Plus authentication is required")

        known_ids = {
            str(receipt.get("id")) for receipt in (self.data or {}).get("receipts", [])
        }

        if receipt_id not in known_ids:
            raise ValueError(f"Unknown receipt ID: {receipt_id}")

        access_token, _ = self._get_access_and_id_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Accept-Language": "en",
            "App-Version": "17.0.5",
            "Operating-System": "Android",
            "App": "com.lidlplus.app",
            "Country": self.country,
        }

        r_detail = requests.get(
            f"https://tickets.lidlplus.com/api/v3/{self.country}/tickets/{receipt_id}",
            headers=headers,
            impersonate="chrome110",
            timeout=15,
        )
        items = []
        if r_detail.status_code == 200:
            detail_data = r_detail.json()
            _LOGGER.debug(
                "LIDL RECEIPTS: JSON %s",
                detail_data,
            )
            if detail_data.get("htmlPrintedReceipt"):
                from html import unescape
                from html.parser import HTMLParser

                class ReceiptParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.items = []

                    def handle_starttag(self, tag, attrs):
                        if tag.lower() != "span":
                            return

                        attrs = dict(attrs)

                        if "article" not in attrs.get("class", "").split():
                            return

                        name = attrs.get("data-art-description")

                        if name:
                            self.items.append(
                                {
                                    "name": unescape(name),
                                    "code": attrs.get("data-art-id"),
                                    "quantity": attrs.get("data-art-quantity", "1"),
                                    "unit_price": attrs.get("data-unit-price"),
                                }
                            )

                parser = ReceiptParser()
                parser.feed(detail_data["htmlPrintedReceipt"])
                items = parser.items

                return {
                    "id": receipt_id,
                    "date": detail_data.get("date"),
                    "store": detail_data.get("store", {}).get("name")
                    or detail_data.get("store", {}).get("id"),
                    "store_code": detail_data.get("store", {}).get("id"),
                    # "total": total_val,
                    # "currency": curr_code,
                    # "total_amount_formatted": formatted_total,
                    # "articles_count": latest.get("articlesCount", 0),
                    # "coupons_used_count": latest.get("couponsUsedCount", 0),
                    "items": items,
                }

        else:
            _LOGGER.error(
                "LIDL RECEIPTS: Detail request failed: %s",
                r_detail.text[:1000],
            )
        return {}
