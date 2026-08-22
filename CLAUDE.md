# Notas para Claude Code

Integración custom de Home Assistant para cámaras Foscam con API `CGIProxy.fcgi`
(probada en una C1, firmware 2.52.2.50). El código vive en
`custom_components/foscam_c1/`.

Antes de tocar nada: `git log --oneline -5` y `git status`. Este repositorio se
ha editado desde varios sitios y el estado en disco manda sobre lo que diga
cualquier resumen, incluido este archivo.

## Reglas de seguridad (lo primero)

El repositorio es **público** y describe una cámara dentro de una casa. Nunca,
bajo ningún concepto, deben aparecer en un archivo versionado:

- la IP de la cámara o cualquier IP privada real,
- el puerto abierto en el router,
- el usuario o la contraseña de la cámara,
- el SSID de la wifi.

Ya pasó una vez: una contraseña real quedó citada dentro de una frase en
`docs/cgi-referencia.md` como ejemplo, y las dos capas que había entonces
—gitleaks y los patrones de `tools/check_no_secrets.py`— la dejaron pasar
porque ambas buscan **patrones** (`usr=`, `pwd=`, IPs) y allí el valor estaba
suelto en prosa. Por eso existe `.secret-values`: la tercera capa, que compara
literalmente y es la única que cubre ese caso.

`.secret-values` es local y está en `.gitignore`, así que hay que crearlo a
mano (`cp .secret-values.example .secret-values`, un valor por línea) y
**volver a rellenarlo cada vez que se roten las credenciales**. Si falta o está
vacío, `check_no_secrets.py` sigue saliendo con 0 y sólo avisa por stderr: el
hueco queda abierto sin que nada falle.

En documentación y tests usa siempre: `192.0.2.10` (RFC 5737, reservado para
ejemplos), puerto `443`, usuario `camera_user`, y contraseñas inventadas.

Nunca escribas un valor real "solo como ejemplo ilustrativo". Nunca.

## Verificar los cambios

```bash
ruff check . && ruff format --check .
pytest -q                      # 18 pruebas, no necesitan Home Assistant
python tools/check_no_secrets.py
gitleaks detect --config .gitleaks.toml --redact    # si lo tienes instalado
```

Las pruebas cargan `api.py` de forma aislada (ver `tests/conftest.py`), así que
corren sin tener `homeassistant` instalado. Si quieres además comprobar que los
módulos importan de verdad contra HA, instala `homeassistant` en un venv y haz
`import custom_components.foscam_c1` y sus submódulos.

## Rarezas del protocolo CGI (esto es lo que no se ve leyendo el código)

**1. Las credenciales van literales, no codificadas.** Muchos firmwares no
descodifican el `%XX` de `usr` y `pwd`. Una contraseña con `^` enviada como
`%5E` llega como *otra contraseña* y la cámara rechaza el acceso, mientras que
la misma URL pegada en el navegador funciona. El cliente escribe las
credenciales en modo `literal` (escapa sólo `& = + # % " < > \` y el espacio) y
sólo prueba la codificación porcentual completa si hay rechazo. El modo que
funciona se memoriza: sondear en cada petición dispararía el bloqueo por
intentos fallidos.

*Limitación sin arreglo*: si la contraseña lleva cualquiera de los caracteres
que sí se escapan (`& = + # % " < > \` o un espacio) o algo fuera del
ASCII imprimible (una `ñ`, una tilde), y el firmware no descodifica, no hay
forma de enviarla. Hay que cambiarla. El resto del ASCII imprimible
—`^ * ! $ @ ~` y demás— viaja tal cual y es seguro.

**2. Escribir la configuración es destructivo.** `setMotionDetectConfig` y
`setAudioAlarmConfig` devuelven a su valor por defecto todo parámetro que no
envíes. Nunca escribas campos sueltos: usa
`FoscamClient.async_update_alarm_config(alarma, **cambios)`, que relee, aplica
encima y reenvía el conjunto completo. Es la razón de ser de esta integración.

**3. El XML no siempre es válido.** Un SSID con un `&` sin escapar rompe
cualquier parser estricto. `_parse_response` cae a extracción por regex en vez
de dejar las entidades indisponibles.

**4. Los códigos de `result` son ambiguos.** `-1`, `-4`, `-7` y `-8` significan
en la práctica «este firmware no implementa el comando»; así se descubren las
capacidades. `-2` es «usuario o contraseña» y `-3` es «privilegios
insuficientes» — son problemas distintos para el usuario y no deben mezclarse.
Algunas cámaras usan `-3` o un 401 de HTTP donde otras usan `-2`.

**5. Las cámaras bloquean la cuenta** tras varios intentos fallidos seguidos.
Cualquier lógica de reintento tiene que ser tacaña.

**6. Las escalas de sensibilidad no son de fiar.** Foscam documenta 0-4 para el
comando antiguo, pero esta C1 devuelve 6. El `native_max_value` de los `number`
se amplía dinámicamente para no dejar un valor fuera de rango.

## Arquitectura

- `api.py` — cliente asíncrono. No guarda estado de la cámara, sólo sabe hablar
  el protocolo. Las credenciales nunca se escriben en el log.
- `coordinator.py` — un solo `DataUpdateCoordinator` con sondeo **escalonado**:
  `getDevState` en cada ciclo (5 s), la configuración cada 60 s, la información
  del dispositivo cada 15 min. Al escribir se invalida y se refresca al vuelo.
- `entity.py` — base con `_attr_has_entity_name`, device info y `unique_id`.
- Plataformas — todas siguen el mismo patrón: una `EntityDescription` extendida
  con `value_fn` / `set_fn`, y una tabla de descripciones. Para añadir una
  entidad, añade una fila a la tabla y su traducción; no hagas subclases.
- **Capacidades**: `CAPABILITY_PROBES` en `coordinator.py` sondea comandos
  opcionales al arrancar. Las entidades con `capability="..."` sólo se crean si
  la cámara respondió. Así el mismo código sirve para modelos con y sin sirena,
  IR o alarma de sonido.
- Movimiento y sonido comparten implementación (`ALARM_COMMANDS` en `const.py`).
  La variante de firmware se detecta **por separado** para cada alarma.

## Convenciones

- Docstrings y comentarios en español; nombres de código en inglés.
- Ruff con `line-length = 100` y `D401` desactivado (el chequeo de modo
  imperativo es para inglés).
- Cada entidad nueva necesita su `translation_key` en **tres** archivos:
  `strings.json`, `translations/en.json` y `translations/es.json`. Los sensores
  de enumeración necesitan además todos sus `state`.
- Los mensajes de commit explican **por qué**, no qué archivos cambiaron.

## Estado y pendientes

- Publicado en https://github.com/miguelsg29/foscam-c1-homeassistant
- CI: hassfest, HACS, ruff, pytest y escaneo de secretos. HACS falla mientras el
  repositorio no tenga *topics* (se ponen en la web, no en el código).
- El vídeo queda fuera de alcance: se usa la integración oficial de Foscam o
  `generic_camera`.
- `_to_delete/` son restos de la instalación; se puede borrar.
