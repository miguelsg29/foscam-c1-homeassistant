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
    ALARM_AUDIO,
    ALARM_MOTION,
    CMD_GET_INFRA,
    CMD_GET_LED,
    CMD_GET_VOICE,
    CMD_GET_VOLUME,
    DEFAULT_INFO_INTERVAL,
    DEFAULT_SCAN_INTERVAL_CONFIG,
    DEFAULT_SCAN_INTERVAL_STATE,
    DOMAIN,
    INFRA_AUTO,
    INFRA_MODE_AUTO,
    INFRA_ON,
)

_LOGGER = logging.getLogger(__name__)

type FoscamConfigEntry = ConfigEntry[FoscamCoordinator]

#: Comandos de sólo lectura usados para detectar qué soporta el modelo concreto.
CAPABILITY_PROBES: dict[str, str] = {
    "infra_led": CMD_GET_INFRA,
    "siren": "getSirenConfig",
    "white_light": "getWhiteLightBrightness",
    "audio_alarm": "getAudioAlarmConfig",
    "volume": CMD_GET_VOLUME,
    "voice": CMD_GET_VOICE,
    "status_led": CMD_GET_LED,
}


@dataclass(slots=True)
class FoscamData:
    """Instantánea combinada de todo lo que leemos de la cámara."""

    state: dict[str, str] = field(default_factory=dict)
    motion: dict[str, str] = field(default_factory=dict)
    audio: dict[str, str] = field(default_factory=dict)
    info: dict[str, str] = field(default_factory=dict)
    infra: dict[str, str] = field(default_factory=dict)
    siren: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)
    volume: int | None = None
    muted: bool | None = None
    status_led: bool | None = None

    def state_int(self, key: str, default: int = -1) -> int:
        """Leer un campo numérico de getDevState."""
        return _as_int(self.state.get(key), default)

    def motion_int(self, key: str, default: int = -1) -> int:
        """Leer un campo numérico de la configuración de movimiento."""
        return _as_int(self.motion.get(key), default)

    def audio_int(self, key: str, default: int = -1) -> int:
        """Leer un campo numérico de la configuración de sonido."""
        return _as_int(self.audio.get(key), default)

    def alarm_int(self, alarm: str, key: str, default: int = -1) -> int:
        """Leer un campo numérico de la alarma indicada."""
        source = self.audio if alarm == ALARM_AUDIO else self.motion
        return _as_int(source.get(key), default)


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
                data.motion = await self.client.async_get_alarm_config(ALARM_MOTION)
                if data.capabilities.get("audio_alarm"):
                    data.audio = await self.client.async_get_alarm_config(ALARM_AUDIO)
                if data.capabilities.get("infra_led"):
                    data.infra = await self.client.async_get_infra_config()
                if data.capabilities.get("siren"):
                    data.siren = await self.client.async_command("getSirenConfig")
                if data.capabilities.get("volume"):
                    data.volume = await self.client.async_get_volume()
                if data.capabilities.get("voice"):
                    data.muted = await self.client.async_get_muted()
                if data.capabilities.get("status_led"):
                    data.status_led = await self.client.async_get_status_led()
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

    async def async_update_alarm(self, alarm: str, **changes: Any) -> None:
        """Cambiar la configuración de una alarma y refrescar el estado."""
        payload = await self.client.async_update_alarm_config(alarm, **changes)
        # Reflejamos el cambio de inmediato para que la UI no «rebote».
        if self.data is not None:
            reflected = {k: str(v) for k, v in payload.items()}
            if alarm == ALARM_AUDIO:
                self.data.audio = reflected
            else:
                self.data.motion = reflected
        self.invalidate_config()
        await self.async_request_refresh()

    async def async_update_motion(self, **changes: Any) -> None:
        """Cambiar la configuración de movimiento y refrescar el estado."""
        await self.async_update_alarm(ALARM_MOTION, **changes)

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

    async def async_set_infra_choice(self, choice: str) -> None:
        """Aplicar automático / encendido / apagado al LED infrarrojo."""
        if choice == INFRA_AUTO:
            await self.client.async_set_infra_mode(INFRA_MODE_AUTO)
        else:
            # `async_set_infra_led` ya pasa a manual antes de encender o apagar:
            # en modo automático la cámara ignora los dos comandos.
            await self.client.async_set_infra_led(choice == INFRA_ON)
        self.invalidate_config()
        await self.async_request_refresh()

    async def async_set_volume(self, volume: int) -> None:
        """Fijar el volumen del dispositivo y reflejarlo de inmediato."""
        await self.client.async_set_volume(volume)
        if self.data is not None:
            self.data.volume = int(volume)
        self.invalidate_config()
        await self.async_request_refresh()

    async def async_set_muted(self, muted: bool) -> None:
        """Silenciar o restablecer el sonido y reflejarlo de inmediato."""
        await self.client.async_set_muted(muted)
        if self.data is not None:
            self.data.muted = muted
        self.invalidate_config()
        await self.async_request_refresh()

    async def async_set_status_led(self, on: bool) -> None:
        """Encender o apagar el LED de estado y reflejarlo de inmediato."""
        await self.client.async_set_status_led(on)
        if self.data is not None:
            self.data.status_led = on
        self.invalidate_config()
        await self.async_request_refresh()

    # -- Ayudas -----------------------------------------------------------------

    @property
    def serial(self) -> str | None:
        """Número de serie de la cámara, si se conoce."""
        return self.data.info.get("serialNo") if self.data else None
