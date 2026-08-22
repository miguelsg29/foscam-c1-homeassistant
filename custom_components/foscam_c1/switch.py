"""Interruptores de la cámara Foscam."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FoscamError
from .const import (
    ALARM_DISABLED,
    LINKAGE_MAIL,
    LINKAGE_RECORD,
    LINKAGE_RING,
    LINKAGE_SNAP,
)
from .coordinator import FoscamConfigEntry, FoscamCoordinator, FoscamData
from .entity import FoscamEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class FoscamSwitchDescription(SwitchEntityDescription):
    """Describe un interruptor de la cámara."""

    is_on_fn: Callable[[FoscamData], bool | None]
    set_fn: Callable[[FoscamCoordinator, bool], Coroutine[Any, Any, None]]
    capability: str | None = None


def _linkage_is_on(bit: int) -> Callable[[FoscamData], bool | None]:
    """Devolver un lector del bit indicado del campo `linkage`."""

    def _reader(data: FoscamData) -> bool | None:
        linkage = data.motion_int("linkage")
        if linkage < 0:
            return None
        return bool(linkage & bit)

    return _reader


def _linkage_setter(bit: int) -> Callable[[FoscamCoordinator, bool], Coroutine[Any, Any, None]]:
    """Devolver un escritor que activa o desactiva el bit indicado."""

    async def _setter(coordinator: FoscamCoordinator, value: bool) -> None:
        current = coordinator.data.motion_int("linkage", 0)
        current = max(current, 0)
        new = current | bit if value else current & ~bit
        await coordinator.async_update_motion(linkage=new)

    return _setter


def _motion_is_on(data: FoscamData) -> bool | None:
    """Estado de la detección de movimiento.

    Preferimos `motionDetectAlarm` de getDevState porque se sondea cada pocos
    segundos; la configuración completa sólo se relee cada minuto.
    """
    alarm = data.state_int("motionDetectAlarm")
    if alarm >= 0:
        return alarm != ALARM_DISABLED
    enabled = data.motion_int("isEnable")
    return None if enabled < 0 else bool(enabled)


async def _motion_setter(coordinator: FoscamCoordinator, value: bool) -> None:
    """Activar o desactivar la detección de movimiento."""
    await coordinator.async_update_motion(isEnable=1 if value else 0)


async def _siren_setter(coordinator: FoscamCoordinator, value: bool) -> None:
    """Activar o desactivar la sirena."""
    await coordinator.async_set_siren(value)


def _siren_is_on(data: FoscamData) -> bool | None:
    """Leer el estado de la sirena de getSirenConfig."""
    for key in ("isEnable", "enable", "sirenEnable", "isEnableSiren"):
        if key in data.siren:
            return data.siren[key] == "1"
    return None


async def _infra_setter(coordinator: FoscamCoordinator, value: bool) -> None:
    """Encender o apagar el LED infrarrojo."""
    await coordinator.async_set_infra_led(value)


SWITCHES: tuple[FoscamSwitchDescription, ...] = (
    FoscamSwitchDescription(
        key="motion_detection",
        translation_key="motion_detection",
        icon="mdi:motion-sensor",
        is_on_fn=_motion_is_on,
        set_fn=_motion_setter,
    ),
    FoscamSwitchDescription(
        key="infra_led",
        translation_key="infra_led",
        icon="mdi:led-on",
        entity_category=EntityCategory.CONFIG,
        capability="infra_led",
        is_on_fn=lambda data: (
            None if data.state_int("infraLedState") < 0 else bool(data.state_int("infraLedState"))
        ),
        set_fn=_infra_setter,
    ),
    # Best-effort: la C1 no lleva sirena, así que esta entidad sólo aparece en
    # los modelos cuyo firmware responde a getSirenConfig.
    FoscamSwitchDescription(
        key="siren",
        translation_key="siren",
        icon="mdi:alarm-light",
        capability="siren",
        is_on_fn=_siren_is_on,
        set_fn=_siren_setter,
    ),
    FoscamSwitchDescription(
        key="linkage_ring",
        translation_key="linkage_ring",
        icon="mdi:bell-ring",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        is_on_fn=_linkage_is_on(LINKAGE_RING),
        set_fn=_linkage_setter(LINKAGE_RING),
    ),
    FoscamSwitchDescription(
        key="linkage_mail",
        translation_key="linkage_mail",
        icon="mdi:email-alert",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        is_on_fn=_linkage_is_on(LINKAGE_MAIL),
        set_fn=_linkage_setter(LINKAGE_MAIL),
    ),
    FoscamSwitchDescription(
        key="linkage_snap",
        translation_key="linkage_snap",
        icon="mdi:camera-plus",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_linkage_is_on(LINKAGE_SNAP),
        set_fn=_linkage_setter(LINKAGE_SNAP),
    ),
    FoscamSwitchDescription(
        key="linkage_record",
        translation_key="linkage_record",
        icon="mdi:record-rec",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_linkage_is_on(LINKAGE_RECORD),
        set_fn=_linkage_setter(LINKAGE_RECORD),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoscamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dar de alta los interruptores soportados por este modelo."""
    coordinator = entry.runtime_data
    capabilities = coordinator.data.capabilities if coordinator.data else {}
    async_add_entities(
        FoscamSwitch(coordinator, description)
        for description in SWITCHES
        if description.capability is None or capabilities.get(description.capability)
    )


class FoscamSwitch(FoscamEntity, SwitchEntity):
    """Interruptor genérico respaldado por la API CGI."""

    entity_description: FoscamSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Estado actual del interruptor."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Encender."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Apagar."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        """Escribir el nuevo estado en la cámara."""
        try:
            await self.entity_description.set_fn(self.coordinator, value)
        except FoscamError as err:
            raise HomeAssistantError(
                f"No se pudo cambiar '{self.entity_description.key}': {err}"
            ) from err
        self.async_write_ha_state()
