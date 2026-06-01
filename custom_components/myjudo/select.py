from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN
from .coordinator import MyJudoCoordinator

CONCENTRATION_OPTIONS = ["minimal", "normal", "maximal"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MyJudoCoordinator = hass.data[DOMAIN][entry.entry_id]
    serial = entry.data[CONF_SERIAL]
    async_add_entities([MyJudoConcentrationSelect(coordinator, serial)])


class MyJudoConcentrationSelect(CoordinatorEntity[MyJudoCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:tune-variant"
    _attr_options = CONCENTRATION_OPTIONS
    _attr_translation_key = "concentration"

    def __init__(self, coordinator: MyJudoCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._attr_name = "Dosiermenge"
        self._attr_unique_id = f"myjudo_{serial}_concentration_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name="JUDO i-dos",
            manufacturer="JUDO",
            model="i-dos",
            serial_number=serial,
        )

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get("dosing_setting")
        if value in CONCENTRATION_OPTIONS:
            return value
        return None

    async def async_select_option(self, option: str) -> None:
        if option not in CONCENTRATION_OPTIONS:
            return
        await self.coordinator.async_set_concentration(option)
