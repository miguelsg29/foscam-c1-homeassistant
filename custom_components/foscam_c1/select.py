"""Desplegables: lo que es una lista de opciones y no un número ni un interruptor."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FoscamError
from .const import (
    ALARM_AUDIO,
    ALARM_MOTION,
    INFRA_AUTO,
    INFRA_CHOICES,
    INFRA_MODE_AUTO,
    INFRA_OFF,
    INFRA_ON,
    MOTION_VARIANT_LEGACY,
    SENSITIVITY_LABELS_LEGACY,
    SENSITIVITY_ORDER_LEGACY,
    SENSITIVITY_VALUES_LEGACY,
)
from .coordinator import FoscamConfigEntry, FoscamCoordinator, FoscamData
from .entity import FoscamEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class FoscamSelectDescription(SelectEntityDescription):
    """Describe un desplegable de la cámara."""

    current_fn: Callable[[FoscamData], str | None]
    select_fn: Callable[[FoscamCoordinator, str], Coroutine[Any, Any, None]]
    capability: str | None = None
    #: Sólo se crea si la alarma usa esta variante de firmware.
    alarm_variant: tuple[str, str] | None = None


def _infra_current(data: FoscamData) -> str | None:
    """Resolver el estado del infrarrojo combinando modo y encendido.

    Hacen falta las dos lecturas: `mode` dice si decide la cámara o nosotros, y
    sólo cuando decidimos nosotros tiene sentido mirar si está encendido.
    """
    raw = str(data.infra.get("mode", "")).strip()
    if not raw.lstrip("-").isdigit():
        return None
    if int(raw) == INFRA_MODE_AUTO:
        return INFRA_AUTO
    state = data.state_int("infraLedState")
    if state < 0:
        return None
    return INFRA_ON if state else INFRA_OFF


async def _infra_select(coordinator: FoscamCoordinator, option: str) -> None:
    await coordinator.async_set_infra_choice(option)


def _sensitivity_current(alarm: str) -> Callable[[FoscamData], str | None]:
    """Traducir el valor crudo de sensibilidad a su etiqueta."""

    def _current(data: FoscamData) -> str | None:
        leer = data.audio_int if alarm == ALARM_AUDIO else data.motion_int
        return SENSITIVITY_LABELS_LEGACY.get(leer("sensitivity"))

    return _current


_SelectFn = Callable[[FoscamCoordinator, str], Coroutine[Any, Any, None]]


def _sensitivity_select(alarm: str) -> _SelectFn:
    """Escribir la sensibilidad a partir de su etiqueta."""

    async def _select(coordinator: FoscamCoordinator, option: str) -> None:
        await coordinator.async_update_alarm(alarm, sensitivity=SENSITIVITY_VALUES_LEGACY[option])

    return _select


SELECTS: tuple[FoscamSelectDescription, ...] = (
    FoscamSelectDescription(
        key="infra_mode",
        translation_key="infra_mode",
        icon="mdi:light-flood-down",
        entity_category=EntityCategory.CONFIG,
        capability="infra_led",
        options=INFRA_CHOICES,
        current_fn=_infra_current,
        select_fn=_infra_select,
    ),
    # La sensibilidad del firmware antiguo es un enum, no una escala: el 2 es el
    # más sensible y el 4 el menos. Un deslizador 0-4 hace creer lo contrario,
    # así que en esa variante se presenta como desplegable con las etiquetas de
    # la app. La variante moderna sí es lineal (0-100) y sigue siendo `number`.
    FoscamSelectDescription(
        key="sensitivity_level",
        translation_key="sensitivity_level",
        icon="mdi:tune",
        entity_category=EntityCategory.CONFIG,
        options=SENSITIVITY_ORDER_LEGACY,
        alarm_variant=(ALARM_MOTION, MOTION_VARIANT_LEGACY),
        current_fn=_sensitivity_current(ALARM_MOTION),
        select_fn=_sensitivity_select(ALARM_MOTION),
    ),
    FoscamSelectDescription(
        key="sound_sensitivity_level",
        translation_key="sound_sensitivity_level",
        icon="mdi:volume-high",
        entity_category=EntityCategory.CONFIG,
        capability="audio_alarm",
        options=SENSITIVITY_ORDER_LEGACY,
        alarm_variant=(ALARM_AUDIO, MOTION_VARIANT_LEGACY),
        current_fn=_sensitivity_current(ALARM_AUDIO),
        select_fn=_sensitivity_select(ALARM_AUDIO),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoscamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dar de alta los desplegables que la cámara soporte."""
    coordinator = entry.runtime_data
    capabilities = coordinator.data.capabilities if coordinator.data else {}
    variants = coordinator.client.alarm_variants

    async_add_entities(
        FoscamSelect(coordinator, description)
        for description in SELECTS
        if (description.capability is None or capabilities.get(description.capability))
        and (
            description.alarm_variant is None
            or variants.get(description.alarm_variant[0]) == description.alarm_variant[1]
        )
    )


class FoscamSelect(FoscamEntity, SelectEntity):
    """Desplegable respaldado por un comando CGI."""

    entity_description: FoscamSelectDescription

    @property
    def current_option(self) -> str | None:
        """Opción activa."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.current_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        """Aplicar la opción elegida."""
        try:
            await self.entity_description.select_fn(self.coordinator, option)
        except FoscamError as err:
            raise HomeAssistantError(
                f"No se pudo cambiar '{self.entity_description.key}': {err}"
            ) from err
        self.async_write_ha_state()
