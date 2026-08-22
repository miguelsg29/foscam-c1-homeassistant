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


async def test_motion_variant_falls_back_to_legacy(api):
    """Si getMotionDetectConfig1 no existe, usamos el comando clásico."""
    session = FakeSession(
        {
            "getMotionDetectConfig1": "<CGI_Result><result>-1</result></CGI_Result>",
            "getMotionDetectConfig": MOTION_XML,
        }
    )
    client = _client(api, session)
    assert await client.async_detect_motion_variant() == api.MOTION_VARIANT_LEGACY


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


async def test_credentials_are_url_encoded(api):
    """Una contraseña con caracteres especiales viaja codificada."""
    session = FakeSession()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "user", "a b&c=d", ssl=True, verify_ssl=False
    )
    await client.async_command("getDevState")
    url = session.requests[-1]
    assert "pwd=a+b%26c%3Dd" in url or "pwd=a%20b%26c%3Dd" in url


async def test_raw_credentials_retry_on_auth_failure(api):
    """Si el firmware no descodifica el %XX, reintentamos en crudo una vez."""

    class Flaky(FakeSession):
        def get(self, url, **kwargs):
            text = str(url)
            self.requests.append(text)
            if "%" in text.split("pwd=", 1)[-1]:
                body = "<CGI_Result><result>-2</result></CGI_Result>"
            else:
                body = "<CGI_Result><result>0</result><mac>001122334455</mac></CGI_Result>"
            from .conftest import FakeResponse

            return FakeResponse(body.encode())

    session = Flaky()
    client = api.FoscamClient(
        session, "192.0.2.10", 443, "user", "p^ss*word", ssl=True, verify_ssl=False
    )
    data = await client.async_get_dev_info()
    assert data["mac"] == "001122334455"
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
