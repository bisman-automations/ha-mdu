"""Data coordinator for Montana-Dakota Utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

try:
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # Home Assistant before 2025.10
    StatisticMeanType = None  # type: ignore[assignment,misc]

from .api import MDUAccount, MDUClient, UsageHistory
from .const import (
    CONF_ACCOUNT_ID,
    CONF_TRUSTED_COOKIES,
    DOMAIN,
    KWH_PER_DEKATHERM,
    KWH_PER_THERM,
    UNIT_DEKATHERM,
    UNIT_KWH,
    UPDATE_INTERVAL,
)
from .exceptions import (
    MDUAuthenticationError,
    MDUError,
    MDUMfaRequired,
)

_LOGGER = logging.getLogger(__name__)

GJ_PER_KWH = 0.0036


@dataclass
class MDUData:
    """Everything one refresh read from the portal."""

    account: MDUAccount
    usage: dict[str, UsageHistory] = field(default_factory=dict)


def to_native(history: UsageHistory, value: float) -> float:
    """Convert a portal value to the unit the sensors and statistics use.

    Electric stays in kWh. Gas is converted from dekatherms or therms to GJ,
    an energy unit Home Assistant's gas tracking accepts (1 Dk ≈ 1.055 GJ).
    """
    if history.unit == UNIT_KWH:
        return value
    kwh = value * (KWH_PER_DEKATHERM if history.unit == UNIT_DEKATHERM else KWH_PER_THERM)
    return round(kwh * GJ_PER_KWH, 4)


def statistic_id(account_id: str, history: UsageHistory) -> str:
    kind = "gas" if history.is_gas else "electric"
    sa = history.service_agreement
    return f"{DOMAIN}:{account_id}_{sa.sa_id}_{kind}_usage".lower()


class MDUCoordinator(DataUpdateCoordinator[MDUData]):
    """Signs in, reads the account and its usage, and records statistics."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: MDUClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_ACCOUNT_ID]}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.account_id: str = entry.data[CONF_ACCOUNT_ID]

    async def _async_update_data(self) -> MDUData:
        try:
            data = await self._fetch()
        except (MDUAuthenticationError, MDUMfaRequired) as err:
            # A password change, or MDU no longer trusting this client, needs
            # the user: reauth asks for the password and, if MDU wants one,
            # a security code.
            raise ConfigEntryAuthFailed(str(err)) from err
        except MDUError as err:
            raise UpdateFailed(f"Error talking to MDU: {err}") from err
        finally:
            await self.client.logout()

        self._save_trusted_cookies()
        for history in data.usage.values():
            await self._insert_statistics(history)
        return data

    async def _fetch(self) -> MDUData:
        # Start every refresh from a clean session, keeping only the cookies
        # that mark this client as a trusted device.
        self.client.clear_session()
        await self.client.login()
        await self.client.select_account(self.account_id)
        account = await self.client.get_account()

        usage: dict[str, UsageHistory] = {}
        for agreement in account.service_agreements:
            try:
                history = await self.client.get_usage(agreement)
            except MDUError as err:
                _LOGGER.warning("Could not read usage for service %s: %s", agreement.sa_id, err)
                continue
            if history is not None and history.months:
                usage[agreement.key] = history
        return MDUData(account=account, usage=usage)

    def _save_trusted_cookies(self) -> None:
        cookies = self.client.export_trusted_cookies()
        if cookies and cookies != self.config_entry.data.get(CONF_TRUSTED_COOKIES):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_TRUSTED_COOKIES: cookies},
            )

    async def _insert_statistics(self, history: UsageHistory) -> None:
        """Record monthly usage as an external statistic for the Energy dashboard.

        MDU only publishes billed months, so each month is one statistic row
        at local midnight on the 1st. The months the portal returns are
        rewritten on every refresh; the running sum continues from what is
        already recorded for the earliest of them, so older months that have
        dropped out of the portal's window stay counted.
        """
        stat_id = statistic_id(self.account_id, history)
        months = history.months
        first_start = _month_start(months[0].month)

        recorder = get_instance(self.hass)
        existing = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            first_start,
            first_start + timedelta(hours=1),
            {stat_id},
            "hour",
            None,
            {"sum", "state"},
        )
        rows = existing.get(stat_id) or []
        if rows and rows[0].get("sum") is not None:
            base = (rows[0]["sum"] or 0) - (rows[0].get("state") or 0)
        else:
            last = await recorder.async_add_executor_job(
                get_last_statistics, self.hass, 1, stat_id, True, {"sum"}
            )
            last_rows = last.get(stat_id) or []
            base = 0.0
            if last_rows and last_rows[0]["start"] < first_start.timestamp():
                base = last_rows[0].get("sum") or 0.0

        total = base
        statistics: list[StatisticData] = []
        for month in months:
            value = to_native(history, month.value)
            total += value
            statistics.append(
                StatisticData(start=_month_start(month.month), state=value, sum=round(total, 4))
            )

        kind = "Gas" if history.is_gas else "Electric"
        native_unit = "kWh" if not history.is_gas else "GJ"
        metadata_kwargs = {
            "has_sum": True,
            "name": f"MDU {kind} usage {self.account_id} {history.service_agreement.sa_id}",
            "source": DOMAIN,
            "statistic_id": stat_id,
            "unit_of_measurement": native_unit,
        }
        if StatisticMeanType is not None:
            metadata_kwargs["mean_type"] = StatisticMeanType.NONE
            metadata_kwargs["unit_class"] = "energy"
        else:
            metadata_kwargs["has_mean"] = False
        _LOGGER.debug("Writing %d monthly statistics to %s", len(statistics), stat_id)
        async_add_external_statistics(self.hass, StatisticMetaData(**metadata_kwargs), statistics)


def _month_start(month: date) -> datetime:
    return dt_util.start_of_local_day(month)
