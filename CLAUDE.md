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
suelto en prosa. Por eso existe la tercera capa, la que compara literalmente
contra tus valores reales, y que es la única que cubre ese caso.

Los valores con los que compara salen de **`.env`** (local, ignorado por git),
que es donde ya están las credenciales para `probe_camera.py`. Se rota ahí y el
detector se entera solo: mantener una lista aparte a mano fue lo que falló —el
archivo quedó vacío mientras la fuga llevaba dos commits publicada—. Si `.env`
falta o sigue igual que `.env.example`, `check_no_secrets.py` sale con 0 y sólo
avisa por stderr: el hueco queda abierto sin que nada falle.

De `.env` **no** entran la IP ni el puerto (ya los cazan los patrones, y un
`443` comparado literalmente marcaría media documentación), ni los valores de
menos de 6 caracteres, que darían falsos positivos por todas partes — de estos
sí avisa, para no dejar un hueco callado. El descarte de marcadores compara de
forma **exacta** contra `.env.example`: la regex `PLACEHOLDERS` lleva palabras
genéricas como `usuario` y descartaría un usuario real que la contenga.

Vale cualquier clave de `.env`, no sólo las del ejemplo: si quieres proteger la
contraseña anterior tras rotar, la de otra cámara o la del router, añade su
línea. Hubo un `.secret-values` aparte para eso y se retiró: dos listas que
mantener a mano es una lista que se olvida, y la que se olvidó estaba vacía
mientras la fuga llevaba dos commits publicada.

Nada de esto corre solo. Hay que instalar los hooks una vez por clon:

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Sin eso la única red es CI, y CI salta **después** del push, cuando el secreto
ya es público. Peor aún: en CI no existe `.env` —es local por
diseño—, así que allí `check_no_secrets.py` sólo corre los patrones y la capa
de valores literales **no existe**. Es decir: la comparación contra tus valores
reales sólo puede ocurrir en tu máquina. Si no instalas los hooks, esa capa no
se ejecuta en ningún sitio. El `--hook-type commit-msg` no es opcional.

**El mensaje de commit es un canal aparte.** El escaneo de archivos sólo ve
`git ls-files` y gitleaks sólo ve los parches; un mensaje no es ninguna de las
dos cosas. La fuga que motivó todo esto estaba justo ahí y sobrevivió a la
limpieza de los archivos. Lo cubre `check_no_secrets.py --commit-msg`, que
corre en la etapa `commit-msg`. Importa más que las otras capas porque un
mensaje ya empujado no se corrige sin reescribir el historial y un
`push --force`.

En documentación y tests usa siempre: `192.0.2.10` (RFC 5737, reservado para
ejemplos), puerto `443`, usuario `camera_user`, y contraseñas inventadas.

Nunca escribas un valor real "solo como ejemplo ilustrativo". Nunca.

## Verificar los cambios

```bash
ruff check . && ruff format --check .
pytest -q                      # 44 pruebas, no necesitan Home Assistant
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

**1 bis. El RTSP se codifica justo al revés.** La misma contraseña se escribe
de dos formas según por dónde salga: literal en el CGI, porque el firmware no
descodifica; y percent-encoded en la URL RTSP, porque ahí el consumidor es
ffmpeg, que sí descodifica y espera la userinfo según la RFC 3986. Confundirlas
da un rechazo de credenciales que parece una contraseña mal escrita. Lo
construye `FoscamClient.rtsp_url()`, y esa URL lleva la contraseña dentro: no
se registra en el log ni se expone como atributo.

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

**6. La sensibilidad del comando antiguo es un enum disfrazado de número.**
Foscam documenta 0-4, y `SENSITIVITY_LABELS_LEGACY` en `const.py` recoge lo que
significa cada valor: `0=low, 1=normal, 2=high, 3=lower, 4=lowest`. El orden no
es el que parece — si esa tabla es correcta, el valor más sensible es el **2** y
el 4 es el menos sensible, justo lo contrario de lo que sugiere un deslizador
0-4. La variante moderna sí usa una escala lineal 0-100.

Una versión anterior de esta nota afirmaba que esta C1 devuelve 6 y en eso se
apoyaba el ensanchado dinámico del `native_max_value`. **La app del fabricante
llega a 4**, comprobado por el usuario en agosto de 2026, así que el 6 no está
confirmado y no debe repetirse como un hecho. El ensanchado se queda, pero como
red por si algún modelo devuelve un valor fuera de rango: evita dejar la entidad
en estado inválido, y se repliega solo al rango documentado en cuanto la cámara
vuelve a informar algo dentro de él.

## Arquitectura

- `api.py` — cliente asíncrono. No guarda estado de la cámara, sólo sabe hablar
  el protocolo. Las credenciales nunca se escriben en el log.
- `coordinator.py` — un solo `DataUpdateCoordinator` con sondeo **escalonado**:
  `getDevState` en cada ciclo (5 s), la configuración cada 60 s, la información
  del dispositivo cada 15 min. Al escribir se invalida y se refresca al vuelo.
- `entity.py` — base con `_attr_has_entity_name`, device info y `unique_id`.
- `camera.py` — la excepción al patrón de tablas: una sola entidad, sin
  `value_fn`. `_attr_name = None` para que tome el nombre del dispositivo, y
  `CameraEntityFeature.STREAM` sólo si hay puerto RTSP configurado: con el
  puerto a 0 quedan las fotos fijas y no se ofrece un directo que fallaría.
- Plataformas — las demás siguen el mismo patrón: una `EntityDescription` extendida
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
- El vídeo **ya está dentro**: la plataforma `camera` da la foto fija por CGI y
  el directo por RTSP. Estuvo fuera de alcance hasta que se comprobó que la
  oficial sólo aporta `camera`, `switch` y `number`: mantenerla en paralelo
  costaba más que las ~70 líneas de `camera.py`.
- `_to_delete/` son restos de la instalación; se puede borrar.
