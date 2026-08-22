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


def _con_denylist(checker, tmp_path, monkeypatch, valor="Xy^Qm*Vb3Nz8"):
    denylist = tmp_path / ".secret-values"
    denylist.write_text(valor + "\n", encoding="utf-8")
    monkeypatch.setattr(checker, "DENYLIST_FILE", denylist)
    # Aislar tambien .env: sin esto las pruebas leerian el del repositorio.
    monkeypatch.setattr(checker, "ENV_FILE", tmp_path / ".env")
    return denylist


def _con_env(checker, tmp_path, monkeypatch, contenido):
    env = tmp_path / ".env"
    env.write_text(contenido, encoding="utf-8")
    monkeypatch.setattr(checker, "ENV_FILE", env)
    monkeypatch.setattr(checker, "DENYLIST_FILE", tmp_path / ".secret-values")
    return env


def test_commit_message_with_secret_is_rejected(checker, tmp_path, monkeypatch, capsys):
    # El caso real: la fuga estaba en el mensaje, no en ningun archivo.
    _con_denylist(checker, tmp_path, monkeypatch)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("La causa: `Xy^Qm*Vb3Nz8` viajaba mal.\n", encoding="utf-8")

    assert checker.main(["--commit-msg", str(msg)]) == 1
    err = capsys.readouterr().err
    assert "mensaje de commit" in err
    assert "Xy^Qm*Vb3Nz8" not in err


def test_commit_message_with_encoded_secret_is_rejected(checker, tmp_path, monkeypatch, capsys):
    _con_denylist(checker, tmp_path, monkeypatch)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("viajaba como `Xy%5EQm*Vb3Nz8`, y la camara lo compara.\n", encoding="utf-8")

    assert checker.main(["--commit-msg", str(msg)]) == 1
    err = capsys.readouterr().err
    assert "percent-encoded" in err
    assert "Xy%5EQm*Vb3Nz8" not in err


def test_clean_commit_message_passes(checker, tmp_path, monkeypatch):
    _con_denylist(checker, tmp_path, monkeypatch)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("Usa `Aq^Ub*Kx2Zt7` como contrasena de ejemplo.\n", encoding="utf-8")

    assert checker.main(["--commit-msg", str(msg)]) == 0


def test_comment_lines_are_ignored(checker, tmp_path, monkeypatch):
    # Git quita las lineas que empiezan por #, asi que no llegan al mensaje.
    _con_denylist(checker, tmp_path, monkeypatch)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("Titulo normal\n# rama con Xy^Qm*Vb3Nz8 dentro\n", encoding="utf-8")

    assert checker.main(["--commit-msg", str(msg)]) == 0


def test_verbose_diff_below_the_scissors_is_ignored(checker, tmp_path, monkeypatch):
    # Con commit.verbose el diff va debajo de las tijeras y no es el mensaje;
    # de ese contenido ya se encarga el escaneo de archivos.
    _con_denylist(checker, tmp_path, monkeypatch)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Titulo normal\n"
        "# ------------------------ >8 ------------------------\n"
        "+contrasena = Xy^Qm*Vb3Nz8\n",
        encoding="utf-8",
    )

    assert checker.main(["--commit-msg", str(msg)]) == 0


def test_commit_msg_without_a_file_is_a_usage_error(checker):
    assert checker.main(["--commit-msg"]) == 2


def test_env_password_becomes_a_denied_value(checker, tmp_path, monkeypatch):
    _con_env(checker, tmp_path, monkeypatch, "FOSCAM_PASSWORD=Xy^Qm*Vb3Nz8\n")
    assert checker.all_denied_values() == ["Xy^Qm*Vb3Nz8"]


def test_env_secret_is_caught_in_a_file(checker, tmp_path, monkeypatch, capsys):
    # Rotar en .env basta: no hay que acordarse de tocar .secret-values.
    _con_env(checker, tmp_path, monkeypatch, "FOSCAM_PASSWORD=Xy^Qm*Vb3Nz8\n")
    doc = tmp_path / "doc.md"
    doc.write_text("la contrasena es Xy^Qm*Vb3Nz8 por ejemplo\n", encoding="utf-8")

    assert checker.main([str(doc)]) == 1
    assert "Xy^Qm*Vb3Nz8" not in capsys.readouterr().err


