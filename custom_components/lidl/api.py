"""Pure Python client for Lidl Weekly Offers using curl_cffi."""

from __future__ import annotations

import logging
from typing import Any, Literal

from curl_cffi import requests
from pydantic import BaseModel, ConfigDict, Field

_LOGGER = logging.getLogger(__name__)

STORES_BASE_URL = "https://stores.lidlplus.com/api/"
OFFERS_BASE_URL = "https://offers.lidlplus.com/app/api/"
APP_VERSION = "17.0.5"


class Location(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    latitude: float | None = None
    longitude: float | None = None


class Store(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    store_key: str | None = Field(default=None, alias="storeKey")
    name: str | None = None
    address: str | None = None
    postal_code: str | None = Field(default=None, alias="postalCode")
    locality: str | None = None
    distance: float | None = None
    location: Location | None = None

    @property
    def label(self) -> str:
        postcode_and_city = (
            " ".join(value for value in (self.postal_code, self.locality) if value)
            or None
        )
        return ", ".join(
            value for value in (self.name, self.address, postcode_and_city) if value
        )

    @property
    def title(self) -> str:
        if self.name:
            return self.name
        if self.store_key:
            return f"Lidl {self.store_key}"
        return "Lidl"


class PriceBox(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    price_symbol: str | None = Field(default=None, alias="priceSymbol")
    discount_message: str | None = Field(default=None, alias="discountMessage")
    large_part_numeric: float | None = Field(default=None, alias="largePartNumeric")
    large_part_string: str | None = Field(default=None, alias="largePartString")
    small_part_numeric: float | None = Field(default=None, alias="smallPartNumeric")
    small_part_string: str | None = Field(default=None, alias="smallPartString")

    @property
    def price_val(self) -> str:
        val = self.large_part_string or (
            f"{self.large_part_numeric:.2f}".rstrip("0").rstrip(".")
            if self.large_part_numeric is not None
            else None
        )
        if not val:
            return "-"
        return f"{val} {self.price_symbol}" if self.price_symbol else val

    @property
    def old_price_val(self) -> str:
        val = self.small_part_string or (
            f"{self.small_part_numeric:.2f}".rstrip("0").rstrip(".")
            if self.small_part_numeric is not None
            else None
        )
        if not val:
            return "-"
        return f"{val} {self.price_symbol}" if self.price_symbol else val


class Offer(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    id: str | None = None
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    offer_type: str | None = Field(default=None, alias="offerType")
    image_url: str | None = Field(default=None, alias="imageUrl")
    start_validity_date: str | None = Field(default=None, alias="startValidityDate")
    end_validity_date: str | None = Field(default=None, alias="endValidityDate")
    price_box: PriceBox | None = Field(default=None, alias="priceBox")
    packaging: str | None = None
    price_per_unit: str | None = Field(default=None, alias="pricePerUnit")


class LidlAPIClient:
    """API client that interacts directly with Lidl Plus mobile API using curl_cffi."""

    def __init__(self, country: str, language: str | None = None) -> None:
        self.country = country.upper()
        self.language = language or f"{self.country.lower()}-{self.country}"
        self.app_version = APP_VERSION

    def _request(
        self,
        method: Literal[
            "GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "TRACE", "PATCH", "QUERY"
        ],
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Accept-Language": self.language,
            "User-Agent": f"LidlPlus/{self.app_version} Android okhttp/4.12.0",
            "X-Client-Version": self.app_version,
            "X-Client-Platform": "android",
        }
        try:
            response = requests.request(
                method,
                url,
                params=params,
                headers=headers,
                impersonate="chrome",
                timeout=20.0,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            _LOGGER.error("Lidl API request failed for %s: %s", url, exc)
            raise RuntimeError(f"Lidl API request failed: {exc}") from exc

    def search_stores(self, query: str) -> list[Store]:
        """Search stores by city/postcode using client-side filtering over the full catalog."""
        all_stores_url = f"{STORES_BASE_URL}v4/{self.country}"
        all_data = self._request("GET", all_stores_url)
        stores = []
        if isinstance(all_data, list):
            terms = [term.casefold() for term in query.split() if term.strip()]
            for item in all_data:
                store = Store.model_validate(item)
                searchable = " ".join(
                    value
                    for value in (
                        store.store_key,
                        store.name,
                        store.address,
                        store.postal_code,
                        store.locality,
                    )
                    if value
                ).casefold()
                if all(term in searchable for term in terms):
                    stores.append(store)
        return stores

    def get_offers(self, store_key: str) -> list[Offer]:
        """Fetch weekly offers for the store."""
        url = f"{OFFERS_BASE_URL}v4/{self.country}/{store_key}/offers"
        data = self._request("GET", url)
        offers_data = data.get("offers", []) if isinstance(data, dict) else []
        return [Offer.model_validate(item) for item in offers_data]
