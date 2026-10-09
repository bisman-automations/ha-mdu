"""Binary sensors for Montana-Dakota Utilities."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MDUConfigEntry
from .api import MDUAccount
from .coordinator import MDUCoordinator
from .entity import MDUEntity


@dataclass(frozen=True, kw_only=True)
class MDUBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[MDUAccount], bool | None]


BINARY_SENSORS: tuple[MDUBinarySensorDescription, ...] = (
    MDUBinarySensorDescription(
        key="autopay",
        translation_key="autopay",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda a: a.autopay,
    ),
    MDUBinarySensorDescription(
        key="budget_pay",
        translation_key="budget_pay",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda a: a.budget_pay,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MDUConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MDU binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(MDUBinarySensor(coordinator, description) for description in BINARY_SENSORS)


class MDUBinarySensor(MDUEntity, BinarySensorEntity):
    """Whether the account is enrolled in Autopay or Budget Pay."""

    entity_description: MDUBinarySensorDescription

    def __init__(self, coordinator: MDUCoordinator, description: MDUBinarySensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.account_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data.account)
