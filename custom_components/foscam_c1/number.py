"""Controles numéricos de la detección de movimiento."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FoscamError
from .const import ALARM_AUDIO, ALARM_MOTION, MOTION_VARIANT_LEGACY, SENSITIVITY_MAX
from .coordinator import FoscamConfigEntry, FoscamCoordinator, FoscamData
from .entity import FoscamEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class FoscamNumberDescription(NumberEntityDescription):
    """Describe un control numérico de la cámara."""

    field: str
    value_fn: Callable[[FoscamData], float | None]
    set_fn: Callable[[FoscamCoordinator, float], Coroutine[Any, Any, None]]
    dynamic_max: bool = False
    capability: str | None = None
    alarm: str = ALARM_MOTION


def _alarm_field(field: str, alarm: str = ALARM_MOTION) -> Callable[[FoscamData], float | None]:
    """Leer un campo numérico de la configuración de una alarma."""

    def _reader(data: FoscamData) -> float | None:
        value = data.alarm_int(alarm, field)
        return None if value < 0 else float(value)

    return _reader


def _alarm_setter(
    field: str, alarm: str = ALARM_MOTION
) -> Callable[[FoscamCoordinator, float], Coroutine[Any, Any, None]]:
    """Escribir un campo numérico conservando el resto de la configuración."""

    async def _setter(coordinator: FoscamCoordinator, value: float) -> None:
        await coordinator.async_update_alarm(alarm, **{field: int(value)})

    return _setter


NUMBERS: tuple[FoscamNumberDescription, ...] = (
    FoscamNumberDescription(
        key="sensitivity",
        translation_key="sensitivity",
        field="sensitivity",
        icon="mdi:tune",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.SLIDER,
        native_min_value=0,
        native_max_value=4,
        native_step=1,
        dynamic_max=True,
        value_fn=_alarm_field("sensitivity"),
        set_fn=_alarm_setter("sensitivity"),
    ),
    FoscamNumberDescription(
        key="trigger_interval",
        translation_key="trigger_interval",
        field="triggerInterval",
        icon="mdi:timer-outline",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=5,
        native_max_value=15,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=_alarm_field("triggerInterval"),
        set_fn=_alarm_setter("triggerInterval"),
    ),
    FoscamNumberDescription(
        key="snap_interval",
        translation_key="snap_interval",
        field="snapInterval",
        icon="mdi:camera-timer",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=1,
        native_max_value=10,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=_alarm_field("snapInterval"),
        set_fn=_alarm_setter("snapInterval"),
    ),
    FoscamNumberDescription(
        key="sound_sensitivity",
        translation_key="sound_sensitivity",
        field="sensitivity",
        alarm=ALARM_AUDIO,
        capability="audio_alarm",
        icon="mdi:volume-high",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.SLIDER,
        native_min_value=0,
        native_max_value=4,
        native_step=1,
        dynamic_max=True,
        value_fn=_alarm_field("sensitivity", ALARM_AUDIO),
        set_fn=_alarm_setter("sensitivity", ALARM_AUDIO),
    ),
    FoscamNumberDescription(
        key="sound_trigger_interval",
        translation_key="sound_trigger_interval",
        field="triggerInterval",
        alarm=ALARM_AUDIO,
        capability="audio_alarm",
        icon="mdi:timer-outline",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=5,
        native_max_value=15,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=_alarm_field("triggerInterval", ALARM_AUDIO),
        set_fn=_alarm_setter("triggerInterval", ALARM_AUDIO),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoscamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dar de alta los controles numéricos."""
    coordinator = entry.runtime_data
    capabilities = coordinator.data.capabilities if coordinator.data else {}
    async_add_entities(
        FoscamNumber(coordinator, description)
        for description in NUMBERS
        if description.capability is None or capabilities.get(description.capability)
    )


class FoscamNumber(FoscamEntity, NumberEntity):
    """Control numérico respaldado por setMotionDetectConfig."""

    entity_description: FoscamNumberDescription

    @property
    def native_value(self) -> float | None:
        """Valor actual."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def native_max_value(self) -> float:
        """Máximo permitido.

        La escala de sensibilidad depende del firmware (0-4 en los antiguos,
        0-100 en los nuevos) y algunas cámaras devuelven valores fuera de la
        escala que documenta Foscam, así que ampliamos el rango si hace falta
        en lugar de dejar la entidad en un estado inválido.
        """
        base = float(self.entity_description.native_max_value or 0)
        if not self.entity_description.dynamic_max:
            return base
        variants = self.coordinator.client.alarm_variants
        variant = variants.get(self.entity_description.alarm) or MOTION_VARIANT_LEGACY
        base = float(SENSITIVITY_MAX.get(variant, base))
        current = self.native_value or 0
        return max(base, float(current))

    async def async_set_native_value(self, value: float) -> None:
        """Escribir el nuevo valor en la cámara."""
        try:
            await self.entity_description.set_fn(self.coordinator, value)
        except FoscamError as err:
            raise HomeAssistantError(
                f"No se pudo cambiar '{self.entity_description.key}': {err}"
            ) from err
        self.async_write_ha_state()
