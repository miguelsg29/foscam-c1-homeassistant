"""Sensores binarios de la cámara Foscam."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ALARM_DETECTED, SD_STATE_NO_CARD, SD_STATE_OK
from .coordinator import FoscamConfigEntry, FoscamData
from .entity import FoscamEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class FoscamBinarySensorDescription(BinarySensorEntityDescription):
    """Describe un sensor binario de la cámara."""

    is_on_fn: Callable[[FoscamData], bool | None]


def _alarm(field: str) -> Callable[[FoscamData], bool | None]:
    """Leer un campo de alarma (0 desactivada, 1 sin alarma, 2 detectada)."""

    def _reader(data: FoscamData) -> bool | None:
        value = data.state_int(field)
        if value < 0:
            return None
        return value == ALARM_DETECTED

    return _reader


def _sd_problem(data: FoscamData) -> bool | None:
    """Marcar problema si hay tarjeta SD pero no está en estado correcto."""
    state = data.state_int("sdState")
    if state < 0 or state == SD_STATE_NO_CARD:
        return None
    return state != SD_STATE_OK


BINARY_SENSORS: tuple[FoscamBinarySensorDescription, ...] = (
    FoscamBinarySensorDescription(
        key="motion",
        translation_key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        is_on_fn=_alarm("motionDetectAlarm"),
    ),
    FoscamBinarySensorDescription(
        key="sound",
        translation_key="sound",
        device_class=BinarySensorDeviceClass.SOUND,
        is_on_fn=_alarm("soundAlarm"),
    ),
    FoscamBinarySensorDescription(
        key="io_alarm",
        translation_key="io_alarm",
        device_class=BinarySensorDeviceClass.SAFETY,
        entity_registry_enabled_default=False,
        is_on_fn=_alarm("IOAlarm"),
    ),
    FoscamBinarySensorDescription(
        key="recording",
        translation_key="recording",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda data: (
            None if data.state_int("record") < 0 else data.state_int("record") == 1
        ),
    ),
    FoscamBinarySensorDescription(
        key="wifi",
        translation_key="wifi",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda data: (
            None
            if data.state_int("isWifiConnected") < 0
            else data.state_int("isWifiConnected") == 1
        ),
    ),
    FoscamBinarySensorDescription(
        key="sd_problem",
        translation_key="sd_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_sd_problem,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoscamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dar de alta los sensores binarios."""
    coordinator = entry.runtime_data
    async_add_entities(
        FoscamBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class FoscamBinarySensor(FoscamEntity, BinarySensorEntity):
    """Sensor binario respaldado por getDevState."""

    entity_description: FoscamBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Estado actual."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.is_on_fn(self.coordinator.data)