def test_host_and_port_are_not_denied(checker, tmp_path, monkeypatch):
    # Ya los cubren los patrones, y un 443 literal marcaria media documentacion.
    # El host aqui es largo y no es un marcador: si queda fuera, es por la clave.
    _con_env(
        checker,
        tmp_path,
        monkeypatch,
        "FOSCAM_HOST=camara.example.net\nFOSCAM_PORT=44344\nFOSCAM_PASSWORD=Xy^Qm*Vb3Nz8\n",
    )
    assert checker.all_denied_values() == ["Xy^Qm*Vb3Nz8"]


def test_untouched_example_env_adds_nothing(checker, tmp_path, monkeypatch):
    # Un .env recien copiado de .env.example no contiene ningun secreto.
    _con_env(
        checker,
        tmp_path,
        monkeypatch,
        "FOSCAM_HOST=192.0.2.10\nFOSCAM_USER=camera_user\nFOSCAM_PASSWORD=\n",
    )
    assert checker.all_denied_values() == []


def test_short_value_is_skipped_but_announced(checker, tmp_path, monkeypatch, capsys):
    # Un hueco silencioso es justo el fallo que hay que evitar.
    _con_env(checker, tmp_path, monkeypatch, "FOSCAM_SSID=casa\n")
    assert checker.all_denied_values() == []
    assert "FOSCAM_SSID" in capsys.readouterr().err


def test_quotes_and_comments_are_handled(checker, tmp_path, monkeypatch):
    _con_env(
        checker,
        tmp_path,
        monkeypatch,
        '# un comentario\nFOSCAM_PASSWORD="Xy^Qm*Vb3Nz8"\nSIN_IGUAL\n',
    )
    assert checker.all_denied_values() == ["Xy^Qm*Vb3Nz8"]


def test_env_and_secret_values_are_merged_without_repeats(checker, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("FOSCAM_PASSWORD=Xy^Qm*Vb3Nz8\n", encoding="utf-8")
    denylist = tmp_path / ".secret-values"
    denylist.write_text("Xy^Qm*Vb3Nz8\nMiWifi_De_Casa\n", encoding="utf-8")
    monkeypatch.setattr(checker, "ENV_FILE", env)
    monkeypatch.setattr(checker, "DENYLIST_FILE", denylist)

    assert checker.all_denied_values() == ["Xy^Qm*Vb3Nz8", "MiWifi_De_Casa"]


def test_env_secret_is_caught_in_a_commit_message(checker, tmp_path, monkeypatch, capsys):
    _con_env(checker, tmp_path, monkeypatch, "FOSCAM_PASSWORD=Xy^Qm*Vb3Nz8\n")
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fallaba con Xy%5EQm*Vb3Nz8 en la URL\n", encoding="utf-8")

    assert checker.main(["--commit-msg", str(msg)]) == 1
    assert "percent-encoded" in capsys.readouterr().err


def test_value_containing_a_placeholder_word_is_not_skipped(checker, tmp_path, monkeypatch):
    # PLACEHOLDERS lleva la palabra generica "usuario". Si se usara esa regex
    # para filtrar .env, un usuario real que la contenga -plausible en espanol-
    # quedaria fuera del denylist sin avisar. Por eso se compara de forma
    # exacta contra los valores de .env.example.
    _con_env(checker, tmp_path, monkeypatch, "FOSCAM_USER=usuario_real_de_la_camara\n")
    assert checker.all_denied_values() == ["usuario_real_de_la_camara"]


def test_example_placeholders_are_matched_exactly(checker, tmp_path, monkeypatch):
    # `camera_user` es el marcador literal de .env.example y se ignora;
    # `camera_user_de_verdad` no lo es, y si entra.
    _con_env(
        checker,
        tmp_path,
        monkeypatch,
        "FOSCAM_USER=camera_user\nFOSCAM_SSID=camera_user_de_verdad\n",
    )
    assert checker.all_denied_values() == ["camera_user_de_verdad"]
