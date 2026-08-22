#!/usr/bin/env python3
"""Red de seguridad: falla si algo del repositorio parece un dato real.

Gitleaks ya cubre lo genérico; esto cubre lo específico de una integración
doméstica, que es justo lo que se suele colar sin querer: la IP de la cámara,
el puerto que abriste en el router, el usuario de la cámara o su contraseña
dentro de una URL de ejemplo.

Uso:
    python tools/check_no_secrets.py          # revisa los archivos versionados
    python tools/check_no_secrets.py ruta ... # revisa rutas concretas
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent

#: Archivos que contienen los patrones a propósito (son los detectores).
SELF_EXCLUDE = {
    "tools/check_no_secrets.py",
    ".gitleaks.toml",
    ".github/workflows/secret-scan.yml",
}

#: Archivo local, ignorado por git, con un valor literal por línea que nunca
#: debe aparecer en el repositorio: tu contraseña real, tu usuario de la cámara,
#: tu SSID... Es la única defensa fiable contra un valor real citado en medio
#: de una frase, donde ningún patrón genérico lo reconoce como secreto.
DENYLIST_FILE = ROOT / ".secret-values"


def _views(line: str) -> dict[str, str]:
    """Devolver las lecturas posibles de una línea, empezando por la literal.

    Un secreto no siempre se cita tal cual: dentro de una URL viaja
    percent-encoded y dentro de un XML o un HTML va escapado. Enumerar las
    formas en que puede escribirse no funciona, porque cada codificador elige
    un juego distinto de caracteres seguros: yarl deja `*` intacto y `quote`
    no, así que la misma contraseña tiene dos formas percent-encoded. Se hace
    al revés: se deshacen las codificaciones de la línea y se compara siempre
    contra el valor literal, que es uno solo.

    Pasó de verdad: un mensaje de commit citaba la contraseña y, dos líneas
    más abajo, su forma `%5E`. Sólo se detectó la primera.
    """
    vistas = {line: "literal"}
    vistas.setdefault(unquote(line), "percent-encoded")
    vistas.setdefault(html.unescape(line), "escapado como XML/HTML")
    vistas.setdefault(unquote(html.unescape(line)), "escapado y percent-encoded")
    return vistas


BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".zip",
    ".gz",
    ".ico",
    ".woff",
    ".woff2",
}

#: Valores que sí queremos ver en la documentación.
PLACEHOLDERS = re.compile(
    r"(?i)(YOUR_|TU_|<[^>]+>|\{\{.*?\}\}|\$\{|!secret|xxx+|camera_user|camera_password"
    r"|usuario|contrase|192\.0\.2\.|203\.0\.113\.|192\.168\.x\.x|0\.0\.0\.0)"
)

CHECKS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "ip-privada",
        re.compile(
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
        ),
        "IP privada real. Usa 192.0.2.10 (rango reservado para documentación).",
    ),
    (
        "credencial-cgi",
        re.compile(r"[?&](?:usr|pwd)=([^\s&\"'<>]{2,})"),
        "Usuario o contraseña dentro de una URL CGI.",
    ),
    (
        "puerto-alto",
        re.compile(r"://[^\s\"'<>/]+:(4[0-9]{4}|[5-9][0-9]{4})\b"),
        "Puerto no estándar que parece el de tu router. Usa 88 o 443 en los ejemplos.",
    ),
]


def tracked_files() -> list[Path]:
    """Listar los archivos que git tiene versionados."""
    try:
        output = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [ROOT / line for line in output.splitlines() if line]


def denylisted_values() -> list[str]:
    """Leer los valores literales prohibidos del archivo local, si existe."""
    if not DENYLIST_FILE.is_file():
        return []
    return [
        line.strip()
        for line in DENYLIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main(argv: list[str]) -> int:
    """Ejecutar la comprobación y devolver el código de salida."""
    paths = [Path(a).resolve() for a in argv] if argv else tracked_files()
    findings: list[str] = []
    denylist = denylisted_values()

    if not denylist:
        print(
            "AVISO: no hay .secret-values. Los patrones de abajo cazan IPs, puertos y\n"
            "       URLs con credenciales, pero NO un valor real citado en medio de una\n"
            "       frase. Copia .secret-values.example a .secret-values y pon ahí tu\n"
            "       contraseña, tu usuario y tu SSID reales para cerrar ese hueco.\n",
            file=sys.stderr,
        )

    for path in paths:
        if not path.is_file() or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        if rel in SELF_EXCLUDE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            # Nunca se imprime lo que ha coincidido: es el secreto.
            vistas = _views(line) if denylist else {}
            for value in denylist:
                for etiqueta in (e for v, e in vistas.items() if value in v):
                    findings.append(
                        f"{rel}:{lineno}: [valor-prohibido] Un valor de "
                        f".secret-values aparece en este archivo ({etiqueta})."
                    )
                    break
            for name, pattern, hint in CHECKS:
                match = pattern.search(line)
                if not match:
                    continue
                if PLACEHOLDERS.search(match.group(0)):
                    continue
                findings.append(f"{rel}:{lineno}: [{name}] {hint}\n    {line.strip()[:120]}")

    if findings:
        print("Se han encontrado datos que parecen reales:\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nSustitúyelos por marcadores antes de hacer commit.",
            file=sys.stderr,
        )
        return 1

    extra = f", {len(denylist)} valores prohibidos" if denylist else ""
    print(f"OK: {len(paths)} archivos revisados{extra}, ningún dato real detectado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
