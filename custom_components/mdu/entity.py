"""Base entity for Montana-Dakota Utilities."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MDUCoordinator


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
