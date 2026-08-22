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
    ALARM_COMMANDS,
    ALARM_MOTION,
    CMD_CLOSE_INFRA,
    CMD_GET_DEV_INFO,
    CMD_GET_DEV_STATE,
    CMD_GET_INFRA,
    CMD_OPEN_INFRA,
    CMD_REBOOT,
    CMD_SET_INFRA,
    CMD_SNAP,
    DEFAULT_TIMEOUT,
    MOTION_VARIANT_LEGACY,
    MOTION_VARIANT_V1,
    STREAM_PATHS,
    normalize_stream,
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

#: Códigos de rechazo. -2 es «usuario o contraseña incorrectos»; -3 es
#: «la cuenta existe pero no tiene privilegios para este comando».
AUTH_RESULTS = {-2, -3}

# Sólo elementos hoja: así el envoltorio <CGI_Result> no se traga el documento.
_TAG_RE = re.compile(r"<([A-Za-z_][\w.\-]*)>([^<]*)</\1>")


def _result_code(data: dict[str, str]) -> int:
    """Leer el campo <result>; su ausencia se trata como éxito."""
    try:
        return int(str(data.get("result", "0")).strip())
    except (TypeError, ValueError):
        return 0


class FoscamError(Exception):
    """Error genérico de la cámara."""


class FoscamConnectionError(FoscamError):
    """No se ha podido contactar con la cámara."""


class FoscamAuthError(FoscamError):
    """La cámara ha rechazado la petición por credenciales o privilegios."""

    def __init__(self, message: str, code: int | None = None) -> None:
        """Guardar el código de rechazo, si lo hay."""
        self.code = code
        super().__init__(message)

    @property
    def is_privilege_error(self) -> bool:
        """Indicar si el rechazo es por privilegios y no por contraseña.

        La cámara distingue entre «esta contraseña no vale» (-2) y «esta cuenta
        no puede ejecutar este comando» (-3). Para el usuario son dos problemas
        muy distintos, así que no los mezclamos.
        """
        return self.code == -3


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


#: Cómo se escriben `usr` y `pwd` dentro de la URL.
#:
#: `literal` es lo que hacen curl y la barra de direcciones del navegador:
#: escapar sólo lo que rompería la propia URL (`&`, `=`, `+`, `#`, `%`, el
#: espacio y unos pocos caracteres que aiohttp no acepta en crudo) y dejar el
#: resto tal cual. Muchos firmwares de Foscam **no descodifican** el `%XX` de
#: estos dos parámetros, así que una contraseña con `^` enviada como `%5E`
#: llega a la cámara como una contraseña distinta y el acceso se rechaza.
#:
#: `encoded` es la codificación porcentual completa y estándar. Se prueba
#: después, por si algún firmware sí la espera.
CREDENTIAL_MODE_LITERAL = "literal"
CREDENTIAL_MODE_ENCODED = "encoded"
_CREDENTIAL_MODES = (CREDENTIAL_MODE_LITERAL, CREDENTIAL_MODE_ENCODED)

#: Todo el ASCII imprimible salvo lo que rompería la URL. El espacio y los
#: caracteres de control quedan fuera del rango y sí se escapan.
_LITERAL_SAFE = "".join(chr(code) for code in range(33, 127) if chr(code) not in '&=+#%"<>\\')


