"""Botones de acción de la cámara Foscam."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FoscamError
from .const import AREA_ALL, SCHEDULE_ALWAYS
from .coordinator import FoscamConfigEntry, FoscamCoordinator
from .entity import FoscamEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class FoscamButtonDescription(ButtonEntityDescription):
    """Describe un botón de acción."""

    press_fn: Callable[[FoscamCoordinator], Coroutine[Any, Any, None]]


async def _reboot(coordinator: FoscamCoordinator) -> None:
    """Reiniciar la cámara."""
    await coordinator.client.async_reboot()


async def _full_coverage(coordinator: FoscamCoordinator) -> None:
    """Poner la detección a 24/7 sobre toda la imagen.

    Equivale a los `schedule0..6=281474976710655` y `area0..9=1023` que había
    que repetir a mano en cada llamada CGI.
    """
    changes: dict[str, int] = {f"schedule{day}": SCHEDULE_ALWAYS for day in range(7)}
    changes.update({f"area{index}": AREA_ALL for index in range(10)})
    await coordinator.async_update_motion(**changes)


BUTTONS: tuple[FoscamButtonDescription, ...] = (
    FoscamButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_reboot,
    ),
    FoscamButtonDescription(
        key="full_coverage",
        translation_key="full_coverage",
        icon="mdi:select-all",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_full_coverage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoscamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dar de alta los botones."""
    coordinator = entry.runtime_data
    async_add_entities(FoscamButton(coordinator, description) for description in BUTTONS)


class FoscamButton(FoscamEntity, ButtonEntity):
    """Botón que dispara un comando CGI."""

    entity_description: FoscamButtonDescription

    async def async_press(self) -> None:
        """Ejecutar la acción."""
        try:
            await self.entity_description.press_fn(self.coordinator)
        except FoscamError as err:
            raise HomeAssistantError(
                f"No se pudo ejecutar '{self.entity_description.key}': {err}"
            ) from err
