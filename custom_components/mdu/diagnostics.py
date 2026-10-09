"""Diagnostics for Montana-Dakota Utilities.

Everything that identifies the account holder is removed: credentials,
cookies, account and service numbers, and addresses. What remains is the
shape of the data and the figures, which is what's needed to debug parsing.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MDUConfigEntry
from .const import CONF_ACCOUNT_ID, CONF_PASSWORD, CONF_TRUSTED_COOKIES, CONF_USERNAME

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_ACCOUNT_ID,
    CONF_TRUSTED_COOKIES,
    "address",
    "description",
    "premise_id",
    "sa_id",
    "unique_id",
    "title",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: MDUConfigEntry) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    usage = {
        f"service_{index}": {
            "service_agreement": asdict(history.service_agreement),
            "sa_type": history.sa_type,
            "gl_division": history.gl_division,
            "unit": history.unit,
            "months": [{"month": m.month.isoformat(), "value": m.value} for m in history.months],
        }
        for index, history in enumerate(data.usage.values(), start=1)
    }
    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "version": f"{entry.version}.{entry.minor_version}",
            },
            "last_update_success": coordinator.last_update_success,
            "account": _jsonable(asdict(data.account)),
            "usage": _jsonable(usage),
        },
        TO_REDACT,
    )


def _jsonable(value: Any) -> Any:
    """Turn dates into ISO strings so the diagnostics file is plain JSON."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
