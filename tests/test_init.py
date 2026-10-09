"""Tests for setup, sensors and statistics."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.mdu.api import parse_account, parse_usage
from custom_components.mdu.const import DOMAIN
from custom_components.mdu.exceptions import MDUConnectionError, MDUMfaRequired

from .conftest import load_fixture

TODAY = date(2026, 10, 9)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1234567890",
        title="MDU 1234567890 – Home",
        data={"username": "donavan", "password": "hunter2", "account_id": "1234567890", "trusted_cookies": {}},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def client():
    account = parse_account(load_fixture("session_user.json")["selectedAccount"])
    electric, gas = account.service_agreements
    usage = {
        electric.sa_id: parse_usage(electric, load_fixture("usage_electric.json")["object"], TODAY),
        gas.sa_id: parse_usage(gas, load_fixture("usage_gas.json")["object"], TODAY),
    }
    client = MagicMock()
    client.base_url = "https://customer.montana-dakota.com"
    client.login = AsyncMock()
    client.logout = AsyncMock()
    client.close = AsyncMock()
    client.select_account = AsyncMock()
    client.get_account = AsyncMock(return_value=account)
    client.get_usage = AsyncMock(side_effect=lambda sa: usage[sa.sa_id])
    client.export_trusted_cookies = MagicMock(return_value={})
    with patch("custom_components.mdu.create_client", return_value=client):
        yield client


async def test_setup_creates_sensors_and_statistics(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-10-09 12:00:00-05:00")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.mdu_home_amount_due").state == "182.45"
    assert hass.states.get("sensor.mdu_home_due_date").state == "2026-10-08"

    electric = hass.states.get("sensor.mdu_home_electric_usage_last_month")
    assert electric.state == "830.0"
    assert electric.attributes["billing_month"] == "2026-09"
    assert electric.attributes["same_month_last_year"] == 800

    gas = hass.states.get("sensor.mdu_home_gas_usage_last_month")
    assert gas.attributes["unit_of_measurement"] == "GJ"
    assert gas.attributes["source_value"] == 2.0
    assert gas.attributes["source_unit"] == "Dk"
    assert float(gas.state) == pytest.approx(2.0 * 1.05506, rel=1e-3)

    await async_wait_recording_done(hass)
    stat_id = "mdu:1234567890_5550001_electric_usage"
    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.as_utc(dt_util.parse_datetime("2020-01-01T00:00:00+00:00")),
        None,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    rows = stats[stat_id]
    assert len(rows) == 21
    assert rows[-1]["state"] == 830
    assert rows[-1]["sum"] == pytest.approx(sum(r["state"] for r in rows))

    # A second refresh rewrites the same months without double counting.
    await entry.runtime_data.async_refresh()
    await async_wait_recording_done(hass)
    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.as_utc(dt_util.parse_datetime("2020-01-01T00:00:00+00:00")),
        None,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    assert stats[stat_id][-1]["sum"] == pytest.approx(rows[-1]["sum"])
    client.logout.assert_awaited()


async def test_mfa_required_starts_reauth(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.login.side_effect = MDUMfaRequired
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_connection_error_retries(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.login.side_effect = MDUConnectionError
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    client.close.assert_awaited()


async def test_unload(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    client.close.assert_awaited()
