"""Comprobaciones de las traducciones que hassfest hace en CI.

Existen porque hassfest sólo corre en GitHub y necesita Docker, así que un
`strings.json` invalido se descubria despues de empujar. Estas reglas son las
suyas, replicadas para que fallen antes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "custom_components" / "foscam_c1"

ARCHIVOS = [
    PACKAGE / "strings.json",
    PACKAGE / "translations" / "en.json",
    PACKAGE / "translations" / "es.json",
]

#: La regla exacta de hassfest para una clave de traduccion.
CLAVE_VALIDA = re.compile(r"^[a-z0-9-_]+$")

#: Secciones cuyas claves nombran cosas del usuario, no identificadores, y que
#: por tanto no siguen esa regla (los textos, los titulos, los placeholders).
VALORES_NO_CLAVES = {"data", "data_description", "title", "description", "name", "message"}


def _cargar(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


@pytest.mark.parametrize("path", ARCHIVOS, ids=lambda p: p.name)
def test_json_es_valido(path):
    assert isinstance(_cargar(path), dict)


@pytest.mark.parametrize("path", ARCHIVOS, ids=lambda p: p.name)
def test_selector_option_keys_are_lowercase(path):
    # El fallo real: las opciones eran "Main"/"Sub" y hassfest las rechazo por
    # empezar en mayuscula. Son claves de traduccion, no etiquetas.
    for nombre, selector in _cargar(path).get("selector", {}).items():
        for clave in selector.get("options", {}):
            assert CLAVE_VALIDA.match(clave), (
                f"{path.name}: la opcion '{clave}' del selector '{nombre}' no casa "
                f"con [a-z0-9-_]+, hassfest la rechazara"
            )


@pytest.mark.parametrize("path", ARCHIVOS, ids=lambda p: p.name)
def test_entity_and_state_keys_are_lowercase(path):
    datos = _cargar(path)
    for plataforma, entidades in datos.get("entity", {}).items():
        assert CLAVE_VALIDA.match(plataforma), f"{path.name}: plataforma '{plataforma}'"
        for clave, entidad in entidades.items():
            assert CLAVE_VALIDA.match(clave), f"{path.name}: entidad '{clave}'"
            for estado in entidad.get("state", {}):
                assert CLAVE_VALIDA.match(estado), (
                    f"{path.name}: el estado '{estado}' de '{clave}' no casa con [a-z0-9-_]+"
                )


def test_the_three_files_have_the_same_structure():
    # CLAUDE.md pide que cada clave nueva este en los tres. Un olvido aqui deja
    # la interfaz en ingles sin que nada falle.
    def rutas(d, pre=""):
        out = set()
        for k, v in d.items():
            out.add(pre + k)
            if isinstance(v, dict) and k not in VALORES_NO_CLAVES:
                out |= rutas(v, pre + k + ".")
        return out

    referencia = rutas(_cargar(ARCHIVOS[0]))
    for path in ARCHIVOS[1:]:
        actual = rutas(_cargar(path))
        assert actual == referencia, (
            f"{path.name} difiere de strings.json: "
            f"faltan {sorted(referencia - actual)}, sobran {sorted(actual - referencia)}"
        )


def _cargar_const():
    """Cargar const.py suelto: no depende de Home Assistant, asi que se puede."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_const_bajo_prueba", PACKAGE / "const.py")
    const = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(const)
    return const


def test_stream_options_match_the_constants():
    # Si alguien cambia STREAMS y no las traducciones, el desplegable sale con
    # la clave cruda en vez del texto.
    const = _cargar_const()

    for path in ARCHIVOS:
        opciones = set(_cargar(path)["selector"]["stream"]["options"])
        assert opciones == set(const.STREAMS), f"{path.name}: {opciones} != {set(const.STREAMS)}"
    assert set(const.STREAM_PATHS) == set(const.STREAMS)


def test_stale_capitalised_stream_is_normalised():
    # Una entrada creada con 1.1.0 guarda "Main". Sin normalizar, la URL RTSP
    # se queda sin flujo y abrir «Configurar» falla, porque el desplegable no
    # admite un valor por defecto que no este entre los suyos.
    const = _cargar_const()

    assert const.normalize_stream("Main") == "main"
    assert const.normalize_stream("Sub") == "sub"
    assert const.normalize_stream("main") == "main"
    assert const.normalize_stream("loquesea") == const.DEFAULT_STREAM
    # Toda clave normalizada tiene ruta: el indexado de api.py no puede fallar.
    for valor in ("Main", "Sub", "main", "sub", "loquesea", None):
        assert const.normalize_stream(valor) in const.STREAM_PATHS
