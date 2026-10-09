"""Montana-Dakota Utilities integration for Home Assistant.

For more details about this integration, please refer to
https://github.com/bisman-automations/ha-mdu
"""
from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import MDUClient
from .const import CONF_HOST, CONF_PASSWORD, CONF_TRUSTED_COOKIES, CONF_USERNAME, DEFAULT_HOST
from .coordinator import MDUCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type MDUConfigEntry = ConfigEntry[MDUCoordinator]


def create_client(hass: HomeAssistant, data: dict, auto_cleanup: bool = True) -> MDUClient:
    """Return a client with its own cookie jar and any saved trusted-device cookies.

    With ``auto_cleanup`` (the default, for entry setup) Home Assistant
    detaches the session when the entry unloads. Config flows pass False and
    call ``client.close()`` themselves.
    """
    # The portal is session-cookie based, so each entry needs a private jar.
    # quote_cookie=False: aiohttp otherwise sends values containing "=" (base64
    # session and load-balancer cookies) wrapped in quotes, the server doesn't
    # recognise its own session, and sign-in silently fails.
    session = async_create_clientsession(
        hass, auto_cleanup=auto_cleanup, cookie_jar=aiohttp.CookieJar(quote_cookie=False)
    )
    client = MDUClient(
        session,
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        host=data.get(CONF_HOST, DEFAULT_HOST),
    )
    client.import_trusted_cookies(data.get(CONF_TRUSTED_COOKIES))
    return client


async def async_setup_entry(hass: HomeAssistant, entry: MDUConfigEntry) -> bool:
    """Set up Montana-Dakota Utilities from a config entry."""
    client = create_client(hass, dict(entry.data))
    coordinator = MDUCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.close()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MDUConfigEntry) -> bool:
    """Unload a config entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.close()
    return unloaded
