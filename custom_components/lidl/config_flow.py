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
    CONF_AUTO_ACTIVATE_COUPONS,
    CONF_CARD_NUMBER,
    CONF_COUNTRY,
    CONF_REFRESH_TOKEN,
    CONF_SKIP_SPECIAL_COUPONS,
    CONF_STORE_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

SUPPORTED_COUNTRIES = {
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CH": "Switzerland",
    "CZ": "Czech Republic",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "NL": "Netherlands",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
}


class LidlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
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
        self._login_email: str = ""
        self._login_password: str = ""
        self._mfa_session: dict[str, Any] = {}
        self._discovery_data: dict[str, Any] = {}

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle a discovered Lidl store (triggered by location-based auto-discovery)."""
        store_key = str(discovery_info.get(CONF_STORE_KEY, "")).strip()
        if not store_key:
            return self.async_abort(reason="no_stores_found")

        await self.async_set_unique_id(f"lidl_{store_key}")
        self._abort_if_unique_id_configured()

        self._discovery_data = discovery_info
        self._selected_country = discovery_info.get(CONF_COUNTRY, "DE")
        self.context["title_placeholders"] = {
            "name": discovery_info.get("name") or store_key,
            "city": discovery_info.get("city") or "",
            "address": discovery_info.get("address") or "",
        }
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm adding the discovered Lidl store."""
        if user_input is not None:
            store_key = self._discovery_data.get(CONF_STORE_KEY, "")
            name = self._discovery_data.get("name") or store_key
            title = f"Lidl {name}"
            return self.async_create_entry(title=title, data=self._discovery_data)

        return self.async_show_form(step_id="discovery_confirm")

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
                    # Automatically reuse existing Lidl Plus refresh token if already logged in for another store
                    existing_token = None
                    for entry in self._async_current_entries():
                        token = entry.data.get(CONF_REFRESH_TOKEN)
                        if token:
                            existing_token = token
                            break

                    if existing_token and not login_to_lidl_plus:
                        self._refresh_token = existing_token

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
                return await self.async_step_web_auth()
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
                exc_str = str(exc).lower()
                if "invalid" in exc_str or "credential" in exc_str or "pass" in exc_str:
                    errors["base"] = "invalid_auth"
                elif (
                    "captcha" in exc_str
                    or "turnstile" in exc_str
                    or "callback" in exc_str
                    or "200" in exc_str
                ):
                    return await self.async_step_web_auth()
                else:
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

    async def async_step_web_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show login URL and route user to manual token entry."""
        # web_auth is an instruction-only step — route to manual_token for input
        return await self.async_step_manual_token()

    async def async_step_manual_token(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Accept a refresh token or callback URL from browser login."""
        if errors is None:
            errors = {}

        if user_input is not None:
            token_or_url = user_input.get("refresh_token", "").strip()
            if "code=" in token_or_url or "com.lidlplus.app" in token_or_url:
                import urllib.parse

                try:
                    parsed = urllib.parse.urlparse(token_or_url)
                    code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
                    if code:
                        result = await self.hass.async_add_executor_job(
                            self._exchange_code_for_tokens, code
                        )
                        self._refresh_token = result["refresh_token"]
                        return await self.async_step_select_store()
                except Exception as exc:
                    _LOGGER.error("Manual token URL exchange failed: %s", exc)
                    errors["base"] = "invalid_token"
            elif len(token_or_url) >= 20:
                self._refresh_token = token_or_url
                return await self.async_step_select_store()
            else:
                errors["base"] = "invalid_token"

        if not self._code_verifier:
            self._build_pkce()

        login_url = self._build_auth_url()

        schema = vol.Schema({vol.Required("refresh_token"): str})
        return self.async_show_form(
            step_id="manual_token",
            data_schema=schema,
            description_placeholders={"login_url": login_url},
            errors=errors,
        )

    # ------------------------------------------------------------------
    # PKCE + headless login helpers
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

    def _build_auth_url(self) -> str:
        """Build the Lidl Plus OAuth authorization URL with PKCE."""
        return (
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

    def _headless_login(self, email: str, password: str) -> dict[str, Any]:
        """Perform headless PKCE login. Returns tokens or mfa_required dict."""
        import re
        import urllib.parse

        from curl_cffi import requests

        self._build_pkce()
        auth_url = self._build_auth_url()

        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self._selected_country.lower()}-{self._selected_country}",
        }

        resp = session.get(auth_url, headers=headers, impersonate="chrome", timeout=20)
        resp.raise_for_status()

        login_data: dict[str, str] = {
            "EmailOrPhone": email,
            "Password": password,
            "RememberMe": "false",
        }
        for hidden_match in re.finditer(
            r'<input[^>]+type=["\']hidden["\'][^>]*>', resp.text, re.IGNORECASE
        ):
            input_html = hidden_match.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', input_html, re.IGNORECASE)
            val_m = re.search(r'value=["\']([^"\']*)["\']', input_html, re.IGNORECASE)
            if name_m:
                login_data[name_m.group(1)] = val_m.group(1) if val_m else ""

        if "__RequestVerificationToken" not in login_data:
            for pattern in [
                r'name=["\']__RequestVerificationToken["\']\s+value=["\']([^"\']+)',
                r'value=["\']([^"\']+)["\']\s+name=["\']__RequestVerificationToken',
            ]:
                m = re.search(pattern, resp.text)
                if m:
                    login_data["__RequestVerificationToken"] = m.group(1)
                    break

        form_action = "https://accounts.lidl.com/account/login"
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

        resp2 = session.post(
            form_action,
            data=login_data,
            headers=post_headers,
            impersonate="chrome",
            timeout=20,
            allow_redirects=False,
        )

        location = resp2.headers.get("Location", "")
        for _ in range(10):
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
            location = resp2.headers.get("Location", "")

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

    async def async_step_select_store(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle selecting store from results."""
        errors: dict[str, str] = {}

        if user_input is not None:
            store_key = user_input[CONF_STORE_KEY]
            await self.async_set_unique_id(f"lidl_{store_key}")
            self._abort_if_unique_id_configured()

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
        self._selected_country: str = config_entry.data.get(CONF_COUNTRY, "DE")
        self._mfa_session: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            action = user_input.get("action", "save")
            if action == "login":
                return await self.async_step_login()
            if action == "manual_token":
                return await self.async_step_manual_token()
            if action == "logout":
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
            return self.async_create_entry(
                title="",
                data={
                    CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                    CONF_AUTO_ACTIVATE_COUPONS: bool(
                        user_input.get(CONF_AUTO_ACTIVATE_COUPONS, False)
                    ),
                    CONF_SKIP_SPECIAL_COUPONS: bool(
                        user_input.get(CONF_SKIP_SPECIAL_COUPONS, True)
                    ),
                    CONF_CARD_NUMBER: str(user_input.get(CONF_CARD_NUMBER, "")).strip(),
                },
            )

        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        current_auto_activate = self._config_entry.options.get(
            CONF_AUTO_ACTIVATE_COUPONS, False
        )
        current_skip_special = self._config_entry.options.get(
            CONF_SKIP_SPECIAL_COUPONS, True
        )
        current_card_number = self._config_entry.options.get(CONF_CARD_NUMBER, "")
        existing_token = self._config_entry.data.get(CONF_REFRESH_TOKEN, "")
        is_logged_in = bool(existing_token)

        action_choices: dict[str, str] = {"save": "Save settings"}
        if is_logged_in:
            action_choices["manual_token"] = "Update Lidl Plus Token / Web Login"
            action_choices["login"] = "Re-login to Lidl Plus (Credentials)"
            action_choices["logout"] = "Log out of Lidl Plus"
        else:
            action_choices["login"] = "Log in to Lidl Plus (Credentials)"
            action_choices["manual_token"] = "Web Login / Enter Refresh Token"

        schema_dict: dict[Any, Any] = {
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
        }

        if is_logged_in:
            schema_dict[vol.Optional(CONF_CARD_NUMBER, default=current_card_number)] = (
                str
            )
            schema_dict[
                vol.Optional(CONF_AUTO_ACTIVATE_COUPONS, default=current_auto_activate)
            ] = bool
            schema_dict[
                vol.Optional(CONF_SKIP_SPECIAL_COUPONS, default=current_skip_special)
            ] = bool

        schema_dict[vol.Required("action", default="save")] = vol.In(action_choices)

        options_schema = vol.Schema(schema_dict)

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
                exc_str = str(exc).lower()
                if "invalid" in exc_str or "credential" in exc_str or "pass" in exc_str:
                    errors["base"] = "invalid_auth"
                elif (
                    "captcha" in exc_str
                    or "turnstile" in exc_str
                    or "callback" in exc_str
                    or "200" in exc_str
                ):
                    return await self.async_step_manual_token(
                        errors={"base": "captcha_required"}
                    )
                else:
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
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Accept a refresh token or callback URL from browser login."""
        if errors is None:
            errors = {}

        if user_input is not None:
            token_or_url = user_input.get("refresh_token", "").strip()
            if "code=" in token_or_url or "com.lidlplus.app" in token_or_url:
                import urllib.parse

                try:
                    parsed = urllib.parse.urlparse(token_or_url)
                    code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
                    if code:
                        result = await self.hass.async_add_executor_job(
                            self._exchange_code_for_tokens, code
                        )
                        return self._save_token(result["refresh_token"])
                except Exception as exc:
                    _LOGGER.error("Options manual token URL exchange failed: %s", exc)
                    errors["base"] = "invalid_token"
            elif len(token_or_url) >= 20:
                return self._save_token(token_or_url)
            else:
                errors["base"] = "invalid_token"

        if not self._code_verifier:
            self._build_pkce()

        login_url = self._build_auth_url()

        existing_token = self._config_entry.data.get(CONF_REFRESH_TOKEN, "")
        schema = vol.Schema(
            {vol.Required("refresh_token", default=existing_token): str}
        )
        return self.async_show_form(
            step_id="manual_token",
            data_schema=schema,
            description_placeholders={"login_url": login_url},
            errors=errors,
        )

    def _save_token(self, refresh_token: str) -> config_entries.ConfigFlowResult:
        """Persist refresh_token in config entry data and close the options flow."""
        new_data = {**self._config_entry.data, CONF_REFRESH_TOKEN: refresh_token}
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        return self.async_create_entry(title="", data=self._config_entry.options)

    # ------------------------------------------------------------------
    # Headless login helpers (shared with ConfigFlow via delegation)
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

    def _build_auth_url(self) -> str:
        """Build the Lidl Plus OAuth authorization URL with PKCE."""
        return (
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

    def _headless_login(self, email: str, password: str) -> dict[str, Any]:
        """Perform headless PKCE login. Returns tokens or mfa_required dict."""
        import re
        import urllib.parse

        from curl_cffi import requests

        self._build_pkce()
        auth_url = self._build_auth_url()

        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self._selected_country.lower()}-{self._selected_country}",
        }

        resp = session.get(auth_url, headers=headers, impersonate="chrome", timeout=20)
        resp.raise_for_status()

        login_data: dict[str, str] = {
            "EmailOrPhone": email,
            "Password": password,
            "RememberMe": "false",
        }
        for hidden_match in re.finditer(
            r'<input[^>]+type=["\']hidden["\'][^>]*>', resp.text, re.IGNORECASE
        ):
            input_html = hidden_match.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', input_html, re.IGNORECASE)
            val_m = re.search(r'value=["\']([^"\']*)["\']', input_html, re.IGNORECASE)
            if name_m:
                login_data[name_m.group(1)] = val_m.group(1) if val_m else ""

        if "__RequestVerificationToken" not in login_data:
            for pattern in [
                r'name=["\']__RequestVerificationToken["\']\s+value=["\']([^"\']+)',
                r'value=["\']([^"\']+)["\']\s+name=["\']__RequestVerificationToken',
            ]:
                m = re.search(pattern, resp.text)
                if m:
                    login_data["__RequestVerificationToken"] = m.group(1)
                    break

        form_action = "https://accounts.lidl.com/account/login"
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

        resp2 = session.post(
            form_action,
            data=login_data,
            headers=post_headers,
            impersonate="chrome",
            timeout=20,
            allow_redirects=False,
        )

        location = resp2.headers.get("Location", "")
        for _ in range(10):
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
            location = resp2.headers.get("Location", "")

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
