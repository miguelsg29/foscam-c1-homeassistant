"""Utilidades de test.

Cargamos `api.py` sin ejecutar el `__init__.py` de la integración, para que la
suite corra sin tener Home Assistant instalado: la lógica del protocolo CGI es
la parte que de verdad interesa probar y no depende de HA.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = ROOT / "custom_components" / "foscam_c1"
PACKAGE_NAME = "_foscam_under_test"


def _ensure_package() -> None:
    if PACKAGE_NAME in sys.modules:
        return
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules[PACKAGE_NAME] = package


def load(module_name: str):
    """Cargar un módulo suelto de la integración."""
    _ensure_package()
    full_name = f"{PACKAGE_NAME}.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, PACKAGE_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    """Respuesta HTTP mínima con la interfaz que usa el cliente."""

    def __init__(self, body: bytes, content_type: str = "text/xml") -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args) -> None:
        return None


class FakeSession:
    """Sesión que devuelve respuestas preprogramadas y registra las URLs."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[str] = []
        self.default = "<CGI_Result><result>0</result></CGI_Result>"

    def get(self, url, **kwargs):
        text = str(url)
        self.requests.append(text)
        cmd = ""
        for part in text.split("?", 1)[-1].split("&"):
            if part.startswith("cmd="):
                cmd = part[4:]
        body = self.responses.get(cmd, self.default)
        content_type = "image/jpeg" if isinstance(body, bytes) else "text/xml"
        payload = body if isinstance(body, bytes) else body.encode()
        return FakeResponse(payload, content_type)


@pytest.fixture
def api():
    """Módulo api ya cargado."""
    return load("api")
