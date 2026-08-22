# Vídeo: cómo ver la cámara

Esta integración se ocupa del control y del estado, no del stream. Para la
imagen tienes tres opciones, y todas conviven con ella sin conflicto.

## 1. La integración oficial de Foscam (lo más sencillo)

*Ajustes → Dispositivos y servicios → Añadir integración → Foscam*. Te da la
entidad `camera.*` con los flujos principal y secundario, y algunos
interruptores propios (infrarrojo, luz de estado, volteo de imagen…).

Aparecerá como un dispositivo distinto al de esta integración. Si te molesta
tener dos tarjetas, desactiva desde la página del dispositivo las entidades que
se solapen: quédate con la cámara de la oficial y con los controles de ésta.

## 2. RTSP con `generic_camera`

Útil si quieres controlar la resolución o si la oficial no reconoce tu modelo.
El flujo principal de las Foscam HD suele estar en:

```
rtsp://<usuario>:<contraseña>@<host>:<puerto_rtsp>/videoMain
rtsp://<usuario>:<contraseña>@<host>:<puerto_rtsp>/videoSub
```

En `configuration.yaml`, con las credenciales fuera del archivo:

```yaml
camera:
  - platform: generic
    name: Foscam dormitorio
    stream_source: !secret foscam_rtsp_url
    verify_ssl: false
```

Y en `secrets.yaml` (que está en `.gitignore` y nunca se sube):

```yaml
foscam_rtsp_url: "rtsp://usuario:contraseña@192.0.2.10:554/videoMain"
```

## 3. Sólo fotos

Si lo que quieres es una imagen al detectar movimiento, no hace falta stream:
el servicio `foscam_c1.snapshot` guarda un JPEG en la ruta que le digas.

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.foscam_dormitorio_movimiento
    to: "on"
actions:
  - action: foscam_c1.snapshot
    data:
      device_id: "{{ device_id('binary_sensor.foscam_dormitorio_movimiento') }}"
      filename: "/config/www/foscam/{{ now().strftime('%Y%m%d-%H%M%S') }}.jpg"
```

Ten en cuenta que todo lo que dejes en `/config/www/` es accesible sin
autenticación desde `/local/`. Para notificaciones al móvil es cómodo; para
grabaciones que quieras conservar, mejor otra carpeta añadida a
`allowlist_external_dirs`.
