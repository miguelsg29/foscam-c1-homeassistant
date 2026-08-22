"""Cliente asíncrono para la API CGI (CGIProxy.fcgi) de las cámaras Foscam HD."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import aiohttp
from yarl import URL

from .const import (
    CMD_CLOSE_INFRA,
    CMD_GET_DEV_INFO,
    CMD_GET_DEV_STATE,
    CMD_GET_INFRA,
    CMD_GET_MOTION,
    CMD_GET_MOTION1,
    CMD_OPEN_INFRA,
    CMD_REBOOT,
    CMD_SET_INFRA,
    CMD_SET_MOTION,
    CMD_SET_MOTION1,
    CMD_SNAP,
    DEFAULT_TIMEOUT,
    MOTION_VARIANT_LEGACY,
    MOTION_VARIANT_V1,
)

_LOGGER = logging.getLogger(__name__)

CGI_PATH = "/cgi-bin/CGIProxy.fcgi"

#: Códigos devueltos en <result> por CGIProxy.fcgi.
RESULT_MESSAGES: dict[int, str] = {
    0: "Success",
    -1: "CGI request string format error",
    -2: "Username or password error",
    -3: "Access denied",
    -4: "CGI execute failure",
    -5: "Timeout",
    -6: "Reserved",
    -7: "Unknown error",
    -8: "Unknown error",
}

#: Códigos que significan «este firmware no soporta el comando».
UNSUPPORTED_RESULTS = {-1, -4, -7, -8}

# Sólo elementos hoja: así el envoltorio <CGI_Result> no se traga el documento.
_TAG_RE = re.compile(r"<([A-Za-z_][\w.\-]*)>([^<]*)</\1>")


class FoscamError(Exception):
    """Error genérico de la cámara."""


class FoscamConnectionError(FoscamError):
    """No se ha podido contactar con la cámara."""


class FoscamAuthError(FoscamError):
    """Usuario o contraseña incorrectos, o privilegios insuficientes."""


class FoscamCommandError(FoscamError):
    """La cámara ha respondido con un código de error."""

    def __init__(self, command: str, code: int) -> None:
        """Guardar el comando y el código devuelto."""
        self.command = command
        self.code = code
        super().__init__(
            f"'{command}' devolvió {code} ({RESULT_MESSAGES.get(code, 'desconocido')})"
        )

    @property
    def unsupported(self) -> bool:
        """Indicar si el código sugiere que el firmware no soporta el comando."""
        return self.code in UNSUPPORTED_RESULTS


def _parse_response(body: str) -> dict[str, str]:
    """Convertir la respuesta XML de la cámara en un diccionario plano.

    Los firmwares de Foscam devuelven XML poco riguroso (SSID con caracteres
    sin escapar, codificaciones mixtas...), así que si el parseo estricto falla
    caemos a una extracción por expresión regular en lugar de romper.
    """
    body = body.strip().lstrip("﻿")
    if not body:
        return {}
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return {tag: value.strip() for tag, value in _TAG_RE.findall(body)}
    return {child.tag: (child.text or "").strip() for child in root}


class FoscamClient:
    """Envoltorio fino y asíncrono sobre CGIProxy.fcgi.

    El cliente no guarda estado de la cámara: sólo sabe hablar el protocolo.
    Las credenciales nunca se escriben en el log.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        ssl: bool = True,
        verify_ssl: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Inicializar el cliente."""
        self._session = session
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._ssl = ssl
        self._verify_ssl = verify_ssl
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()
        #: Algunos firmwares no descodifican el porcentaje en usr/pwd. Si la
        #: autenticación falla con credenciales codificadas lo reintentamos en
        #: crudo una vez y recordamos qué modo funciona.
        self._raw_credentials = False
        self._motion_variant: str | None = None

    # -- Propiedades ------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """URL base de la cámara (sin credenciales)."""
        scheme = "https" if self._ssl else "http"
        return f"{scheme}://{self._host}:{self._port}"

    @property
    def motion_variant(self) -> str | None:
        """Variante de la API de detección de movimiento ya detectada."""
        return self._motion_variant

    # -- Capa de transporte -----------------------------------------------------

    def _build_url(self, cmd: str, params: dict[str, Any], raw_creds: bool) -> URL:
        """Construir la URL completa de la petición."""
        query = {"cmd": cmd, **{k: str(v) for k, v in params.items()}}
        if raw_creds:
            # Codificamos todo menos las credenciales, que van tal cual.
            parts = [f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in query.items()]
            parts.append(f"usr={self._username}")
            parts.append(f"pwd={self._password}")
            return URL(f"{self.base_url}{CGI_PATH}?{'&'.join(parts)}", encoded=True)
        query["usr"] = self._username
        query["pwd"] = self._password
        return URL(f"{self.base_url}{CGI_PATH}").with_query(query)

    async def _request(
        self, cmd: str, params: dict[str, Any], raw_creds: bool
    ) -> tuple[bytes, str]:
        """Ejecutar la petición HTTP y devolver (cuerpo, content-type)."""
        url = self._build_url(cmd, params, raw_creds)
        try:
            async with self._session.get(
                url,
                timeout=self._timeout,
                ssl=self._verify_ssl if self._ssl else None,
            ) as response:
                response.raise_for_status()
                return await response.read(), response.headers.get("Content-Type", "")
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                raise FoscamAuthError(
                    f"La cámara rechazó las credenciales (HTTP {err.status})"
                ) from err
            raise FoscamConnectionError(f"La cámara respondió HTTP {err.status} a '{cmd}'") from err
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise FoscamConnectionError(
                f"No se pudo contactar con la cámara en {self.base_url}: {err}"
            ) from err

    async def async_command(self, cmd: str, params: dict[str, Any] | None = None) -> dict[str, str]:
        """Ejecutar un comando CGI y devolver sus campos como diccionario.

        Lanza FoscamCommandError si <result> no es 0.
        """
        params = params or {}
        _LOGGER.debug("Foscam -> %s (params: %s)", cmd, sorted(params))

        async with self._lock:
            body, _ = await self._request(cmd, params, self._raw_credentials)
            data = _parse_response(body.decode("utf-8", errors="replace"))

            if data.get("result") == "-2" and not self._raw_credentials:
                # Reintento con credenciales sin codificar (firmwares antiguos).
                _LOGGER.debug("Autenticación rechazada; reintentando con credenciales en crudo")
                body, _ = await self._request(cmd, params, True)
                retry = _parse_response(body.decode("utf-8", errors="replace"))
                if retry.get("result") != "-2":
                    self._raw_credentials = True
                    data = retry

        try:
            result = int(data.get("result", "0"))
        except ValueError:
            result = 0

        if result == -2 or result == -3:
            raise FoscamAuthError(f"'{cmd}': {RESULT_MESSAGES.get(result, 'acceso denegado')}")
        if result != 0:
            raise FoscamCommandError(cmd, result)

        data.pop("result", None)
        return data

    async def async_command_raw(self, cmd: str, params: dict[str, Any] | None = None) -> bytes:
        """Ejecutar un comando que devuelve binario (por ejemplo una foto)."""
        async with self._lock:
            body, content_type = await self._request(cmd, params or {}, self._raw_credentials)
        if "xml" in content_type or body.lstrip()[:1] == b"<":
            data = _parse_response(body.decode("utf-8", errors="replace"))
            code = int(data.get("result", "-7") or -7)
            if code == -2:
                raise FoscamAuthError(f"'{cmd}': usuario o contraseña incorrectos")
            raise FoscamCommandError(cmd, code)
        return body

    # -- Comandos de alto nivel -------------------------------------------------

    async def async_get_dev_state(self) -> dict[str, str]:
        """Leer el estado en vivo (alarmas, SD, wifi, IR...)."""
        return await self.async_command(CMD_GET_DEV_STATE)

    async def async_get_dev_info(self) -> dict[str, str]:
        """Leer la información del dispositivo (modelo, firmware, MAC...)."""
        return await self.async_command(CMD_GET_DEV_INFO)

    async def async_get_infra_config(self) -> dict[str, str]:
        """Leer la configuración del LED infrarrojo."""
        return await self.async_command(CMD_GET_INFRA)

    async def async_set_infra_mode(self, mode: int) -> None:
        """Fijar el modo del LED infrarrojo (0 = automático, 1 = manual)."""
        await self.async_command(CMD_SET_INFRA, {"mode": mode})

    async def async_set_infra_led(self, on: bool) -> None:
        """Encender o apagar el LED infrarrojo (requiere modo manual)."""
        await self.async_set_infra_mode(1)
        await self.async_command(CMD_OPEN_INFRA if on else CMD_CLOSE_INFRA)

    async def async_snapshot(self) -> bytes:
        """Pedir una foto fija a la cámara."""
        return await self.async_command_raw(CMD_SNAP)

    async def async_reboot(self) -> None:
        """Reiniciar la cámara."""
        await self.async_command(CMD_REBOOT)

    # -- Detección de movimiento ------------------------------------------------

    async def async_detect_motion_variant(self) -> str:
        """Averiguar qué API de detección de movimiento soporta este firmware."""
        if self._motion_variant is not None:
            return self._motion_variant
        for cmd, variant in (
            (CMD_GET_MOTION1, MOTION_VARIANT_V1),
            (CMD_GET_MOTION, MOTION_VARIANT_LEGACY),
        ):
            try:
                await self.async_command(cmd)
            except FoscamCommandError as err:
                if err.unsupported:
                    continue
                raise
            self._motion_variant = variant
            _LOGGER.debug("Variante de detección de movimiento: %s", variant)
            return variant
        raise FoscamError(
            "La cámara no responde ni a getMotionDetectConfig ni a "
            "getMotionDetectConfig1; revisa que el usuario tenga permisos de admin"
        )

    async def async_get_motion_config(self) -> dict[str, str]:
        """Leer la configuración completa de detección de movimiento."""
        variant = await self.async_detect_motion_variant()
        cmd = CMD_GET_MOTION1 if variant == MOTION_VARIANT_V1 else CMD_GET_MOTION
        return await self.async_command(cmd)

    async def async_update_motion_config(self, **changes: Any) -> dict[str, str]:
        """Modificar la detección de movimiento sin perder el resto de ajustes.

        `setMotionDetectConfig` es *destructivo*: los parámetros que no se envían
        vuelven a su valor por defecto. Por eso leemos la configuración actual,
        aplicamos encima sólo los campos que cambian y la reenviamos entera.
        """
        variant = await self.async_detect_motion_variant()
        current = await self.async_get_motion_config()
        payload: dict[str, Any] = dict(current)
        payload.update({k: v for k, v in changes.items() if v is not None})
        cmd = CMD_SET_MOTION1 if variant == MOTION_VARIANT_V1 else CMD_SET_MOTION
        await self.async_command(cmd, payload)
        return payload

    # -- Descubrimiento de capacidades ------------------------------------------

    async def async_probe(self, commands: dict[str, str]) -> dict[str, bool]:
        """Comprobar qué comandos opcionales soporta la cámara.

        `commands` es un mapa {clave_de_capacidad: comando_cgi_de_lectura}.
        """
        supported: dict[str, bool] = {}
        for key, cmd in commands.items():
            try:
                await self.async_command(cmd)
            except FoscamCommandError:
                supported[key] = False
            except FoscamError:
                supported[key] = False
            else:
                supported[key] = True
        return supported
