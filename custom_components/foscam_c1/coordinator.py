"""Coordinador de actualizaciones de la cámara Foscam."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FoscamAuthError, FoscamClient, FoscamError
from .const import (
    CMD_GET_INFRA,
    DEFAULT_INFO_INTERVAL,
    DEFAULT_SCAN_INTERVAL_CONFIG,
    DEFAULT_SCAN_INTERVAL_STATE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type FoscamConfigEntry = ConfigEntry[FoscamCoordinator]

#: Comandos de sólo lectura usados para detectar qué soporta el modelo concreto.
CAPABILITY_PROBES: dict[str, str] = {
    "infra_led": CMD_GET_INFRA,
    "siren": "getSirenConfig",
    "white_light": "getWhiteLightBrightness",
    "audio_alarm": "getAudioAlarmConfig",
}


@dataclass(slots=True)
class FoscamData:
    """Instantánea combinada de todo lo que leemos de la cámara."""

    state: dict[str, str] = field(default_factory=dict)
    motion: dict[str, str] = field(default_factory=dict)
    info: dict[str, str] = field(default_factory=dict)
    infra: dict[str, str] = field(default_factory=dict)
    siren: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)

    def state_int(self, key: str, default: int = -1) -> int:
        """Leer un campo numérico de getDevState."""
        return _as_int(self.state.get(key), default)

    def motion_int(self, key: str, default: int = -1) -> int:
        """Leer un campo numérico de la configuración de movimiento."""
        return _as_int(self.motion.get(key), default)


def _as_int(value: Any, default: int = -1) -> int:
    """Convertir a entero tolerando valores vacíos o basura."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class FoscamCoordinator(DataUpdateCoordinator[FoscamData]):
    """Sondea la cámara escalonando las lecturas según lo que cambia de verdad.

    - `getDevState` se lee en cada ciclo: es lo que dispara las automatizaciones.
    - La configuración de movimiento y el LED IR se leen cada minuto, o justo
      después de que nosotros los cambiemos.
    - La información del dispositivo se lee cada 15 minutos.
    """

    config_entry: FoscamConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FoscamConfigEntry,
        client: FoscamClient,
        *,
        state_interval: int = DEFAULT_SCAN_INTERVAL_STATE,
        config_interval: int = DEFAULT_SCAN_INTERVAL_CONFIG,
    ) -> None:
        """Inicializar el coordinador."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=state_interval),
        )
        self.client = client
        self._config_interval = config_interval
        self._last_config = 0.0
        self._last_info = 0.0
        self._probed = False
        self.data = FoscamData()

    # -- Ciclo de actualización -------------------------------------------------

    async def _async_update_data(self) -> FoscamData:
        """Leer la cámara respetando la cadencia de cada bloque."""
        data = self.data or FoscamData()
        now = monotonic()

        try:
            state = await self.client.async_get_dev_state()

            if not self._probed:
                data.capabilities = await self.client.async_probe(CAPABILITY_PROBES)
                self._probed = True

            if now - self._last_config >= self._config_interval:
                data.motion = await self.client.async_get_motion_config()
                if data.capabilities.get("infra_led"):
                    data.infra = await self.client.async_get_infra_config()
                if data.capabilities.get("siren"):
                    data.siren = await self.client.async_command("getSirenConfig")
                self._last_config = now

            if now - self._last_info >= DEFAULT_INFO_INTERVAL or not data.info:
                data.info = await self.client.async_get_dev_info()
                self._last_info = now

        except FoscamAuthError as err:
            raise UpdateFailed(str(err)) from err
        except FoscamError as err:
            raise UpdateFailed(str(err)) from err

        data.state = state
        return data

    # -- Escrituras -------------------------------------------------------------

    def invalidate_config(self) -> None:
        """Forzar que la próxima lectura recargue la configuración."""
        self._last_config = 0.0

    async def async_update_motion(self, **changes: Any) -> None:
        """Cambiar la configuración de movimiento y refrescar el estado."""
        payload = await self.client.async_update_motion_config(**changes)
        # Reflejamos el cambio de inmediato para que la UI no «rebote».
        if self.data is not None:
            self.data.motion = {k: str(v) for k, v in payload.items()}
        self.invalidate_config()
        await self.async_request_refresh()

    async def async_set_siren(self, on: bool) -> None:
        """Activar o desactivar la sirena (sólo en modelos que la llevan).

        Los distintos firmwares nombran el campo de activación de forma
        distinta, así que releemos la configuración y cambiamos la clave que
        exista, en lugar de asumir una.
        """
        current = dict(await self.client.async_command("getSirenConfig"))
        for key in ("isEnable", "enable", "sirenEnable", "isEnableSiren"):
            if key in current:
                current[key] = "1" if on else "0"
                break
        else:
            raise FoscamError("getSirenConfig no devolvió ningún campo de activación conocido")
        await self.client.async_command("setSirenConfig", current)
        self.invalidate_config()
        await self.async_request_refresh()

    async def async_set_infra_led(self, on: bool) -> None:
        """Encender o apagar el LED infrarrojo y refrescar."""
        await self.client.async_set_infra_led(on)
        self.invalidate_config()
        await self.async_request_refresh()

    # -- Ayudas -----------------------------------------------------------------

    @property
    def serial(self) -> str | None:
        """Número de serie de la cámara, si se conoce."""
        return self.data.info.get("serialNo") if self.data else None
