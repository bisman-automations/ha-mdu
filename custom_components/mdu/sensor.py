"""Sensors for Montana-Dakota Utilities."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MDUConfigEntry
from .api import MDUAccount, UsageHistory
from .const import (
    ATTR_ACCOUNT_ID,
    ATTR_BILLING_MONTH,
    ATTR_LAST_YEAR,
    ATTR_PREMISE_ID,
    ATTR_SA_ID,
    ATTR_SERVICE_ADDRESS,
    ATTR_SOURCE_UNIT,
    ATTR_SOURCE_VALUE,
    DOMAIN,
)
from .coordinator import MDUCoordinator, statistic_id, to_native


@dataclass(frozen=True, kw_only=True)
class MDUAccountSensorDescription(SensorEntityDescription):
    value_fn: Callable[[MDUAccount], float | date | None]


ACCOUNT_SENSORS: tuple[MDUAccountSensorDescription, ...] = (
    MDUAccountSensorDescription(
        key="account_balance",
        translation_key="account_balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        value_fn=lambda a: a.account_balance,
    ),
    MDUAccountSensorDescription(
        key="amount_due",
        translation_key="amount_due",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        value_fn=lambda a: a.amount_due,
    ),
    MDUAccountSensorDescription(
        key="last_bill_amount",
        translation_key="last_bill_amount",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        value_fn=lambda a: a.last_bill_amount,
    ),
    MDUAccountSensorDescription(
        key="due_date",
        translation_key="due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda a: a.due_date,
    ),
    MDUAccountSensorDescription(
        key="last_bill_date",
        translation_key="last_bill_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda a: a.last_bill_date,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MDUConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MDU sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        MDUAccountSensor(coordinator, description) for description in ACCOUNT_SENSORS
    ]

    histories = list(coordinator.data.usage.values())
    for history in histories:
        same_kind = [h for h in histories if h.is_gas == history.is_gas]
        entities.append(MDUUsageSensor(coordinator, history, numbered=len(same_kind) > 1))

    async_add_entities(entities)


class MDUEntity(CoordinatorEntity[MDUCoordinator]):
    """Common device info for an MDU account."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MDUCoordinator) -> None:
        super().__init__(coordinator)
        account_id = coordinator.account_id
        account = coordinator.data.account
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account_id)},
            name=f"MDU {account.description or account_id}",
            manufacturer="Montana-Dakota Utilities",
            model="Utility account",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.base_url,
        )


class MDUAccountSensor(MDUEntity, SensorEntity):
    """Balance, amount due and billing dates for the account."""

    entity_description: MDUAccountSensorDescription

    def __init__(self, coordinator: MDUCoordinator, description: MDUAccountSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.account_id}_{description.key}"

    @property
    def native_value(self) -> float | date | None:
        return self.entity_description.value_fn(self.coordinator.data.account)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_ACCOUNT_ID: self.coordinator.account_id}


class MDUUsageSensor(MDUEntity, SensorEntity):
    """Usage for the most recent billed month of one service.

    The Energy dashboard should use the ``mdu:...`` statistic this sensor names
    in its attributes, which holds every billed month, not this sensor.
    """

    def __init__(self, coordinator: MDUCoordinator, history: UsageHistory, numbered: bool) -> None:
        super().__init__(coordinator)
        sa = history.service_agreement
        self._key = sa.key
        kind = "gas" if history.is_gas else "electric"
        self._attr_unique_id = f"{coordinator.account_id}_{sa.sa_id}_{kind}_usage"
        self._attr_translation_key = f"{kind}_usage"
        if numbered:
            self._attr_translation_key = f"{kind}_usage_service"
            self._attr_translation_placeholders = {"service": sa.address or sa.sa_id}
        if history.is_gas:
            # The gas device class only takes volume units; MDU bills gas by
            # energy (dekatherms), so it is reported as energy in GJ.
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = "GJ"
            self._attr_suggested_display_precision = 3
        else:
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_suggested_display_precision = 0
        self._statistic_id = statistic_id(coordinator.account_id, history)

    @property
    def _history(self) -> UsageHistory | None:
        return self.coordinator.data.usage.get(self._key)

    @property
    def available(self) -> bool:
        return super().available and self._history is not None

    @property
    def native_value(self) -> float | None:
        history = self._history
        if history is None or history.latest is None:
            return None
        return to_native(history, history.latest.value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        history = self._history
        if history is None or history.latest is None:
            return {}
        latest = history.latest
        sa = history.service_agreement
        last_year = history.value_for(latest.month.replace(year=latest.month.year - 1))
        return {
            ATTR_BILLING_MONTH: latest.month.strftime("%Y-%m"),
            ATTR_SOURCE_VALUE: latest.value,
            ATTR_SOURCE_UNIT: history.unit,
            ATTR_LAST_YEAR: last_year,
            ATTR_SA_ID: sa.sa_id,
            ATTR_PREMISE_ID: sa.premise_id,
            ATTR_SERVICE_ADDRESS: sa.address,
            "statistic_id": self._statistic_id,
        }
