"""Stub for the lidlplus package used in tests."""

from __future__ import annotations

from typing import Any


class LidlPlusApi:
    """Minimal stub of LidlPlusApi for test isolation."""

    def __init__(
        self,
        language: str = "de",
        country: str = "DE",
        refresh_token: str = "",
        **kwargs: Any,
    ) -> None:
        self.language = language
        self.country = country
        self.refresh_token = refresh_token

    def coupons(self) -> list[dict[str, Any]]:
        return []

    def ticket(self) -> dict[str, Any]:
        return {}

    def tickets(self) -> list[dict[str, Any]]:
        return []

    def mydata(self) -> dict[str, Any]:
        return {}
