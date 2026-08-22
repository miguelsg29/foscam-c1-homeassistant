#!/usr/bin/env python3
"""Sonda de capacidades para cámaras Foscam con API CGIProxy.fcgi.

Recorre una lista de comandos de *sólo lectura* y anota cuáles soporta tu
cámara y qué campos devuelve cada uno. Sirve para dos cosas:

* saber qué entidades tiene sentido crear para tu modelo concreto;
* pegar el resultado en un issue sin filtrar tus datos (por defecto se
  enmascaran MAC, número de serie, SSID, URL de DDNS e IPs).

Sólo usa la biblioteca estándar. Ejemplo:

    python tools/probe_camera.py --host 192.0.2.10 --port 443 --user admin

La contraseña se pide por teclado si no se pasa con --password, para que no
quede en el historial de la shell. El archivo de salida está en .gitignore.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

READ_COMMANDS = [
    "getDevInfo",
    "getDevState",
    "getProductAllInfo",
    "getMotionDetectConfig",
    "getMotionDetectConfig1",
    "getAudioAlarmConfig",
    "getSirenConfig",
    "getWhiteLightBrightness",
    "getInfraLedConfig",
    "getIRLedState",
    "getSnapConfig",
    "getScheduleSnapConfig",
    "getAlarmRecordConfig",
    "getScheduleRecordConfig",
    "getRecordList2",
    "getSDCardStatus",
    "getSDCardInfo",
    "getWifiConfig",
    "getIPInfo",
    "getPortInfo",
    "getSystemTime",
    "getImageSetting",
    "getMirrorAndFlipSetting",
    "getVideoStreamParam",
    "getSubVideoStreamParam",
    "getOSDSetting",
    "getPTZPresetPointList",
    "getDevName",
    "getFirewallConfig",
    "getLogEntries",
]

#: Campos que enmascaramos antes de escribir el informe.
SENSITIVE_FIELDS = {
    "mac",
    "serialNo",
    "devName",
    "wifiConnectedAP",
    "ssid",
    "url",
    "ip",
    "gate",
    "mask",
    "dns1",
    "dns2",
    "user",
    "usr",
    "pwd",
    "password",
    "psk",
    "key1",
    "key2",
    "key3",
    "key4",
    "ddnsUser",
    "ddnsPwd",
    "host",
}
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
TAG_RE = re.compile(r"<([A-Za-z_][\w.\-]*)>([^<]*)</\1>")


def parse(body: str) -> dict[str, str]:
    """Convertir la respuesta XML en un diccionario, tolerando XML inválido."""
    body = body.strip().lstrip("﻿")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return {tag: value.strip() for tag, value in TAG_RE.findall(body)}
    return {child.tag: (child.text or "").strip() for child in root}


def redact(fields: dict[str, str]) -> dict[str, str]:
    """Enmascarar los campos que identifican tu cámara o tu red."""
    out: dict[str, str] = {}
    for key, value in fields.items():
        if key in SENSITIVE_FIELDS:
            out[key] = f"<oculto: {len(value)} caracteres>" if value else ""
        else:
            out[key] = IP_RE.sub("<ip-oculta>", value)
    return out


def call(base: str, user: str, password: str, cmd: str, context: ssl.SSLContext | None):
    """Ejecutar un comando y devolver (código, campos)."""
    query = urllib.parse.urlencode({"cmd": cmd, "usr": user, "pwd": password})
    url = f"{base}/cgi-bin/CGIProxy.fcgi?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "foscam-probe/1.0"})
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        body = response.read().decode("utf-8", errors="replace")
    fields = parse(body)
    code = fields.pop("result", "?")
    return code, fields


def main() -> int:
    """Punto de entrada."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", default=None)
    parser.add_argument("--no-ssl", action="store_true", help="usar http en vez de https")
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="no enmascarar (SÓLO para uso local; no publiques ese archivo)",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    password = args.password or getpass.getpass("Contraseña de la cámara: ")
    scheme = "http" if args.no_ssl else "https"
    base = f"{scheme}://{args.host}:{args.port}"

    context = None
    if not args.no_ssl:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    report: dict[str, object] = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "redacted": not args.no_redact,
        "commands": {},
    }
    supported: list[str] = []

    for cmd in READ_COMMANDS:
        try:
            code, fields = call(base, args.user, password, cmd, context)
        except urllib.error.HTTPError as err:
            report["commands"][cmd] = {"error": f"HTTP {err.code}"}
            print(f"  {cmd:<28} HTTP {err.code}")
            continue
        except OSError as err:
            print(f"  {cmd:<28} sin conexión: {err}", file=sys.stderr)
            report["commands"][cmd] = {"error": str(err)}
            continue

        if code == "0":
            supported.append(cmd)
            report["commands"][cmd] = {
                "result": code,
                "fields": fields if args.no_redact else redact(fields),
            }
            print(f"  {cmd:<28} OK ({len(fields)} campos)")
        else:
            report["commands"][cmd] = {"result": code}
            print(f"  {cmd:<28} result={code}")

    report["supported"] = supported

    out = Path(args.out or f"probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(supported)}/{len(READ_COMMANDS)} comandos soportados.")
    print(f"Informe escrito en {out}")
    if args.no_redact:
        print("AVISO: has usado --no-redact. Ese archivo contiene datos reales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
