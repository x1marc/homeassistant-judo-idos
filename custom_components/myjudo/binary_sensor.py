from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN
from .coordinator import MyJudoCoordinator

# Below this mineral-solution level (%) the warning turns on.
_LOW_LEVEL_THRESHOLD = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MyJudoCoordinator = hass.data[DOMAIN][entry.entry_id]
    serial = entry.data[CONF_SERIAL]
    async_add_entities([MyJudoProblemBinarySensor(coordinator, serial)])


class MyJudoProblemBinarySensor(
    CoordinatorEntity[MyJudoCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator: MyJudoCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._attr_name = "Minerallösung Warnung"
        self._attr_unique_id = f"myjudo_{serial}_mineral_warning"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name="JUDO i-dos",
            manufacturer="JUDO",
            model="i-dos",
            serial_number=serial,
        )

    @property
    def is_on(self) -> bool | None:
        """Problem = ON when supply is low OR the device reports any error."""
        data = self.coordinator.data
        if data is None:
            return None

        # 1) Mineral solution running low
        level = data.get("mineral_level")
        if isinstance(level, (int, float)) and level < _LOW_LEVEL_THRESHOLD:
            return True

        # 2) Device status is anything other than OK
        error = data.get("error_state")
        if error is not None and error != "OK":
            return True

        # 3) Mineral-specific state warnings (expiry / quantity)
        for key in ("mineral_quantity_state", "mineral_expiry_state"):
            state = data.get(key)
            if state is not None and state != "OK":
                return True

        return False

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "mineral_level": data.get("mineral_level"),
            "error_state": data.get("error_state"),
            "mineral_quantity_state": data.get("mineral_quantity_state"),
            "mineral_expiry_state": data.get("mineral_expiry_state"),
        }
