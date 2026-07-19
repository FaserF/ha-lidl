"""Config flow for Lidl Weekly Offers integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import LidlAPIClient, Store
from .const import (
    CONF_COUNTRY,
    CONF_REFRESH_TOKEN,
    CONF_STORE_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

SUPPORTED_COUNTRIES = {
    "DE": "Germany",
    "AT": "Austria",
    "ES": "Spain",
    "FR": "France",
    "NL": "Netherlands",
    "PL": "Poland",
}


class LidlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lidl."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._search_results: list[Store] = []
        self._selected_country: str = "DE"
        self._refresh_token: str | None = None
        self._code_verifier: str = ""
        self._code_challenge: str = ""
        self._auth_url: str = ""
        self._nonce: str = ""
        self._state: str = ""
        # Headless auth session state
        self._login_email: str = ""
        self._login_password: str = ""
        self._mfa_session: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle initial user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_country = user_input[CONF_COUNTRY]
            query = user_input["search_query"].strip()
            login_to_lidl_plus = user_input.get("login_to_lidl_plus", False)

            try:
                client = LidlAPIClient(country=self._selected_country)
                results = await self.hass.async_add_executor_job(
                    client.search_stores, query
                )

                if not results:
                    errors["base"] = "no_stores_found"
                else:
                    self._search_results = results
                    if login_to_lidl_plus:
                        return await self.async_step_login()
                    return await self.async_step_select_store()
            except Exception as exc:
                _LOGGER.error("Lidl store search error: %s", exc)
                errors["base"] = "search_failed"

        schema = vol.Schema(
            {
                vol.Required(CONF_COUNTRY, default="DE"): vol.In(SUPPORTED_COUNTRIES),
                vol.Required("search_query"): str,
                vol.Required("login_to_lidl_plus", default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show email/password form for Lidl Plus login."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("use_manual_token"):
                return await self.async_step_manual_token()
            self._login_email = user_input["email"].strip()
            self._login_password = user_input["password"]
            try:
                result = await self.hass.async_add_executor_job(
                    self._headless_login,
                    self._login_email,
                    self._login_password,
                )
                if result.get("mfa_required"):
                    self._mfa_session = result
                    return await self.async_step_mfa()
                self._refresh_token = result["refresh_token"]
                return await self.async_step_select_store()
            except Exception as exc:
                _LOGGER.error("Lidl Plus headless login failed: %s", exc)
                errors["base"] = "auth_failed"

        from homeassistant.helpers.selector import BooleanSelector

        schema = vol.Schema(
            {
                vol.Required("email", default=self._login_email): str,
                vol.Required("password", default=self._login_password): str,
                vol.Optional("use_manual_token", default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="login",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle MFA code entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mfa_code = user_input["mfa_code"].strip()
            try:
                result = await self.hass.async_add_executor_job(
                    self._submit_mfa,
                    self._mfa_session,
                    mfa_code,
                )
                self._refresh_token = result["refresh_token"]
                return await self.async_step_select_store()
            except Exception as exc:
                _LOGGER.error("Lidl Plus MFA verification failed: %s", exc)
                errors["base"] = "mfa_failed"

        schema = vol.Schema({vol.Required("mfa_code"): str})
        return self.async_show_form(
            step_id="mfa",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_manual_token(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Accept a refresh token obtained via the lidl-plus CLI as a fallback."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input["refresh_token"].strip()
            if len(token) < 20:
                errors["base"] = "invalid_token"
            else:
                self._refresh_token = token
                return await self.async_step_select_store()

        schema = vol.Schema({vol.Required("refresh_token"): str})
        return self.async_show_form(
            step_id="manual_token", data_schema=schema, errors=errors
        )

    def _build_pkce(self) -> None:
        """Generate PKCE verifier/challenge, nonce, state."""
        import base64
        import hashlib
        import secrets

        self._code_verifier = secrets.token_urlsafe(64)
        sha256 = hashlib.sha256(self._code_verifier.encode()).digest()
        self._code_challenge = (
            base64.urlsafe_b64encode(sha256).decode().replace("=", "")
        )
        self._nonce = secrets.token_urlsafe(32)
        self._state = secrets.token_urlsafe(32)

    def _headless_login(self, email: str, password: str) -> dict[str, Any]:
        """Perform headless PKCE login via curl_cffi session. Returns tokens or mfa_required dict."""
        import re
        import urllib.parse

        from curl_cffi import requests

        self._build_pkce()

        auth_url = (
            "https://accounts.lidl.com/connect/authorize"
            "?client_id=LidlPlusNativeClient"
            "&redirect_uri=com.lidlplus.app%3A%2F%2Fcallback"
            "&response_type=code"
            "&scope=openid%20profile%20offline_access%20lpprofile%20lpapis"
            f"&code_challenge={self._code_challenge}"
            "&code_challenge_method=S256"
            f"&nonce={self._nonce}"
            f"&state={self._state}"
            f"&Country={self._selected_country}"
            f"&language={self._selected_country.lower()}-{self._selected_country}"
        )

        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self._selected_country.lower()}-{self._selected_country}",
        }

        # 1. GET auth URL → follow redirects to login page
        resp = session.get(auth_url, headers=headers, impersonate="chrome", timeout=20)
        resp.raise_for_status()

        # 2. Parse CSRF token and form action from HTML
        csrf = ""
        form_action = "https://accounts.lidl.com/account/login"
        for pattern in [
            r'name=["\']__RequestVerificationToken["\']\s+value=["\']([^"\']+)',
            r'value=["\']([^"\']+)["\']\s+name=["\']__RequestVerificationToken',
        ]:
            m = re.search(pattern, resp.text)
            if m:
                csrf = m.group(1)
                break
        m_action = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', resp.text)
        if m_action:
            raw = m_action.group(1).replace("&amp;", "&")
            form_action = (
                raw if raw.startswith("http") else f"https://accounts.lidl.com{raw}"
            )

        post_headers = {
            **headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": resp.url,
        }

        # 3. POST email + password
        login_data: dict[str, str] = {
            "EmailOrPhone": email,
            "Password": password,
            "RememberMe": "false",
        }
        if csrf:
            login_data["__RequestVerificationToken"] = csrf

        resp2 = session.post(
            form_action,
            data=login_data,
            headers=post_headers,
            impersonate="chrome",
            timeout=20,
            allow_redirects=False,
        )

        # Follow redirects manually, watching for the callback or MFA page
        for _ in range(10):
            location = resp2.headers.get("Location", "")
            if not location:
                break
            if location.startswith("com.lidlplus.app://"):
                # Got the callback directly — extract code
                parsed = urllib.parse.urlparse(location)
                code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
                return self._exchange_code_for_tokens(code)
            if "mfa" in location.lower() or "verify" in location.lower():
                # MFA required — save session state
                full_url = (
                    location
                    if location.startswith("http")
                    else f"https://accounts.lidl.com{location}"
                )
                mfa_resp = session.get(
                    full_url, headers=headers, impersonate="chrome", timeout=20
                )
                mfa_csrf = ""
                for pattern in [
                    r'name=["\']__RequestVerificationToken["\']\s+value=["\']([^"\']+)',
                    r'value=["\']([^"\']+)["\']\s+name=["\']__RequestVerificationToken',
                ]:
                    m = re.search(pattern, mfa_resp.text)
                    if m:
                        mfa_csrf = m.group(1)
                        break
                # Find MFA submit URL
                mfa_action = full_url
                m_mfa = re.search(
                    r'<form[^>]+action=["\']([^"\']+)["\']', mfa_resp.text
                )
                if m_mfa:
                    raw = m_mfa.group(1).replace("&amp;", "&")
                    mfa_action = (
                        raw
                        if raw.startswith("http")
                        else f"https://accounts.lidl.com{raw}"
                    )
                return {
                    "mfa_required": True,
                    "session_cookies": dict(session.cookies),
                    "mfa_url": mfa_action,
                    "mfa_csrf": mfa_csrf,
                    "referer": full_url,
                }
            abs_url = (
                location
                if location.startswith("http")
                else f"https://accounts.lidl.com{location}"
            )
            resp2 = session.get(
                abs_url,
                headers=headers,
                impersonate="chrome",
                timeout=20,
                allow_redirects=False,
            )

        raise RuntimeError(
            f"Login flow did not reach callback. Last status: {resp2.status_code}"
        )

    def _submit_mfa(self, mfa_session: dict[str, Any], code: str) -> dict[str, str]:
        """Submit MFA code and return tokens."""
        import urllib.parse

        from curl_cffi import requests

        session = requests.Session()
        # Restore cookies
        for k, v in mfa_session.get("session_cookies", {}).items():
            session.cookies.set(k, v)

        post_data: dict[str, str] = {"VerificationCode": code}
        csrf = mfa_session.get("mfa_csrf", "")
        if csrf:
            post_data["__RequestVerificationToken"] = csrf

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": mfa_session.get("referer", ""),
        }

        resp = session.post(
            mfa_session["mfa_url"],
            data=post_data,
            headers=headers,
            impersonate="chrome",
            timeout=20,
            allow_redirects=False,
        )

        for _ in range(10):
            location = resp.headers.get("Location", "")
            if not location:
                break
            if location.startswith("com.lidlplus.app://"):
                parsed = urllib.parse.urlparse(location)
                auth_code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
                return self._exchange_code_for_tokens(auth_code)
            abs_url = (
                location
                if location.startswith("http")
                else f"https://accounts.lidl.com{location}"
            )
            resp = session.get(
                abs_url,
                headers=headers,
                impersonate="chrome",
                timeout=20,
                allow_redirects=False,
            )

        raise RuntimeError(
            f"MFA flow did not reach callback. Last status: {resp.status_code}"
        )

    def _exchange_code_for_tokens(self, code: str) -> dict[str, str]:
        """Perform token exchange synchronously with curl_cffi."""
        import base64

        from curl_cffi import requests

        auth_header = base64.b64encode(b"LidlPlusNativeClient:secret").decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "LidlPlus/17.0.5 Android okhttp/4.12.0",
        }
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "com.lidlplus.app://callback",
            "code_verifier": self._code_verifier,
        }
        response = requests.post(
            "https://accounts.lidl.com/connect/token",
            data=payload,
            headers=headers,
            impersonate="chrome",
            timeout=15.0,
        )
        response.raise_for_status()
        res_json = response.json()
        return {
            "refresh_token": res_json["refresh_token"],
            "access_token": res_json["access_token"],
        }

    async def async_step_select_store(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle selecting store from results."""
        errors: dict[str, str] = {}

        if user_input is not None:
            store_key = user_input[CONF_STORE_KEY]
            await self.async_set_unique_id(f"lidl_{store_key}")
            self._abort_if_unique_id_configured()

            # Find matching store for details
            selected_store: Store | None = None
            for store in self._search_results:
                if store.store_key == store_key:
                    selected_store = store
                    break

            if selected_store is not None:
                title = f"Lidl {selected_store.name or selected_store.locality or store_key}"
                entry_data = {
                    CONF_STORE_KEY: store_key,
                    CONF_COUNTRY: self._selected_country,
                    "name": selected_store.name,
                    "address": selected_store.address,
                    "postal_code": selected_store.postal_code,
                    "city": selected_store.locality,
                }
                if self._refresh_token:
                    entry_data[CONF_REFRESH_TOKEN] = self._refresh_token
                return self.async_create_entry(title=title, data=entry_data)
            errors["base"] = "unknown"

        # Build dropdown options
        options: dict[str, str] = {}
        for store in self._search_results:
            if store.store_key:
                options[store.store_key] = store.label or f"Store {store.store_key}"

        if not options:
            return self.async_abort(reason="no_stores_found")

        schema = vol.Schema({vol.Required(CONF_STORE_KEY): vol.In(options)})
        return self.async_show_form(
            step_id="select_store",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LidlOptionsFlowHandler:
        """Return options flow handler."""
        return LidlOptionsFlowHandler(config_entry)


class LidlOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Lidl."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._code_verifier: str = ""
        self._code_challenge: str = ""
        self._auth_url: str = ""
        self._nonce: str = ""
        self._state: str = ""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            action = user_input.get("action", "save")
            if action == "login":
                return await self.async_step_login()
            if action == "logout":
                # Remove token from config entry data
                new_data = {
                    k: v
                    for k, v in self._config_entry.data.items()
                    if k != CONF_REFRESH_TOKEN
                }
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=new_data
                )
                return self.async_create_entry(
                    title="", data=self._config_entry.options
                )
            # save — only update_interval
            return self.async_create_entry(
                title="",
                data={CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL])},
            )

        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        is_logged_in = bool(self._config_entry.data.get(CONF_REFRESH_TOKEN))

        action_choices: dict[str, str] = {"save": "Save settings"}
        if is_logged_in:
            action_choices["logout"] = "Log out of Lidl Plus"
        else:
            action_choices["login"] = "Log in to Lidl Plus"

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_UPDATE_INTERVAL,
                        max=MAX_UPDATE_INTERVAL,
                        step=1,
                        unit_of_measurement="hours",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("action", default="save"): vol.In(action_choices),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show email/password form for Lidl Plus login."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("use_manual_token"):
                return await self.async_step_manual_token()
            email = user_input["email"].strip()
            password = user_input["password"]
            try:
                result = await self.hass.async_add_executor_job(
                    self._headless_login, email, password
                )
                if result.get("mfa_required"):
                    self._mfa_session = result
                    return await self.async_step_mfa()
                return self._save_token(result["refresh_token"])
            except Exception as exc:
                _LOGGER.error("Lidl Plus options login failed: %s", exc)
                errors["base"] = "auth_failed"

        from homeassistant.helpers.selector import BooleanSelector

        schema = vol.Schema(
            {
                vol.Required("email"): str,
                vol.Required("password"): str,
                vol.Optional("use_manual_token", default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="login",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle MFA code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mfa_code = user_input["mfa_code"].strip()
            try:
                result = await self.hass.async_add_executor_job(
                    self._submit_mfa, self._mfa_session, mfa_code
                )
                return self._save_token(result["refresh_token"])
            except Exception as exc:
                _LOGGER.error("Lidl Plus options MFA failed: %s", exc)
                errors["base"] = "mfa_failed"

        schema = vol.Schema({vol.Required("mfa_code"): str})
        return self.async_show_form(step_id="mfa", data_schema=schema, errors=errors)

    async def async_step_manual_token(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Accept a refresh token obtained via lidl-plus CLI."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input["refresh_token"].strip()
            if len(token) < 20:
                errors["base"] = "invalid_token"
            else:
                return self._save_token(token)

        schema = vol.Schema({vol.Required("refresh_token"): str})
        return self.async_show_form(
            step_id="manual_token", data_schema=schema, errors=errors
        )

    def _save_token(self, refresh_token: str) -> config_entries.ConfigFlowResult:
        """Persist refresh_token in config entry data and close the options flow."""
        new_data = {**self._config_entry.data, CONF_REFRESH_TOKEN: refresh_token}
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        return self.async_create_entry(title="", data=self._config_entry.options)

    # ------------------------------------------------------------------
    # Headless login helpers
    # ------------------------------------------------------------------

    def _build_pkce(self) -> None:
        """Generate PKCE verifier/challenge, nonce, state."""
        import base64
        import hashlib
        import secrets

        self._code_verifier = secrets.token_urlsafe(64)
        sha256 = hashlib.sha256(self._code_verifier.encode()).digest()
        self._code_challenge = (
            base64.urlsafe_b64encode(sha256).decode().replace("=", "")
        )
        self._nonce = secrets.token_urlsafe(32)
        self._state = secrets.token_urlsafe(32)

    def _headless_login(self, email: str, password: str) -> dict[str, Any]:
        """Perform headless PKCE login. Returns tokens or mfa_required dict."""
        import re
        import urllib.parse

        from curl_cffi import requests

        self._build_pkce()

        auth_url = (
            "https://accounts.lidl.com/connect/authorize"
            "?client_id=LidlPlusNativeClient"
            "&redirect_uri=com.lidlplus.app%3A%2F%2Fcallback"
            "&response_type=code"
            "&scope=openid%20profile%20offline_access%20lpprofile%20lpapis"
            f"&code_challenge={self._code_challenge}"
            "&code_challenge_method=S256"
            f"&nonce={self._nonce}"
            f"&state={self._state}"
            f"&Country={self._selected_country}"
            f"&language={self._selected_country.lower()}-{self._selected_country}"
        )

        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self._selected_country.lower()}-{self._selected_country}",
        }

        resp = session.get(auth_url, headers=headers, impersonate="chrome", timeout=20)
        resp.raise_for_status()

        csrf = ""
        form_action = "https://accounts.lidl.com/account/login"
        for pattern in [
            r'name=["\']__RequestVerificationToken["\']\s+value=["\']([^"\']+)',
            r'value=["\']([^"\']+)["\']\s+name=["\']__RequestVerificationToken',
        ]:
            m = re.search(pattern, resp.text)
            if m:
                csrf = m.group(1)
                break
        m_action = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', resp.text)
        if m_action:
            raw = m_action.group(1).replace("&amp;", "&")
            form_action = (
                raw if raw.startswith("http") else f"https://accounts.lidl.com{raw}"
            )

        post_headers = {
            **headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": resp.url,
        }
        login_data: dict[str, str] = {
            "EmailOrPhone": email,
            "Password": password,
            "RememberMe": "false",
        }
        if csrf:
            login_data["__RequestVerificationToken"] = csrf

        resp2 = session.post(
            form_action,
            data=login_data,
            headers=post_headers,
            impersonate="chrome",
            timeout=20,
            allow_redirects=False,
        )

        for _ in range(10):
            location = resp2.headers.get("Location", "")
            if not location:
                break
            if location.startswith("com.lidlplus.app://"):
                parsed = urllib.parse.urlparse(location)
                code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
                return self._exchange_code_for_tokens(code)
            if "mfa" in location.lower() or "verify" in location.lower():
                full_url = (
                    location
                    if location.startswith("http")
                    else f"https://accounts.lidl.com{location}"
                )
                mfa_resp = session.get(
                    full_url, headers=headers, impersonate="chrome", timeout=20
                )
                mfa_csrf = ""
                for pattern in [
                    r'name=["\']__RequestVerificationToken["\']\s+value=["\']([^"\']+)',
                    r'value=["\']([^"\']+)["\']\s+name=["\']__RequestVerificationToken',
                ]:
                    m = re.search(pattern, mfa_resp.text)
                    if m:
                        mfa_csrf = m.group(1)
                        break
                mfa_action = full_url
                m_mfa = re.search(
                    r'<form[^>]+action=["\']([^"\']+)["\']', mfa_resp.text
                )
                if m_mfa:
                    raw = m_mfa.group(1).replace("&amp;", "&")
                    mfa_action = (
                        raw
                        if raw.startswith("http")
                        else f"https://accounts.lidl.com{raw}"
                    )
                return {
                    "mfa_required": True,
                    "session_cookies": dict(session.cookies),
                    "mfa_url": mfa_action,
                    "mfa_csrf": mfa_csrf,
                    "referer": full_url,
                }
            abs_url = (
                location
                if location.startswith("http")
                else f"https://accounts.lidl.com{location}"
            )
            resp2 = session.get(
                abs_url,
                headers=headers,
                impersonate="chrome",
                timeout=20,
                allow_redirects=False,
            )

        raise RuntimeError(
            f"Login flow did not reach callback. Last status: {resp2.status_code}"
        )

    def _submit_mfa(self, mfa_session: dict[str, Any], code: str) -> dict[str, str]:
        """Submit MFA code and return tokens."""
        import urllib.parse

        from curl_cffi import requests

        session = requests.Session()
        for k, v in mfa_session.get("session_cookies", {}).items():
            session.cookies.set(k, v)

        post_data: dict[str, str] = {"VerificationCode": code}
        csrf = mfa_session.get("mfa_csrf", "")
        if csrf:
            post_data["__RequestVerificationToken"] = csrf

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": mfa_session.get("referer", ""),
        }

        resp = session.post(
            mfa_session["mfa_url"],
            data=post_data,
            headers=headers,
            impersonate="chrome",
            timeout=20,
            allow_redirects=False,
        )

        for _ in range(10):
            location = resp.headers.get("Location", "")
            if not location:
                break
            if location.startswith("com.lidlplus.app://"):
                parsed = urllib.parse.urlparse(location)
                auth_code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
                return self._exchange_code_for_tokens(auth_code)
            abs_url = (
                location
                if location.startswith("http")
                else f"https://accounts.lidl.com{location}"
            )
            resp = session.get(
                abs_url,
                headers=headers,
                impersonate="chrome",
                timeout=20,
                allow_redirects=False,
            )

        raise RuntimeError(
            f"MFA flow did not reach callback. Last status: {resp.status_code}"
        )

    def _exchange_code_for_tokens(self, code: str) -> dict[str, str]:
        """Exchange authorization code for tokens."""
        import base64

        from curl_cffi import requests

        auth_header = base64.b64encode(b"LidlPlusNativeClient:secret").decode()
        response = requests.post(
            "https://accounts.lidl.com/connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "com.lidlplus.app://callback",
                "code_verifier": self._code_verifier,
            },
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "LidlPlus/17.0.5 Android okhttp/4.12.0",
            },
            impersonate="chrome",
            timeout=15.0,
        )
        response.raise_for_status()
        res_json = response.json()
        return {
            "refresh_token": res_json["refresh_token"],
            "access_token": res_json["access_token"],
        }
