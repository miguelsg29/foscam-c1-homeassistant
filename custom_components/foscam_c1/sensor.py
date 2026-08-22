"""Sensores de estado y diagnóstico de la cámara Foscam."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ALARM_DETECTED, ALARM_DISABLED, ALARM_NO_ALARM
from .coordinator import FoscamConfigEntry, FoscamData
from .entity import FoscamEntity

PARALLEL_UPDATES = 0

ALARM_STATES = {
    ALARM_DISABLED: "disabled",
    ALARM_NO_ALARM: "idle",
    ALARM_DETECTED: "detected",
}
ALARM_OPTIONS = ["disabled", "idle", "detected"]

LINK_STATES = {0: "disabled", 1: "success", 2: "failed"}
LINK_OPTIONS = ["disabled", "success", "failed"]

SD_STATES = {0: "no_card", 1: "ok", 2: "read_only"}
SD_OPTIONS = ["no_card", "ok", "read_only"]

INFRA_MODES = {0: "auto", 1: "manual"}
INFRA_OPTIONS = ["auto", "manual"]


@dataclass(frozen=True, kw_only=True)
class FoscamSensorDescription(SensorEntityDescription):
    """Describe un sensor de la cámara."""

    value_fn: Callable[[FoscamData], str | int | float | None]


def _mapped(field: str, mapping: dict[int, str]) -> Callable[[FoscamData], str | None]:
    """Traducir un campo numérico de getDevState a una opción de enumeración."""
    return lambda data: mapping.get(data.state_int(field))


def _sd_used_percent(data: FoscamData) -> float | None:
    """Porcentaje de la tarjeta SD ocupado."""
    total = data.state_int("sdTotalSpace", 0)
    free = data.state_int("sdFreeSpace", -1)
    if total <= 0 or free < 0:
        return None
    return round((total - free) / total * 100, 1)


def _space(field: str) -> Callable[[FoscamData], int | None]:
    """Leer un campo de espacio de la SD (la cámara lo devuelve en kilobytes)."""

    def _reader(data: FoscamData) -> int | None:
        value = data.state_int(field, -1)
        return None if value < 0 else value

    return _reader


def _infra_mode(data: FoscamData) -> str | None:
    """Traducir el modo del LED infrarrojo a una opción de enumeración."""
    raw = str(data.infra.get("mode", "")).strip()
    if not raw.lstrip("-").isdigit():
        return None
    return INFRA_MODES.get(int(raw))


SENSORS: tuple[FoscamSensorDescription, ...] = (
    FoscamSensorDescription(
        key="motion_status",
        translation_key="motion_status",
        device_class=SensorDeviceClass.ENUM,
        options=ALARM_OPTIONS,
        icon="mdi:motion-sensor",
        value_fn=_mapped("motionDetectAlarm", ALARM_STATES),
    ),
    FoscamSensorDescription(
        key="sound_status",
        translation_key="sound_status",
        device_class=SensorDeviceClass.ENUM,
        options=ALARM_OPTIONS,
        entity_registry_enabled_default=False,
        icon="mdi:ear-hearing",
        value_fn=_mapped("soundAlarm", ALARM_STATES),
    ),
    FoscamSensorDescription(
        key="sd_status",
        translation_key="sd_status",
        device_class=SensorDeviceClass.ENUM,
        options=SD_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:micro-sd",
        value_fn=_mapped("sdState", SD_STATES),
    ),
    FoscamSensorDescription(
        key="sd_free_space",
        translation_key="sd_free_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.KILOBYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_space("sdFreeSpace"),
    ),
    FoscamSensorDescription(
        key="sd_total_space",
        translation_key="sd_total_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.KILOBYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_space("sdTotalSpace"),
    ),
    FoscamSensorDescription(
        key="sd_used_percent",
        translation_key="sd_used_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:micro-sd",
        value_fn=_sd_used_percent,
    ),
    FoscamSensorDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
        value_fn=lambda data: data.state.get("wifiConnectedAP") or None,
    ),
    FoscamSensorDescription(
        key="infra_led_mode",
        translation_key="infra_led_mode",
        device_class=SensorDeviceClass.ENUM,
        options=INFRA_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:led-outline",
        value_fn=_infra_mode,
    ),
    FoscamSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:chip",
        value_fn=lambda data: data.info.get("firmwareVer") or None,
    ),
    FoscamSensorDescription(
        key="ntp_status",
        translation_key="ntp_status",
        device_class=SensorDeviceClass.ENUM,
        options=LINK_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_mapped("ntpState", LINK_STATES),
    ),
    FoscamSensorDescription(
        key="ddns_status",
        translation_key="ddns_status",
        device_class=SensorDeviceClass.ENUM,
        options=LINK_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_mapped("ddnsState", LINK_STATES),
    ),
    FoscamSensorDescription(
        key="upnp_status",
        translation_key="upnp_status",
        device_class=SensorDeviceClass.ENUM,
        options=LINK_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_mapped("upnpState", LINK_STATES),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoscamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dar de alta los sensores."""
    coordinator = entry.runtime_data
    async_add_entities(FoscamSensor(coordinator, description) for description in SENSORS)


class FoscamSensor(FoscamEntity, SensorEntity):
    """Sensor respaldado por el coordinador."""

    entity_description: FoscamSensorDescription

    @property
    def native_value(self) -> str | int | float | None:
        """Valor actual."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
