"""Pruebas del detector de datos reales.

El caso que fija esta suite es el que se escapó de verdad: un secreto citado
en su forma percent-encoded, que la comparación literal no veía.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    name = "_check_no_secrets_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "check_no_secrets.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker():
    return _load()


def test_percent_encoding_is_undone(checker):
    # `%5E` con el `*` intacto es lo que produce yarl, no `quote`: por eso se
    # descodifica la línea en vez de enumerar formas del secreto.
    vistas = checker._views("viajaba como Xy%5EQm*Vb3Nz8")
    assert any("Xy^Qm*Vb3Nz8" in v for v in vistas)
    assert vistas["viajaba como Xy%5EQm*Vb3Nz8"] == "literal"


def test_lowercase_percent_is_undone(checker):
    assert any("Xy^Qm*Vb3Nz8" in v for v in checker._views("Xy%5eQm*Vb3Nz8"))


def test_markup_escaping_is_undone(checker):
    vistas = checker._views("&lt;SSID&gt;casa&amp;red&lt;/SSID&gt;")
    assert any("casa&red" in v for v in vistas)


def test_literal_line_is_always_the_first_view(checker):
    # Si el valor está tal cual, el hallazgo debe decir "literal" y no una
    # etiqueta de codificación que despiste sobre dónde mirar.
    vistas = checker._views("camerauser")
    assert next(iter(vistas.items())) == ("camerauser", "literal")


def test_encoded_secret_in_a_file_is_caught(checker, tmp_path, monkeypatch, capsys):
    denylist = tmp_path / ".secret-values"
    denylist.write_text("# comentario\nXy^Qm*Vb3Nz8\n", encoding="utf-8")
    monkeypatch.setattr(checker, "DENYLIST_FILE", denylist)

    sospechoso = tmp_path / "mensaje.txt"
    sospechoso.write_text("la contraseña viajaba como Xy%5EQm*Vb3Nz8\n", encoding="utf-8")

    assert checker.main([str(sospechoso)]) == 1
    err = capsys.readouterr().err
    assert "valor-prohibido" in err
    assert "percent-encoded" in err
    # El detector no puede filtrar aquello de lo que avisa.
    assert "Xy^Qm*Vb3Nz8" not in err
    assert "Xy%5EQm*Vb3Nz8" not in err


def test_clean_file_passes(checker, tmp_path, monkeypatch):
    denylist = tmp_path / ".secret-values"
    denylist.write_text("Xy^Qm*Vb3Nz8\n", encoding="utf-8")
    monkeypatch.setattr(checker, "DENYLIST_FILE", denylist)

    limpio = tmp_path / "limpio.md"
    limpio.write_text("host 192.0.2.10, puerto 443, usuario camera_user\n", encoding="utf-8")

    assert checker.main([str(limpio)]) == 0
