"""Config flow for Montana-Dakota Utilities."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import MDUClient
from .const import (
    CONF_ACCOUNT_ID,
    CONF_MFA_CODE,
    CONF_MFA_CONTACT,
    CONF_PASSWORD,
    CONF_TRUSTED_COOKIES,
    CONF_USERNAME,
    DOMAIN,
)
from .exceptions import (
    MDUAuthenticationError,
    MDUConnectionError,
    MDUError,
    MDUMfaError,
    MDUMfaRequired,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def mask_contact(contact: str) -> str:
    """Mask a contact the way the portal does: a****@example.com, (***) ***-1234."""
    if "@" in contact:
        name, _, domain = contact.partition("@")
        return f"{name[:1]}{'*' * (len(name) - 1)}@{domain}"
    digits = "".join(ch for ch in contact if ch.isdigit())
    return f"(***) ***-{digits[-4:]}" if len(digits) >= 4 else contact


class MDUConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Montana-Dakota Utilities."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: MDUClient | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._contacts: list[str] = []
        self._accounts: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the portal username and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            result = await self._async_sign_in(errors)
            if result is not None:
                return result

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=self._username or ""): str,
                vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication."""
        self._username = entry_data[CONF_USERNAME]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again; MDU may also ask for a security code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            result = await self._async_sign_in(errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"username": self._username or ""},
            errors=errors,
        )

    async def async_step_mfa_contact(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose where MDU sends the security code."""
        errors: dict[str, str] = {}
        assert self._client is not None
        if user_input is not None:
            try:
                await self._client.mfa_send_code(user_input[CONF_MFA_CONTACT])
            except MDUError as err:
                _LOGGER.debug("Sending security code failed: %s", err)
                errors["base"] = "mfa_send_failed"
            else:
                return await self.async_step_mfa_code()

        options = [SelectOptionDict(value=c, label=mask_contact(c)) for c in self._contacts]
        schema = vol.Schema(
            {
                vol.Required(CONF_MFA_CONTACT, default=self._contacts[0]): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="mfa_contact", data_schema=schema, errors=errors)

    async def async_step_mfa_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the 5-digit security code."""
        errors: dict[str, str] = {}
        assert self._client is not None
        if user_input is not None:
            try:
                await self._client.mfa_verify(user_input[CONF_MFA_CODE])
            except MDUMfaError as err:
                errors["base"] = f"mfa_{err.reason}"
            except MDUConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_after_sign_in(errors) or self.async_show_form(
                    step_id="mfa_code", data_schema=_code_schema(), errors=errors
                )

        return self.async_show_form(step_id="mfa_code", data_schema=_code_schema(), errors=errors)

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick an account when the login has more than one."""
        if user_input is not None:
            return await self._async_finish(user_input[CONF_ACCOUNT_ID])

        options = [SelectOptionDict(value=k, label=v) for k, v in self._accounts.items()]
        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT_ID): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="account", data_schema=schema)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def async_remove(self) -> None:
        """Close the flow's HTTP session if the flow is abandoned."""
        if self._client is not None:
            self.hass.async_create_task(self._client.close())

    def _new_client(self) -> MDUClient:
        # Imported here so tests can patch the client factory.
        from . import create_client

        data = {CONF_USERNAME: self._username, CONF_PASSWORD: self._password}
        if self.source == SOURCE_REAUTH:
            # Keep the trusted-device cookies, so MDU may skip the code.
            data[CONF_TRUSTED_COOKIES] = self._get_reauth_entry().data.get(CONF_TRUSTED_COOKIES)
        return create_client(self.hass, data)

    async def _async_sign_in(self, errors: dict[str, str]) -> ConfigFlowResult | None:
        """Sign in; return the next step, or None with ``errors`` filled in."""
        if self._client is not None:
            await self._client.close()
        self._client = self._new_client()
        try:
            await self._client.login()
        except MDUMfaRequired:
            try:
                self._contacts = await self._client.mfa_contacts()
            except MDUError as err:
                _LOGGER.debug("Reading security code contacts failed: %s", err)
                errors["base"] = "cannot_connect"
                return None
            if not self._contacts:
                errors["base"] = "mfa_no_contacts"
                return None
            return await self.async_step_mfa_contact()
        except MDUAuthenticationError:
            errors["base"] = "invalid_auth"
            return None
        except MDUConnectionError:
            errors["base"] = "cannot_connect"
            return None
        except Exception:
            _LOGGER.exception("Unexpected error signing in to MDU")
            errors["base"] = "unknown"
            return None
        return await self._async_after_sign_in(errors)

    async def _async_after_sign_in(self, errors: dict[str, str]) -> ConfigFlowResult | None:
        """Read the accounts and move on to choosing one."""
        assert self._client is not None
        try:
            self._accounts = await self._client.get_accounts()
        except MDUError as err:
            _LOGGER.debug("Reading accounts failed: %s", err)
            errors["base"] = "cannot_connect"
            return None
        if not self._accounts:
            return self.async_abort(reason="no_accounts")

        if self.source == SOURCE_REAUTH:
            account_id = self._get_reauth_entry().data[CONF_ACCOUNT_ID]
            if account_id not in self._accounts:
                return self.async_abort(reason="account_missing")
            return await self._async_finish(account_id)
        if len(self._accounts) == 1:
            return await self._async_finish(next(iter(self._accounts)))
        return await self.async_step_account()

    async def _async_finish(self, account_id: str) -> ConfigFlowResult:
        assert self._client is not None
        cookies = self._client.export_trusted_cookies()
        await self._client.logout()
        await self._client.close()

        data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_ACCOUNT_ID: account_id,
            CONF_TRUSTED_COOKIES: cookies,
        }
        await self.async_set_unique_id(account_id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="account_missing")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)

        self._abort_if_unique_id_configured()
        label = self._accounts.get(account_id, account_id)
        return self.async_create_entry(title=f"MDU {label}", data=data)


def _code_schema() -> vol.Schema:
    return vol.Schema({vol.Required(CONF_MFA_CODE): str})
