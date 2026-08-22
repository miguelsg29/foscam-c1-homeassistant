# Vídeo: cómo ver la cámara

La integración trae su propia entidad `camera.*`: foto fija por CGI y vídeo en
directo por RTSP. No hace falta nada más.

## 1. La cámara de esta integración (lo normal)

Sale sola al configurar. Al añadir la cámara se piden dos cosas:

* **Flujo de vídeo** — `Principal` se ve mejor, `Secundario` aguanta mejor una
  red pobre. Se puede cambiar luego en *Configurar*.
* **Puerto RTSP** — los modelos nuevos admiten 88 y 554; los antiguos, 88 y
  65534. Por defecto 88, que es el común a todos.

Si tu cámara tiene el RTSP desactivado, pon el puerto a **0**: la foto fija
sigue funcionando y el directo simplemente no se ofrece, en vez de aparecer un
botón que acabaría en error.

Un detalle del que no te tienes que ocupar, pero que explica un fallo raro: la
contraseña viaja **percent-encoded** en la URL RTSP y **literal** en el CGI.
Son codificaciones opuestas para la misma contraseña, porque el firmware no
descodifica y ffmpeg sí. La integración lo hace bien en cada sitio.

## 2. La integración oficial de Foscam

Ya no hace falta, pero conviven sin conflicto si la prefieres. Aporta `camera`,
`switch` y `number`; todo lo demás (los sensores, los binarios, los botones)
sólo está aquí.

Aparecerá como un dispositivo distinto. Si te molesta tener dos tarjetas,
desactiva desde la página del dispositivo las entidades que se solapen.

## 3. RTSP con `generic_camera`

Útil si quieres una segunda entidad con otros ajustes, o para depurar la URL a
mano cuando el directo no arranca.
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

## 4. Sólo fotos

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
