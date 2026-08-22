"""Cámara: la imagen fija por CGI y el vídeo en directo por RTSP."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera, CameraEntityDescription, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FoscamError
from .const import (
    CONF_RTSP_PORT,
    CONF_STREAM,
    DEFAULT_RTSP_PORT,
    DEFAULT_STREAM,
)
from .coordinator import FoscamConfigEntry, FoscamCoordinator
from .entity import FoscamEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

CAMERA = CameraEntityDescription(key="camera")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoscamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dar de alta la cámara."""
    async_add_entities([FoscamCamera(entry.runtime_data, CAMERA)])


class FoscamCamera(FoscamEntity, Camera):
    """La cámara en sí: foto fija por CGI y vídeo por RTSP."""

    # Sin nombre propio: la entidad toma el del dispositivo, que es como se
    # espera de la entidad principal de una cámara.
    _attr_name = None

    def __init__(self, coordinator: FoscamCoordinator, description) -> None:
        """Inicializar la cámara."""
        FoscamEntity.__init__(self, coordinator, description)
        Camera.__init__(self)

        options = {**coordinator.config_entry.data, **coordinator.config_entry.options}
        self._stream = options.get(CONF_STREAM, DEFAULT_STREAM)
        self._rtsp_port = options.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)

        # Sin puerto RTSP no hay vídeo, pero la foto fija sigue funcionando:
        # se declara la capacidad sólo si de verdad se puede cumplir, para no
        # ofrecer un botón de directo que acabaría en error.
        if self._rtsp_port:
            self._attr_supported_features = CameraEntityFeature.STREAM

    async def stream_source(self) -> str | None:
        """Devolver la URL RTSP del flujo en directo.

        Nunca se registra en el log: lleva la contraseña dentro.
        """
        if not self._rtsp_port:
            return None
        return self.coordinator.client.rtsp_url(self._stream, self._rtsp_port)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Pedir una foto fija a la cámara.

        Devuelve None en vez de propagar si la cámara no responde: una imagen
        que falta se dibuja como hueco, mientras que una excepción aquí ensucia
        el log en cada refresco de la tarjeta.
        """
        try:
            return await self.coordinator.client.async_snapshot()
        except FoscamError as err:
            _LOGGER.debug("No se pudo obtener la imagen: %s", err)
            return None
