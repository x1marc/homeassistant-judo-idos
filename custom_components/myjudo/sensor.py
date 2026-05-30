from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN
from .coordinator import MyJudoCoordinator


@dataclass(frozen=True, kw_only=True)
class MyJudoSensorDescription(SensorEntityDescription):
    data_key: str


SENSORS: tuple[MyJudoSensorDescription, ...] = (
    MyJudoSensorDescription(
        key="water_total",
        data_key="water_total",
        name="Gesamtwassermenge",
        icon="mdi:water",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    MyJudoSensorDescription(
        key="water_total_l",
        data_key="water_total_l",
        name="Gesamtwassermenge (Liter)",
        icon="mdi:water",
        native_unit_of_measurement="L",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="water_current",
        data_key="water_current",
        name="Aktueller Wasserdurchfluss",
        icon="mdi:water-pump",
        native_unit_of_measurement="L/h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="water_average",
        data_key="water_average",
        name="Ø Wasserverbrauch täglich",
        icon="mdi:chart-line",
        native_unit_of_measurement="L/d",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="salt_quantity",
        data_key="salt_quantity",
        name="Salzmenge",
        icon="mdi:grain",
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="actual_quantity",
        data_key="actual_quantity",
        name="Dosiermenge aktuell",
        icon="mdi:beaker",
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="natural_hardness",
        data_key="natural_hardness",
        name="Natürliche Wasserhärte",
        icon="mdi:water-opacity",
        native_unit_of_measurement="°dH",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="water_today",
        data_key="water_today",
        name="Verbrauch heute",
        icon="mdi:water-check",
        native_unit_of_measurement="L",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="water_week",
        data_key="water_week",
        name="Verbrauch Woche",
        icon="mdi:calendar-week",
        native_unit_of_measurement="L",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="water_month",
        data_key="water_month",
        name="Verbrauch Monat",
        icon="mdi:calendar-month",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    MyJudoSensorDescription(
        key="water_month_l",
        data_key="water_month_l",
        name="Verbrauch Monat (Liter)",
        icon="mdi:calendar-month",
        native_unit_of_measurement="L",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="water_year",
        data_key="water_year",
        name="Verbrauch Jahr",
        icon="mdi:calendar",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    MyJudoSensorDescription(
        key="water_year_l",
        data_key="water_year_l",
        name="Verbrauch Jahr (Liter)",
        icon="mdi:calendar",
        native_unit_of_measurement="L",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    MyJudoSensorDescription(
        key="device_age",
        data_key="device_age",
        name="Gerätealter",
        icon="mdi:clock-outline",
        native_unit_of_measurement="Jahre",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    MyJudoSensorDescription(
        key="init_date",
        data_key="init_date",
        name="Inbetriebnahme",
        icon="mdi:calendar-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    MyJudoSensorDescription(
        key="service_date",
        data_key="service_date",
        name="Service-Datum",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    MyJudoSensorDescription(
        key="devcomm_version",
        data_key="devcomm_version",
        name="Modul-Firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    MyJudoSensorDescription(
        key="serial_number",
        data_key="serial_number",
        name="Seriennummer",
        icon="mdi:barcode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MyJudoCoordinator = hass.data[DOMAIN][entry.entry_id]
    serial = entry.data[CONF_SERIAL]

    async_add_entities(
        MyJudoSensor(coordinator, description, serial)
        for description in SENSORS
    )


class MyJudoSensor(CoordinatorEntity[MyJudoCoordinator], SensorEntity):
    entity_description: MyJudoSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MyJudoCoordinator,
        description: MyJudoSensorDescription,
        serial: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"myjudo_{serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name="JUDO i-dos",
            manufacturer="JUDO",
            model="i-dos",
            serial_number=serial,
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)
