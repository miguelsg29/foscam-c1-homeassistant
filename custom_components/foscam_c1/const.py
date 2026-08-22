"""Constantes de la integración Foscam C1."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "foscam_c1"

# --- Opciones de configuración -------------------------------------------------
CONF_SSL: Final = "ssl"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_SCAN_INTERVAL_STATE: Final = "scan_interval_state"
CONF_SCAN_INTERVAL_CONFIG: Final = "scan_interval_config"
CONF_STREAM: Final = "stream"
CONF_RTSP_PORT: Final = "rtsp_port"
CONF_WEB_URL: Final = "web_url"

DEFAULT_PORT_HTTPS: Final = 443
DEFAULT_PORT_HTTP: Final = 88
DEFAULT_SSL: Final = True
DEFAULT_VERIFY_SSL: Final = False  # las Foscam usan un certificado autofirmado
DEFAULT_SCAN_INTERVAL_STATE: Final = 5
DEFAULT_SCAN_INTERVAL_CONFIG: Final = 60
DEFAULT_INFO_INTERVAL: Final = 900
DEFAULT_TIMEOUT: Final = 10

# El flujo principal da mas calidad; el secundario aguanta mejor una red pobre.
#
# En minusculas a proposito: hassfest exige que las claves de traduccion de un
# selector casen con [a-z0-9-_]+, y estos valores SON las claves. El nombre que
# espera la URL RTSP es otra cosa (videoMain/videoSub), y va en STREAM_PATHS.
STREAM_MAIN: Final = "main"
STREAM_SUB: Final = "sub"
STREAMS: Final = [STREAM_MAIN, STREAM_SUB]
DEFAULT_STREAM: Final = STREAM_MAIN

#: {clave de configuracion: ruta dentro de la URL RTSP}
STREAM_PATHS: Final = {
    STREAM_MAIN: "videoMain",
    STREAM_SUB: "videoSub",
}


def normalize_stream(valor: object) -> str:
    """Normalizar el flujo guardado a una de las claves válidas.

    La 1.1.0 guardaba "Main"/"Sub" con mayúscula inicial y hassfest obligó a
    pasarlas a minúscula. Las entradas creadas con aquella versión siguen ahí,
    así que hay dos sitios que tienen que tragarlas: la URL RTSP, que si no se
    quedaría sin flujo, y el desplegable de opciones, que rechaza un valor por
    defecto que no esté entre los suyos y deja el formulario sin abrir.

    Vive aquí y no en `config_flow.py` para que se pueda probar sin Home
    Assistant instalado, que es como corre la suite.
    """
    clave = str(valor).lower()
    return clave if clave in STREAMS else DEFAULT_STREAM


# Los modelos nuevos admiten RTSP en 88 y 554; los antiguos, en 88 y 65534.
# El 88 es el unico comun a todos, asi que es el valor por defecto.
DEFAULT_RTSP_PORT: Final = 88

MIN_SCAN_INTERVAL_STATE: Final = 2
MAX_SCAN_INTERVAL_STATE: Final = 300

# --- Claves internas del diccionario del coordinator ---------------------------
DATA_STATE: Final = "state"
DATA_MOTION: Final = "motion"
DATA_INFO: Final = "info"
DATA_INFRA: Final = "infra"
DATA_CAPABILITIES: Final = "capabilities"

# --- Comandos CGI --------------------------------------------------------------
CMD_GET_DEV_STATE: Final = "getDevState"
CMD_GET_DEV_INFO: Final = "getDevInfo"
CMD_GET_MOTION: Final = "getMotionDetectConfig"
CMD_SET_MOTION: Final = "setMotionDetectConfig"
CMD_GET_MOTION1: Final = "getMotionDetectConfig1"
CMD_SET_MOTION1: Final = "setMotionDetectConfig1"
CMD_GET_AUDIO: Final = "getAudioAlarmConfig"
CMD_SET_AUDIO: Final = "setAudioAlarmConfig"
CMD_GET_AUDIO1: Final = "getAudioAlarmConfig1"
CMD_SET_AUDIO1: Final = "setAudioAlarmConfig1"
CMD_GET_INFRA: Final = "getInfraLedConfig"
CMD_SET_INFRA: Final = "setInfraLedConfig"
CMD_OPEN_INFRA: Final = "openInfraLed"
CMD_CLOSE_INFRA: Final = "closeInfraLed"
CMD_SNAP: Final = "snapPicture2"
CMD_REBOOT: Final = "rebootSystem"

# Audio del dispositivo y LED de estado. Todos opcionales: se sondean al
# arrancar y las entidades sólo se crean si la cámara responde.
CMD_GET_VOLUME: Final = "getAudioVolume"
CMD_SET_VOLUME: Final = "setAudioVolume"
CMD_GET_VOICE: Final = "getVoiceEnableState"
CMD_SET_VOICE: Final = "setVoiceEnableState"
CMD_GET_LED: Final = "getLedEnableState"
CMD_SET_LED: Final = "setLedEnableState"

# Las dos alarmas que se configuran igual: movimiento y sonido. Comparten la
# forma de los parámetros (isEnable, linkage, sensitivity, triggerInterval,
# scheduleN) y el mismo problema: escribir es destructivo.
ALARM_MOTION: Final = "motion"
ALARM_AUDIO: Final = "audio"

#: {alarma: (leer_v1, escribir_v1, leer_legacy, escribir_legacy)}
ALARM_COMMANDS: Final = {
    ALARM_MOTION: (CMD_GET_MOTION1, CMD_SET_MOTION1, CMD_GET_MOTION, CMD_SET_MOTION),
    ALARM_AUDIO: (CMD_GET_AUDIO1, CMD_SET_AUDIO1, CMD_GET_AUDIO, CMD_SET_AUDIO),
}

# Variantes de firmware. Las Foscam antiguas (H.264 "1080p/720p" tipo C1)
# exponen setMotionDetectConfig con sensibilidad 0-4; los firmwares más nuevos
# exponen setMotionDetectConfig1 con sensibilidad 0-100 y campos extra de área.
MOTION_VARIANT_LEGACY: Final = "legacy"
MOTION_VARIANT_V1: Final = "v1"

SENSITIVITY_MAX: Final = {
    MOTION_VARIANT_LEGACY: 4,
    MOTION_VARIANT_V1: 100,
}

# Etiquetas de sensibilidad del firmware legacy.
#
# El valor NO es una escala: es un enum cuyo orden no tiene nada que ver con la
# sensibilidad. El 2 es el más sensible y el 4 el menos, así que presentarlo
# como un deslizador 0-4 hace creer justo lo contrario. Verificado contra la
# app del fabricante en agosto de 2026.
SENSITIVITY_LABELS_LEGACY: Final = {
    0: "low",
    1: "normal",
    2: "high",
    3: "lower",
    4: "lowest",
}

#: El orden en que los muestra la app, de más a menos sensible.
SENSITIVITY_ORDER_LEGACY: Final = ["high", "normal", "low", "lower", "lowest"]

#: {etiqueta: valor} para escribir.
SENSITIVITY_VALUES_LEGACY: Final = {v: k for k, v in SENSITIVITY_LABELS_LEGACY.items()}

# --- LED infrarrojo ------------------------------------------------------------
# `mode` 0 es automático y 1 manual; encendido y apagado son dos comandos
# aparte que además exigen estar en manual. Las tres cosas que le importan al
# usuario son un único desplegable.
INFRA_AUTO: Final = "auto"
INFRA_ON: Final = "on"
INFRA_OFF: Final = "off"
INFRA_CHOICES: Final = [INFRA_AUTO, INFRA_ON, INFRA_OFF]

INFRA_MODE_AUTO: Final = 0
INFRA_MODE_MANUAL: Final = 1

# --- Volumen -------------------------------------------------------------------
VOLUME_MIN: Final = 0
VOLUME_MAX: Final = 100

# --- Bits del campo `linkage` --------------------------------------------------
# bit0: Ring (zumbador)  bit1: Mail  bit2: Snap (foto)  bit3: Record (vídeo)
LINKAGE_RING: Final = 1 << 0
LINKAGE_MAIL: Final = 1 << 1
LINKAGE_SNAP: Final = 1 << 2
LINKAGE_RECORD: Final = 1 << 3

# --- Valores de estado ---------------------------------------------------------
ALARM_DISABLED: Final = 0
ALARM_NO_ALARM: Final = 1
ALARM_DETECTED: Final = 2

SD_STATE_NO_CARD: Final = 0
SD_STATE_OK: Final = 1
SD_STATE_READ_ONLY: Final = 2

# Todos los días de la semana habilitados, las 24 h (48 franjas de media hora).
SCHEDULE_ALWAYS: Final = 281474976710655
# Todas las celdas de la rejilla de detección activadas.
AREA_ALL: Final = 1023

# --- Servicios -----------------------------------------------------------------
SERVICE_CGI_COMMAND: Final = "cgi_command"
SERVICE_SET_MOTION_CONFIG: Final = "set_motion_config"
SERVICE_SNAPSHOT: Final = "snapshot"

ATTR_COMMAND: Final = "command"
ATTR_PARAMS: Final = "params"
ATTR_FILENAME: Final = "filename"
