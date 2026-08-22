"""Pruebas del cliente CGI."""

from __future__ import annotations

import pytest

from .conftest import FakeSession

MOTION_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<CGI_Result>
<result>0</result>
<isEnable>1</isEnable>
<linkage>142</linkage>
<snapInterval>2</snapInterval>
<sensitivity>3</sensitivity>
<triggerInterval>10</triggerInterval>
<schedule0>281474976710655</schedule0>
<area0>1023</area0>
</CGI_Result>"""

DEV_STATE_XML = """<CGI_Result>
<result>0</result>
<motionDetectAlarm>2</motionDetectAlarm>
<sdState>1</sdState>
<sdFreeSpace>15000000</sdFreeSpace>
</CGI_Result>"""


def _client(api, session):
    return api.FoscamClient(session, "192.0.2.10", 443, "user", "p4ss", ssl=True, verify_ssl=False)


def test_parse_tolerates_broken_xml(api):
    """Un SSID con un & sin escapar no debe romper el parseo."""
    body = (
        "<CGI_Result><result>0</result>"
        "<wifiConnectedAP>Casa & Jardin</wifiConnectedAP></CGI_Result>"
    )
    parsed = api._parse_response(body)
    assert parsed["result"] == "0"
    assert parsed["wifiConnectedAP"] == "Casa & Jardin"


async def test_command_returns_fields_without_result(api):
    """El campo result se consume y no aparece en los datos."""
    session = FakeSession({"getDevState": DEV_STATE_XML})
    client = _client(api, session)
    data = await client.async_get_dev_state()
    assert "result" not in data
    assert data["motionDetectAlarm"] == "2"


async def test_auth_error_raises(api):
    """result=-2 se traduce en FoscamAuthError."""
    session = FakeSession({"getDevState": "<CGI_Result><result>-2</result></CGI_Result>"})
    client = _client(api, session)
    with pytest.raises(api.FoscamAuthError):
        await client.async_get_dev_state()


async def test_unsupported_command_is_flagged(api):
    """Los códigos de 'no soportado' se marcan como tales."""
    session = FakeSession({"getSirenConfig": "<CGI_Result><result>-4</result></CGI_Result>"})
    client = _client(api, session)
    with pytest.raises(api.FoscamCommandError) as excinfo:
        await client.async_command("getSirenConfig")
    assert excinfo.value.unsupported


async def test_motion_variant_falls_back_to_legacy(api, const):
    """Si getMotionDetectConfig1 no existe, usamos el comando clásico."""
    session = FakeSession(
        {
            "getMotionDetectConfig1": "<CGI_Result><result>-1</result></CGI_Result>",
            "getMotionDetectConfig": MOTION_XML,
        }
    )
    client = _client(api, session)
    assert await client.async_detect_motion_variant() == const.MOTION_VARIANT_LEGACY


async def test_update_motion_preserves_other_fields(api):
    """Cambiar isEnable no debe perder sensibilidad, horarios ni áreas.

    Es el fallo que tenía la configuración basada en curl: `setMotionDetectConfig`
    resetea todo lo que no se le envía.
    """
    session = FakeSession(
        {
            "getMotionDetectConfig1": "<CGI_Result><result>-1</result></CGI_Result>",
            "getMotionDetectConfig": MOTION_XML,
        }
    )
    client = _client(api, session)
    payload = await client.async_update_motion_config(isEnable=0)

    assert payload["isEnable"] == 0
    assert payload["sensitivity"] == "3"
    assert payload["schedule0"] == "281474976710655"
    assert payload["area0"] == "1023"

    sent = [url for url in session.requests if "cmd=setMotionDetectConfig" in url][-1]
    for field in ("linkage", "snapInterval", "triggerInterval", "schedule0", "area0"):
        assert f"{field}=" in sent


async def test_credentials_travel_literally_by_default(api):
    """Por defecto la contraseña viaja como la escribe curl o el navegador.

    Es la regresión que motivó este modo: una contraseña con `^` enviada como
    `%5E` llega a muchos firmwares de Foscam como otra contraseña distinta,
    porque no descodifican el porcentaje en usr ni en pwd.
    """
    session = FakeSession()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "camera_user", "Aq^Ub*Kx2Zt7", ssl=True, verify_ssl=False
    )
    await client.async_command("getDevState")
    assert "pwd=Aq^Ub*Kx2Zt7" in session.requests[-1]
    assert client._credential_mode == api.CREDENTIAL_MODE_LITERAL


async def test_url_breaking_characters_are_still_escaped(api):
    """Lo que rompería la URL se escapa incluso en modo literal."""
    session = FakeSession()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "user", "a&b=c#d e", ssl=True, verify_ssl=False
    )
    await client.async_command("getDevState")
    url = session.requests[-1]
    pwd = url.split("pwd=", 1)[1]
    assert pwd == "a%26b%3Dc%23d%20e"
    # Y sigue habiendo exactamente un parámetro pwd, no tres.
    assert url.count("&") == url.count("=") - 1


async def test_falls_back_to_percent_encoding(api):
    """Si el modo literal se rechaza, se prueba la codificación porcentual."""

    class OnlyEncoded(FakeSession):
        def get(self, url, **kwargs):
            from .conftest import FakeResponse

            text = str(url)
            self.requests.append(text)
            encoded = "%5E" in text.split("pwd=", 1)[-1]
            body = (
                "<CGI_Result><result>0</result><mac>001122334455</mac></CGI_Result>"
                if encoded
                else "<CGI_Result><result>-2</result></CGI_Result>"
            )
            return FakeResponse(body.encode())

    session = OnlyEncoded()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "user", "p^ssword", ssl=True, verify_ssl=False
    )
    data = await client.async_get_dev_info()
    assert data["mac"] == "001122334455"
    assert len(session.requests) == 2
    assert client._credential_mode == api.CREDENTIAL_MODE_ENCODED


async def test_working_mode_is_remembered(api):
    """Descubierto el modo, no se malgastan intentos con el otro.

    Importa porque estos firmwares bloquean la cuenta tras unos pocos
    rechazos: sondear en cada petición acabaría por dejarnos fuera.
    """

    class OnlyEncoded(FakeSession):
        def get(self, url, **kwargs):
            from .conftest import FakeResponse

            text = str(url)
            self.requests.append(text)
            ok = "%5E" in text.split("pwd=", 1)[-1]
            return FakeResponse(
                f"<CGI_Result><result>{0 if ok else -2}</result></CGI_Result>".encode()
            )

    session = OnlyEncoded()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "user", "p^ssword", ssl=True, verify_ssl=False
    )
    await client.async_get_dev_state()
    session.requests.clear()
    await client.async_get_dev_state()
    await client.async_get_dev_state()
    assert len(session.requests) == 2


async def test_snapshot_returns_bytes(api):
    """snapPicture2 devuelve el JPEG tal cual."""
    session = FakeSession({"snapPicture2": b"\xff\xd8\xff\xe0jpegdata"})
    client = _client(api, session)
    image = await client.async_snapshot()
    assert image.startswith(b"\xff\xd8")


async def test_probe_reports_capabilities(api):
    """El sondeo distingue comandos soportados de no soportados."""
    session = FakeSession(
        {
            "getInfraLedConfig": "<CGI_Result><result>0</result><mode>0</mode></CGI_Result>",
            "getSirenConfig": "<CGI_Result><result>-4</result></CGI_Result>",
        }
    )
    client = _client(api, session)
    result = await client.async_probe({"infra_led": "getInfraLedConfig", "siren": "getSirenConfig"})
    assert result == {"infra_led": True, "siren": False}


async def test_privilege_rejection_is_distinguished(api):
    """Un -3 se marca como problema de privilegios, no de contraseña."""
    session = FakeSession({"getDevState": "<CGI_Result><result>-3</result></CGI_Result>"})
    client = _client(api, session)
    with pytest.raises(api.FoscamAuthError) as excinfo:
        await client.async_get_dev_state()
    assert excinfo.value.is_privilege_error
    assert excinfo.value.code == -3


async def test_retry_also_fires_on_privilege_rejection(api):
    """El cambio de modo también se dispara con el código -3.

    Hay firmwares que ante unas credenciales que no reconocen contestan -3 en
    lugar de -2; si sólo reintentáramos ante un -2 daríamos por «sin permisos»
    una cuenta perfectamente válida.
    """

    class Flaky(FakeSession):
        def get(self, url, **kwargs):
            from .conftest import FakeResponse

            text = str(url)
            self.requests.append(text)
            literal = "^" in text.split("pwd=", 1)[-1]
            body = (
                "<CGI_Result><result>-3</result></CGI_Result>"
                if literal
                else "<CGI_Result><result>0</result><isEnable>1</isEnable></CGI_Result>"
            )
            return FakeResponse(body.encode())

    session = Flaky()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "user", "p^ssword", ssl=True, verify_ssl=False
    )
    data = await client.async_command("getMotionDetectConfig")
    assert data["isEnable"] == "1"
    assert len(session.requests) == 2


async def test_motion_variant_reports_privilege_error(api):
    """Si ninguna variante es accesible, el error habla de privilegios."""
    session = FakeSession(
        {
            "getMotionDetectConfig1": "<CGI_Result><result>-3</result></CGI_Result>",
            "getMotionDetectConfig": "<CGI_Result><result>-3</result></CGI_Result>",
        }
    )
    client = _client(api, session)
    with pytest.raises(api.FoscamAuthError) as excinfo:
        await client.async_detect_motion_variant()
    assert excinfo.value.is_privilege_error


async def test_privilege_rejection_falls_back_to_legacy(api, const):
    """Un -3 en la variante nueva no impide usar la clásica."""
    session = FakeSession(
        {
            "getMotionDetectConfig1": "<CGI_Result><result>-3</result></CGI_Result>",
            "getMotionDetectConfig": MOTION_XML,
        }
    )
    client = _client(api, session)
    assert await client.async_detect_motion_variant() == const.MOTION_VARIANT_LEGACY


AUDIO_XML = """<CGI_Result>
<result>0</result>
<isEnable>0</isEnable>
<linkage>4</linkage>
<sensitivity>1</sensitivity>
<triggerInterval>10</triggerInterval>
<schedule0>281474976710655</schedule0>
</CGI_Result>"""


async def test_audio_alarm_uses_its_own_commands(api, const):
    """La alarma de sonido habla con setAudioAlarmConfig, no con la de movimiento."""
    session = FakeSession(
        {
            "getAudioAlarmConfig1": "<CGI_Result><result>-1</result></CGI_Result>",
            "getAudioAlarmConfig": AUDIO_XML,
        }
    )
    client = _client(api, session)
    payload = await client.async_update_alarm_config(const.ALARM_AUDIO, isEnable=1)

    assert payload["isEnable"] == 1
    assert payload["sensitivity"] == "1"
    sent = [url for url in session.requests if "cmd=setAudioAlarmConfig" in url][-1]
    assert "triggerInterval=" in sent and "schedule0=" in sent
    assert not any("MotionDetect" in url for url in session.requests)


async def test_alarm_variants_are_detected_independently(api, const):
    """Cada alarma recuerda su propia variante de firmware.

    Un firmware puede exponer la versión moderna de una y la antigua de la otra,
    así que compartir la detección daría comandos incorrectos.
    """
    session = FakeSession(
        {
            "getMotionDetectConfig1": MOTION_XML,
            "getAudioAlarmConfig1": "<CGI_Result><result>-1</result></CGI_Result>",
            "getAudioAlarmConfig": AUDIO_XML,
        }
    )
    client = _client(api, session)
    assert await client.async_detect_alarm_variant(const.ALARM_MOTION) == const.MOTION_VARIANT_V1
    assert await client.async_detect_alarm_variant(const.ALARM_AUDIO) == const.MOTION_VARIANT_LEGACY
    assert client.motion_variant == const.MOTION_VARIANT_V1


def test_rtsp_url_percent_encodes_the_credentials(api):
    # Es la codificacion CONTRARIA que en el CGI: ahi las credenciales viajan
    # literales porque el firmware no descodifica, pero aqui el consumidor es
    # ffmpeg, que si descodifica y espera la userinfo segun la RFC 3986.
    session = FakeSession()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "camera_user", "Aq^Ub*Kx2Zt7", ssl=True, verify_ssl=False
    )
    url = client.rtsp_url("main", 88)
    assert url == "rtsp://camera_user:Aq%5EUb%2AKx2Zt7@192.0.2.10:88/videoMain"


def test_rtsp_url_escapes_what_would_break_the_authority(api):
    # Una `@` o unos `:` sin escapar partirian la userinfo y el host.
    session = FakeSession()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "us:er", "a@b/c", ssl=True, verify_ssl=False
    )
    url = client.rtsp_url("sub", 554)
    assert url == "rtsp://us%3Aer:a%40b%2Fc@192.0.2.10:554/videoSub"


def test_rtsp_url_uses_the_requested_stream_and_port(api):
    session = FakeSession()
    client = api.FoscamClient(session, "192.0.2.10", 443, "u", "p", ssl=True, verify_ssl=False)
    assert client.rtsp_url("main", 65534).endswith(":65534/videoMain")
    assert client.rtsp_url("sub", 88).endswith(":88/videoSub")


def test_rtsp_url_is_independent_of_the_cgi_scheme(api):
    # El RTSP no va por HTTPS aunque el CGI si: son puertos y protocolos
    # distintos, y confundirlos daba una URL que ffmpeg no abre.
    session = FakeSession()
    client = api.FoscamClient(session, "192.0.2.10", 443, "u", "p", ssl=True, verify_ssl=False)
    assert client.rtsp_url("main", 88).startswith("rtsp://")
    assert client.base_url.startswith("https://")


def test_rtsp_url_still_accepts_the_1_1_0_capitalised_values(api):
    # 1.1.0 guardaba "Main"/"Sub" en la entrada de configuracion. hassfest
    # obligo a pasarlas a minuscula, pero esas entradas siguen existiendo y no
    # deben quedarse sin directo por un cambio de nombre interno.
    session = FakeSession()
    client = api.FoscamClient(session, "192.0.2.10", 443, "u", "p", ssl=True, verify_ssl=False)
    assert client.rtsp_url("Main", 88).endswith("/videoMain")
    assert client.rtsp_url("Sub", 88).endswith("/videoSub")


def test_rtsp_url_falls_back_to_main_for_an_unknown_stream(api):
    # Mejor el flujo principal que una URL con una ruta inventada que ffmpeg
    # no sabria abrir.
    session = FakeSession()
    client = api.FoscamClient(session, "192.0.2.10", 443, "u", "p", ssl=True, verify_ssl=False)
    assert client.rtsp_url("loquesea", 88).endswith("/videoMain")