def _literal(value: str) -> str:
    """Escapar sólo lo imprescindible, como haría curl."""
    return quote(value, safe=_LITERAL_SAFE)


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
        #: Cómo se escriben usr y pwd en la URL. Empezamos por el modo
        #: «literal», que es el que usan curl y la barra del navegador y el
        #: único que funciona en muchos firmwares. Ver _CREDENTIAL_MODES.
        self._credential_mode: str | None = None
        #: Variante de la API por alarma ("motion", "audio"), una vez detectada.
        self._alarm_variants: dict[str, str] = {}

    # -- Propiedades ------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """URL base de la cámara (sin credenciales)."""
        scheme = "https" if self._ssl else "http"
        return f"{scheme}://{self._host}:{self._port}"

    @property
    def motion_variant(self) -> str | None:
        """Variante de la API de detección de movimiento ya detectada."""
        return self._alarm_variants.get(ALARM_MOTION)

    @property
    def alarm_variants(self) -> dict[str, str]:
        """Variantes detectadas para cada alarma."""
        return dict(self._alarm_variants)

    # -- Capa de transporte -----------------------------------------------------

    def _build_url(self, cmd: str, params: dict[str, Any], mode: str) -> URL:
        """Construir la URL completa de la petición.

        Los parámetros del comando siempre van con codificación porcentual
        normal; lo único que cambia entre modos es cómo se escriben `usr` y
        `pwd`, porque es ahí donde los firmwares antiguos se atragantan.
        """
        query = {"cmd": cmd, **{k: str(v) for k, v in params.items()}}
        quoter = _literal if mode == CREDENTIAL_MODE_LITERAL else (lambda v: quote(v, safe=""))

        parts = [f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in query.items()]
        parts.append(f"usr={quoter(self._username)}")
        parts.append(f"pwd={quoter(self._password)}")
        return URL(f"{self.base_url}{CGI_PATH}?{'&'.join(parts)}", encoded=True)

    async def _request(self, cmd: str, params: dict[str, Any], mode: str) -> tuple[bytes, str]:
        """Ejecutar la petición HTTP y devolver (cuerpo, content-type)."""
        url = self._build_url(cmd, params, mode)
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
                raise FoscamAuthError(f"La cámara rechazó '{cmd}' con HTTP {err.status}") from err
            raise FoscamConnectionError(f"La cámara respondió HTTP {err.status} a '{cmd}'") from err
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise FoscamConnectionError(
                f"No se pudo contactar con la cámara en {self.base_url}: {err}"
            ) from err

    async def _attempt(
        self, cmd: str, params: dict[str, Any], mode: str
    ) -> tuple[dict[str, str], FoscamAuthError | None]:
        """Probar un modo de credenciales.

        Devuelve (datos, error). El error sólo se rellena cuando la cámara
        contesta con un 401/403 de HTTP, que es un rechazo tan válido como un
        `<result>` negativo y también merece que probemos el otro modo.
        """
        try:
            body, _ = await self._request(cmd, params, mode)
        except FoscamAuthError as err:
            return {}, err
        return _parse_response(body.decode("utf-8", errors="replace")), None

    async def async_command(self, cmd: str, params: dict[str, Any] | None = None) -> dict[str, str]:
        """Ejecutar un comando CGI y devolver sus campos como diccionario.

        Lanza FoscamAuthError si la cámara rechaza las credenciales o los
        privilegios, y FoscamCommandError para cualquier otro <result> distinto
        de 0.
        """
        params = params or {}
        _LOGGER.debug("Foscam -> %s (params: %s)", cmd, sorted(params))

        async with self._lock:
            # Una vez sabemos qué modo entiende esta cámara, no volvemos a
            # probar el otro: cada rechazo cuenta para el bloqueo por intentos
            # fallidos que aplican estos firmwares.
            candidates = (self._credential_mode,) if self._credential_mode else _CREDENTIAL_MODES
            data: dict[str, str] = {}
            http_error: FoscamAuthError | None = None

            for index, mode in enumerate(candidates):
                data, http_error = await self._attempt(cmd, params, mode)
                rejected = http_error is not None or _result_code(data) in AUTH_RESULTS
                if not rejected:
                    if self._credential_mode != mode:
                        _LOGGER.debug("Credenciales aceptadas en modo '%s'", mode)
                        self._credential_mode = mode
                    break
                if index + 1 < len(candidates):
                    _LOGGER.debug("'%s' rechazado en modo '%s'; probando el siguiente", cmd, mode)

            if http_error is not None:
                raise http_error

        code = _result_code(data)

        if code in AUTH_RESULTS:
            _LOGGER.warning("La cámara rechazó '%s' con result=%s", cmd, code)
            raise FoscamAuthError(f"'{cmd}': {RESULT_MESSAGES.get(code, 'acceso denegado')}", code)
        if code != 0:
            raise FoscamCommandError(cmd, code)

        data.pop("result", None)
        return data

    async def async_command_raw(self, cmd: str, params: dict[str, Any] | None = None) -> bytes:
        """Ejecutar un comando que devuelve binario (por ejemplo una foto)."""
        # Antes de pedir binario nos aseguramos de saber qué modo de
        # credenciales entiende la cámara, para no gastar aquí un intento.
        mode = self._credential_mode
        if mode is None:
            await self.async_command(CMD_GET_DEV_STATE)
            mode = self._credential_mode or CREDENTIAL_MODE_LITERAL

        async with self._lock:
            body, content_type = await self._request(cmd, params or {}, mode)
        if "xml" in content_type or body.lstrip()[:1] == b"<":
            data = _parse_response(body.decode("utf-8", errors="replace"))
            code = _result_code(data) or -7
            if code in AUTH_RESULTS:
                raise FoscamAuthError(
                    f"'{cmd}': {RESULT_MESSAGES.get(code, 'acceso denegado')}", code
                )
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

    def rtsp_url(self, stream: str, port: int) -> str:
        """Construir la URL RTSP del flujo indicado.

        Ojo con la codificacion, porque es **la contraria** que en el CGI. Ahi
        las credenciales viajan literales porque el firmware no descodifica el
        `%XX` (ver la nota de arriba); aqui el consumidor es ffmpeg, que si
        descodifica y espera la userinfo percent-encoded segun la RFC 3986. La
        misma contrasena, por tanto, se escribe de dos formas distintas segun
        por donde salga, y confundirlas da un fallo de credenciales que parece
        una contrasena mal escrita.

        `stream` es la clave de configuracion (`main`/`sub`), no la ruta: la
        clave va en minuscula porque hassfest lo exige para las traducciones del
        selector, mientras que la URL quiere `videoMain`/`videoSub`.

        La URL lleva la contrasena dentro, asi que no debe registrarse nunca en
        el log ni exponerse como atributo de una entidad.
        """
        user = quote(self._username, safe="")
        password = quote(self._password, safe="")
        ruta = STREAM_PATHS[normalize_stream(stream)]
        return f"rtsp://{user}:{password}@{self._host}:{port}/{ruta}"

    async def async_snapshot(self) -> bytes:
        """Pedir una foto fija a la cámara."""
        return await self.async_command_raw(CMD_SNAP)

    async def async_reboot(self) -> None:
        """Reiniciar la cámara."""
        await self.async_command(CMD_REBOOT)

    # -- Alarmas de movimiento y de sonido --------------------------------------
    #
    # Las dos se configuran igual (isEnable, linkage, sensitivity,
    # triggerInterval, scheduleN) y las dos tienen el mismo firmware partido en
    # dos variantes, así que comparten implementación.

    async def async_detect_alarm_variant(self, alarm: str) -> str:
        """Averiguar qué variante de la API soporta este firmware para `alarm`."""
        if (cached := self._alarm_variants.get(alarm)) is not None:
            return cached

        get_v1, _, get_legacy, _ = ALARM_COMMANDS[alarm]
        privilege_error: FoscamAuthError | None = None

        for cmd, variant in ((get_v1, MOTION_VARIANT_V1), (get_legacy, MOTION_VARIANT_LEGACY)):
            try:
                await self.async_command(cmd)
            except FoscamCommandError as err:
                if err.unsupported:
                    continue
                raise
            except FoscamAuthError as err:
                if err.is_privilege_error:
                    # Un -3 aquí es ambiguo: puede ser que este firmware no
                    # implemente el comando, o que la cuenta no sea de
                    # administrador. Probamos la otra variante antes de decidir.
                    privilege_error = err
                    continue
                raise
            self._alarm_variants[alarm] = variant
            _LOGGER.debug("Variante de la alarma '%s': %s", alarm, variant)
            return variant

        if privilege_error is not None:
            raise privilege_error
        raise FoscamError(
            f"La cámara no responde ni a {get_legacy} ni a {get_v1} con este firmware"
        )

    async def async_get_alarm_config(self, alarm: str) -> dict[str, str]:
        """Leer la configuración completa de una alarma."""
        variant = await self.async_detect_alarm_variant(alarm)
        get_v1, _, get_legacy, _ = ALARM_COMMANDS[alarm]
        return await self.async_command(get_v1 if variant == MOTION_VARIANT_V1 else get_legacy)

    async def async_update_alarm_config(self, alarm: str, **changes: Any) -> dict[str, str]:
        """Modificar una alarma sin perder el resto de sus ajustes.

        `setMotionDetectConfig` y `setAudioAlarmConfig` son *destructivos*: los
        parámetros que no se envían vuelven a su valor por defecto. Por eso
        leemos la configuración actual, aplicamos encima sólo los campos que
        cambian y la reenviamos entera.
        """
        variant = await self.async_detect_alarm_variant(alarm)
        payload: dict[str, Any] = dict(await self.async_get_alarm_config(alarm))
        payload.update({k: v for k, v in changes.items() if v is not None})
        _, set_v1, _, set_legacy = ALARM_COMMANDS[alarm]
        await self.async_command(set_v1 if variant == MOTION_VARIANT_V1 else set_legacy, payload)
        return payload

    # Atajos para la alarma de movimiento, que es la que usa el config flow.

    async def async_detect_motion_variant(self) -> str:
        """Averiguar qué API de detección de movimiento soporta este firmware."""
        return await self.async_detect_alarm_variant(ALARM_MOTION)

    async def async_get_motion_config(self) -> dict[str, str]:
        """Leer la configuración completa de detección de movimiento."""
        return await self.async_get_alarm_config(ALARM_MOTION)

    async def async_update_motion_config(self, **changes: Any) -> dict[str, str]:
        """Modificar la detección de movimiento conservando el resto."""
        return await self.async_update_alarm_config(ALARM_MOTION, **changes)

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
