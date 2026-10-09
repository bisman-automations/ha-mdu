"""Tests for the MDU config flow."""
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mdu.config_flow import mask_contact
from custom_components.mdu.const import DOMAIN
from custom_components.mdu.exceptions import (
    MDUAuthenticationError,
    MDUConnectionError,
    MDUMfaError,
    MDUMfaRequired,
)

COOKIES = {"TRUSTED_DEVICE": {"value": "abc", "domain": "", "path": "/", "max-age": "100", "secure": True}}


@pytest.fixture
def client() -> Generator[MagicMock]:
    client = MagicMock()
    client.login = AsyncMock()
    client.logout = AsyncMock()
    client.close = AsyncMock()
    client.get_accounts = AsyncMock(return_value={"1234567890": "1234567890 – Home"})
    client.mfa_contacts = AsyncMock(return_value=["d@example.com", "7015551234"])
    client.mfa_send_code = AsyncMock()
    client.mfa_verify = AsyncMock()
    client.export_trusted_cookies = MagicMock(return_value=COOKIES)
    with (
        patch("custom_components.mdu.create_client", return_value=client),
        patch("custom_components.mdu.async_setup_entry", return_value=True),
    ):
        yield client


async def _start(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "donavan", "password": "hunter2"}
    )


async def test_single_account_no_mfa(hass: HomeAssistant, client: MagicMock) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MDU 1234567890 – Home"
    assert result["result"].unique_id == "1234567890"
    assert result["data"] == {
        "username": "donavan",
        "password": "hunter2",
        "account_id": "1234567890",
        "trusted_cookies": COOKIES,
    }
    client.close.assert_awaited()


async def test_mfa_then_pick_account(hass: HomeAssistant, client: MagicMock) -> None:
    client.login.side_effect = MDUMfaRequired
    client.get_accounts.return_value = {"111": "111 – Home", "222": "222 – Cabin"}

    result = await _start(hass)
    assert result["step_id"] == "mfa_contact"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mfa_contact": "7015551234"})
    assert result["step_id"] == "mfa_code"
    client.mfa_send_code.assert_awaited_with("7015551234")

    client.mfa_verify.side_effect = MDUMfaError("bad", "invalid_code")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mfa_code": "11111"})
    assert result["errors"] == {"base": "mfa_invalid_code"}

    client.mfa_verify.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mfa_code": "12345"})
    assert result["step_id"] == "account"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"account_id": "222"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["account_id"] == "222"
    assert result["title"] == "MDU 222 – Cabin"


@pytest.mark.parametrize(
    ("error", "key"),
    [(MDUAuthenticationError, "invalid_auth"), (MDUConnectionError, "cannot_connect"), (RuntimeError, "unknown")],
)
async def test_sign_in_errors(hass: HomeAssistant, client: MagicMock, error, key) -> None:
    client.login.side_effect = error
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


async def test_already_configured(hass: HomeAssistant, client: MagicMock) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="1234567890", data={}).add_to_hass(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_with_mfa(hass: HomeAssistant, client: MagicMock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1234567890",
        data={"username": "donavan", "password": "old", "account_id": "1234567890", "trusted_cookies": {}},
    )
    entry.add_to_hass(hass)
    client.login.side_effect = MDUMfaRequired

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new"})
    assert result["step_id"] == "mfa_contact"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mfa_contact": "d@example.com"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mfa_code": "12345"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new"
    assert entry.data["trusted_cookies"] == COOKIES


def test_mask_contact() -> None:
    assert mask_contact("donavan@example.com") == "d******@example.com"
    assert mask_contact("7015551234") == "(***) ***-1234"
