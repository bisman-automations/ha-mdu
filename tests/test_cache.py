"""Setup from the last saved figures, and retrying sooner after a failure."""

import asyncio
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mdu.const import RETRY_INTERVAL, UPDATE_INTERVAL
from custom_components.mdu.coordinator import MDUData, data_from_dict, data_to_dict
from custom_components.mdu.exceptions import MDUAuthenticationError, MDUConnectionError
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant

from .test_init import client, entry  # noqa: F401 - fixtures


async def test_round_trip(client) -> None:  # noqa: F811
    """Saved figures come back exactly as they were read."""
    account = await client.get_account()
    usage = {
        sa.key: client.get_usage(sa) for sa in account.service_agreements if sa.active
    }
    usage = {key: await value for key, value in usage.items()}
    data = MDUData(account=account, usage=usage)
    assert data_from_dict(data_to_dict(data)) == data


async def test_setup_starts_from_saved_figures(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    client,  # noqa: F811
    freezer: FrozenDateTimeFactory,
) -> None:
    """Once figures are saved, setup doesn't wait for the portal."""
    freezer.move_to("2026-10-09 12:00:00-05:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    release = asyncio.Event()

    async def slow_login() -> None:
        await release.wait()

    client.login = AsyncMock(side_effect=slow_login)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.mdu_home_amount_due").state == "48.75"
    assert hass.states.get("sensor.mdu_home_electric_usage_last_month").state == (
        "830.0"
    )
    client.login.assert_awaited_once()

    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.last_update_success
    assert hass.states.get("sensor.mdu_home_amount_due").state == "48.75"


async def test_saved_figures_rejected_password_starts_reauth(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    client,  # noqa: F811
    freezer: FrozenDateTimeFactory,
) -> None:
    """The background refresh still asks for the password when it's rejected."""
    freezer.move_to("2026-10-09 12:00:00-05:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    client.login = AsyncMock(side_effect=MDUAuthenticationError("bad password"))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    flows = hass.config_entries.flow.async_progress_by_handler(entry.domain)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_failed_refresh_retries_sooner(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    client,  # noqa: F811
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failed refresh tries again in 30 minutes, then goes back to 12 hours."""
    freezer.move_to("2026-10-09 12:00:00-05:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.update_interval == UPDATE_INTERVAL

    client.login = AsyncMock(side_effect=MDUConnectionError("down"))
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.update_interval == RETRY_INTERVAL

    client.login = AsyncMock()
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.update_interval == UPDATE_INTERVAL


async def test_remove_deletes_saved_figures(
    hass: HomeAssistant,
    hass_storage,
    entry: MockConfigEntry,  # noqa: F811
    client,  # noqa: F811
    freezer: FrozenDateTimeFactory,
) -> None:
    """Removing the entry deletes what was saved for it."""
    freezer.move_to("2026-10-09 12:00:00-05:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    key = f"mdu.{entry.entry_id}"
    assert key in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
