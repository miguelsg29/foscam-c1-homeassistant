# Foscam C1 (CGI) para Home Assistant

Integración personalizada para cámaras Foscam que hablan la API `CGIProxy.fcgi`
(C1, C2, R2, FI9xxx HD y compatibles). Sustituye el clásico apaño de
`command_line` + `curl` + `shell_command` por una integración nativa con
config flow, coordinador de actualizaciones y entidades de verdad.

> **English:** a Home Assistant custom integration for Foscam HD IP cameras
> using the `CGIProxy.fcgi` API. Config flow, motion detection switch and
> binary sensor, sensitivity/linkage controls, SD-card and Wi-Fi diagnostics,
> and a generic CGI service. Docs are in Spanish.

---

## Por qué

El montaje habitual con `command_line` funciona, pero arrastra cuatro problemas
que esta integración resuelve:

| Problema del montaje con `curl` | Qué hace esta integración |
| --- | --- |
| `setMotionDetectConfig` es **destructivo**: los parámetros que no envías vuelven a su valor por defecto. Por eso hay que repetir `schedule0..6`, `area0..9`, `sensitivity`… en cada llamada. | Lee la configuración actual, aplica encima **sólo** el campo que cambia y la reenvía entera. Cambiar la sensibilidad no te borra los horarios. |
| La contraseña viaja en la línea de comandos, visible en la lista de procesos y en los logs de Home Assistant. | Las credenciales se guardan cifradas en el registro de config entries y nunca se escriben en el log. |
| Un `sensor` de texto (`Activada` / `Detectado`) no sirve para automatizaciones limpias ni para el historial. | `binary_sensor` con `device_class: motion`, más un sensor de enumeración con estados traducidos. |
| Un `scan_interval` de 3 s lanza un proceso `curl` nuevo cada 3 segundos. | Un único coordinador asíncrono con sondeo escalonado: el estado en vivo cada 5 s, la configuración cada minuto, la información del dispositivo cada 15 minutos. |

## Entidades

| Plataforma | Entidad | Notas |
| --- | --- | --- |
| `switch` | Detección de movimiento | Lee el estado en vivo de `getDevState`, así que responde en segundos |
| `switch` | LED infrarrojo | Sólo si el modelo responde a `getInfraLedConfig` |
| `switch` | Sirena | Sólo en modelos con sirena (la C1 no la tiene) |
| `switch` | Al detectar: zumbador / email / foto / grabar | Los cuatro bits del campo `linkage` |
| `binary_sensor` | Movimiento, Sonido, Grabando, Wifi, Entrada de alarma, Problema con la SD | |
| `sensor` | Estado de la detección, Tarjeta SD, Espacio libre/total/ocupado, Red conectada, Modo del infrarrojo, Firmware, NTP, DDNS, UPnP | |
| `number` | Sensibilidad, Intervalo de disparo, Intervalo entre fotos | La escala de sensibilidad se ajusta sola al firmware (0-4 ó 0-100) |
| `button` | Reiniciar cámara, Detectar todo el día en toda la imagen | |

Las entidades de diagnóstico y las más ruidosas vienen **desactivadas por
defecto**: actívalas desde la página del dispositivo si las quieres.

## Instalación

### HACS

1. HACS → Integraciones → menú ⋮ → *Repositorios personalizados*.
2. Añade la URL de este repositorio con la categoría **Integration**.
3. Instala «Foscam C1 (CGI)» y reinicia Home Assistant.

### Manual

Copia `custom_components/foscam_c1/` dentro de la carpeta `custom_components/`
de tu configuración y reinicia.

## Configuración

*Ajustes → Dispositivos y servicios → Añadir integración → Foscam C1 (CGI)*.

| Campo | Qué poner |
| --- | --- |
| Dirección o IP | La IP fija de la cámara en tu red |
| Puerto | El puerto de la **API CGI**, no el del panel web. Suelen ser distintos |
| Usuario / Contraseña | Una cuenta con privilegios de **administrador** |
| Usar HTTPS | Actívalo si la cámara sirve la API por TLS |
| Verificar el certificado TLS | Déjalo desactivado: las Foscam traen un certificado autofirmado |

