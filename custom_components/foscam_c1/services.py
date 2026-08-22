"""Servicios de la integración Foscam C1."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .api import FoscamError
from .const import (
    ATTR_COMMAND,
    ATTR_FILENAME,
    ATTR_PARAMS,
    DOMAIN,
    SERVICE_CGI_COMMAND,
    SERVICE_SET_MOTION_CONFIG,
    SERVICE_SNAPSHOT,
)
from .coordinator import FoscamCoordinator

_LOGGER = logging.getLogger(__name__)

#: Comandos que no dejamos ejecutar desde el servicio genérico. No es una
#: medida de seguridad (quien tenga las credenciales puede llamarlos a mano),
#: sino una red para no destrozar la cámara con una automatización mal escrita.
BLOCKED_COMMANDS = {
    "restoreToFactorySetting",
    "setSystemFactoryDefault",
    "addAccount",
    "delAccount",
    "changeUserName",
    "changePassword",
    "setUserPwd",
    "setUserName",
    "setMac",
    "setIpInfo",
    "setPortInfo",
    "setWifiSetting",
    "usbUpgrade",
    "upgradeSystem",
    "upgradeFirmware",
}

BASE_SCHEMA = {vol.Required(ATTR_DEVICE_ID): cv.string}

CGI_COMMAND_SCHEMA = vol.Schema(
    {
        **BASE_SCHEMA,
        vol.Required(ATTR_COMMAND): cv.string,
        vol.Optional(ATTR_PARAMS, default={}): {cv.string: cv.string},
    }
)

SET_MOTION_SCHEMA = vol.Schema(
    {
        **BASE_SCHEMA,
        vol.Required(ATTR_PARAMS): {cv.string: cv.string},
    }
)

SNAPSHOT_SCHEMA = vol.Schema(
    {
        **BASE_SCHEMA,
        vol.Required(ATTR_FILENAME): cv.string,
    }
)


def _get_coordinator(hass: HomeAssistant, device_id: str) -> FoscamCoordinator:
    """Resolver el coordinador a partir del dispositivo indicado."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Dispositivo desconocido: {device_id}")

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
            coordinator = entry.runtime_data
            if isinstance(coordinator, FoscamCoordinator):
                return coordinator

    raise ServiceValidationError(
        f"El dispositivo {device_id} no pertenece a la integración {DOMAIN}"
    )


async def _async_cgi_command(call: ServiceCall) -> ServiceResponse:
    """Ejecutar un comando CGI arbitrario y devolver su respuesta."""
    command: str = call.data[ATTR_COMMAND]
    if command in BLOCKED_COMMANDS:
        raise ServiceValidationError(
            f"El comando '{command}' está bloqueado por esta integración; "
            "usa el panel web de la cámara si de verdad quieres ejecutarlo"
        )

    coordinator = _get_coordinator(call.hass, call.data[ATTR_DEVICE_ID])
    try:
        result = await coordinator.client.async_command(command, call.data[ATTR_PARAMS])
    except FoscamError as err:
        raise HomeAssistantError(str(err)) from err
    return {"command": command, "result": result}


async def _async_set_motion_config(call: ServiceCall) -> ServiceResponse:
    """Cambiar campos sueltos de la configuración de movimiento."""
    coordinator = _get_coordinator(call.hass, call.data[ATTR_DEVICE_ID])
    try:
        await coordinator.async_update_motion(**call.data[ATTR_PARAMS])
    except FoscamError as err:
        raise HomeAssistantError(str(err)) from err
    return {"motion": dict(coordinator.data.motion)}


async def _async_snapshot(call: ServiceCall) -> ServiceResponse:
    """Guardar una foto fija de la cámara en la ruta indicada."""
    hass = call.hass
    filename: str = call.data[ATTR_FILENAME]
    if not hass.config.is_allowed_path(filename):
        raise ServiceValidationError(
            f"'{filename}' no está en allowlist_external_dirs; añádelo en configuration.yaml"
        )

    coordinator = _get_coordinator(hass, call.data[ATTR_DEVICE_ID])
    try:
        image = await coordinator.client.async_snapshot()
    except FoscamError as err:
        raise HomeAssistantError(str(err)) from err

    def _write() -> None:
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)

    await hass.async_add_executor_job(_write)
    return {"filename": filename, "size": len(image)}


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Registrar los servicios del dominio (una sola vez)."""
    if hass.services.has_service(DOMAIN, SERVICE_CGI_COMMAND):
        return

    services: list[tuple[str, Any, vol.Schema]] = [
        (SERVICE_CGI_COMMAND, _async_cgi_command, CGI_COMMAND_SCHEMA),
        (SERVICE_SET_MOTION_CONFIG, _async_set_motion_config, SET_MOTION_SCHEMA),
        (SERVICE_SNAPSHOT, _async_snapshot, SNAPSHOT_SCHEMA),
    ]
    for name, handler, schema in services:
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