En *Configurar* (opciones) puedes ajustar los intervalos de sondeo y añadir la
URL del panel web, que aparecerá como el enlace «Visitar» del dispositivo.

> **Consejo:** crea en la cámara una cuenta dedicada para Home Assistant en vez
> de reutilizar la tuya. Si algún día tienes que rotar la contraseña, no pierdes
> el acceso desde la app.

## Servicios

### `foscam_c1.cgi_command`

Escotilla de escape: ejecuta cualquier comando de la API CGI y te devuelve la
respuesta ya parseada. Útil para explorar lo que expone tu modelo concreto.

```yaml
action: foscam_c1.cgi_command
data:
  device_id: "{{ device_id('switch.foscam_deteccion_de_movimiento') }}"
  command: getDevState
response_variable: estado
```

Hay una lista corta de comandos bloqueados (reset de fábrica, gestión de
usuarios, cambio de red y actualizaciones de firmware) para que una
automatización mal escrita no te deje la cámara inservible.

### `foscam_c1.set_motion_config`

Cambia campos sueltos de la detección de movimiento sin tocar el resto:

```yaml
action: foscam_c1.set_motion_config
data:
  device_id: "{{ device_id('switch.foscam_deteccion_de_movimiento') }}"
  params:
    sensitivity: "1"
    triggerInterval: "15"
```

### `foscam_c1.snapshot`

```yaml
action: foscam_c1.snapshot
data:
  device_id: "{{ device_id('switch.foscam_deteccion_de_movimiento') }}"
  filename: /config/www/foscam/dormitorio.jpg
```

La ruta debe estar dentro de `allowlist_external_dirs`.

## Vídeo

Esta integración **no** sirve el stream: para eso usa la integración oficial de
Foscam o una entrada `generic_camera` con el RTSP de la cámara. Ambas conviven
sin problema con ésta. Ver [docs/video.md](docs/video.md).

## Migrar desde `command_line`

En [docs/migracion.md](docs/migracion.md) tienes el mapeo entidad a entidad, qué
borrar de `command_line.yaml`, `switch.yaml` y `scripts.yaml`, y cómo quedan las
automatizaciones.

## Seguridad del repositorio

Este repositorio es público y describe una cámara que está dentro de una casa.
Lo que **nunca** debe llegar a un commit: la IP de la cámara, el puerto abierto
en el router, el usuario y la contraseña.

Tres capas lo impiden:

1. **`.gitignore`** — ignora `secrets.yaml`, `.env`, salidas de la sonda
   (`probe-*.json`) y la carpeta `manual/`.
2. **`tools/check_no_secrets.py`** — falla si encuentra una IP privada, un
   `usr=`/`pwd=` con valor real o un puerto no estándar en una URL.
3. **gitleaks** — con reglas propias en `.gitleaks.toml`, tanto en `pre-commit`
   como en CI.

Actívalas en local con:

```bash
pip install pre-commit
pre-commit install
```

En la documentación se usan siempre marcadores: `192.0.2.10` (rango reservado
por la RFC 5737 para ejemplos), el puerto `443` y `!secret foscam_password`.

## Explorar tu cámara

`tools/probe_camera.py` recorre una treintena de comandos de sólo lectura y
apunta cuáles soporta tu modelo y qué campos devuelven. Enmascara la MAC, el
número de serie, el SSID y las IPs, así que el informe se puede pegar en un
issue:

```bash
python tools/probe_camera.py --host 192.0.2.10 --port 443 --user camera_user
```

La contraseña se pide por teclado para que no quede en el historial de la shell.

## Desarrollo

```bash
pip install -r requirements-test.txt
pytest                       # pruebas del protocolo CGI, sin necesidad de HA
ruff check . && ruff format --check .
python tools/check_no_secrets.py
```

Las pruebas cargan `api.py` de forma aislada, así que corren sin tener Home
Assistant instalado.

## Referencia CGI

[docs/cgi-referencia.md](docs/cgi-referencia.md) resume los comandos que usa la
integración, los códigos de `result` y el significado de `linkage`, `schedule`
y `area`.

## Licencia

MIT. Foscam es una marca de Shenzhen Foscam Intelligent Technology; este
proyecto no está afiliado ni respaldado por ellos.
