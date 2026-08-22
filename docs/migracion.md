# Migrar desde la configuración con `command_line`

Guía para pasar del montaje `command_line` + `curl` + `shell_command` a esta
integración. Hazlo con calma: los pasos 1 y 2 no rompen nada, y hasta el paso 4
puedes convivir con las dos configuraciones a la vez.

---

## 0. Antes de empezar: rota la contraseña de la cámara

Si la contraseña de la cámara ha estado en claro dentro de `command_line.yaml`,
en la línea de comandos de `curl` (visible en la lista de procesos y a veces en
los logs) o pegada en un chat o un issue, **dala por comprometida**. Cámbiala
desde el panel web de la cámara antes de configurar la integración, y aprovecha
para crear una cuenta dedicada a Home Assistant con permisos de administrador
en lugar de reutilizar la tuya.

## 1. Instala la integración y añade la cámara

*Ajustes → Dispositivos y servicios → Añadir integración → Foscam C1 (CGI)*.
Ponle al dispositivo el nombre que quieras que hereden las entidades, por
ejemplo `Foscam dormitorio`.

Comprueba que aparecen y funcionan:

* el interruptor de detección de movimiento,
* el sensor binario de movimiento (muévete delante de la cámara),
* el sensor de estado de la detección.

## 2. Un aviso sobre tus `entity_id` actuales

En la configuración de partida conviven **tres nombres distintos** para lo que
en realidad es un solo interruptor:

| Dónde aparece | `entity_id` |
| --- | --- |
| `scripts.yaml` | `switch.foscam_motion` |
| Automatizaciones «Salir de casa» / «En casa» | `switch.foscam_dormitorio_motion` |
| El que le correspondería al `switch` de `command_line.yaml` por su nombre | `switch.foscam_interruptor_de_activacion` |

El bloque comentado de `switch.yaml` y el activo de `command_line.yaml`
comparten el mismo `unique_id`, así que el registro de entidades **conserva el
`entity_id` que asignó la primera vez** (`switch.foscam_dormitorio_motion`) aunque
el nombre descriptivo haya cambiado. Por eso las automatizaciones siguen
funcionando y los scripts no: `switch.foscam_motion` no existe.

Merece la pena comprobarlo antes de tocar nada, en
*Herramientas para desarrolladores → Estados*, buscando `foscam`. Verás cuáles
de esos tres identificadores existen de verdad.

## 3. Mapeo de entidades

Sustituye `foscam_dormitorio` por el nombre que le hayas dado al dispositivo.

| Antes | Ahora |
| --- | --- |
| `switch.foscam_dormitorio_motion` (o `switch.foscam_interruptor_de_activacion`) | `switch.foscam_dormitorio_deteccion_de_movimiento` |
| `sensor.foscam_dormitorio_detector_de_movimiento` con estados `Desactivada` / `Activada` / `Detectado` | `binary_sensor.foscam_dormitorio_movimiento` para automatizar, y `sensor.foscam_dormitorio_estado_de_la_deteccion` si quieres el texto |
| `script.foscam_on` | `switch.turn_on` sobre el interruptor |
| `script.foscam_off` | `switch.turn_off` sobre el interruptor |
| `shell_command.foscam_turn_on` / `foscam_turn_off` | Ya no hacen falta |
| El `sensitivity=…` dentro de la URL de `curl` | `number.foscam_dormitorio_sensibilidad_de_movimiento` |
| El `linkage=142` dentro de la URL | Los cuatro interruptores «Al detectar: …» |
| Los `schedule0..6` y `area0..9` repetidos en cada URL | El botón «Detectar todo el día, toda la imagen», o simplemente no tocarlos: ya no se pierden |

## 4. Qué borrar

**`command_line.yaml`** — elimina el bloque `# Foscam Motion detector` (el
`switch`) y el bloque `# Estado de la cámara Foscam` (el `sensor`).

**`switch.yaml`** — elimina el bloque comentado de la plataforma
`command_line`. Ya no aporta nada y es el origen de la confusión de nombres.

**`scripts.yaml`** — `foscam_on` y `foscam_off` se pueden borrar enteros. Si
prefieres conservarlos porque los llamas desde otros sitios, quedan así:

```yaml
foscam_off:
  alias: Foscam - Desactivar detección
  sequence:
    - action: switch.turn_off
      target:
        entity_id: switch.foscam_dormitorio_deteccion_de_movimiento

foscam_on:
  alias: Foscam - Activar detección
  sequence:
    - action: switch.turn_on
      target:
        entity_id: switch.foscam_dormitorio_deteccion_de_movimiento
```

Fíjate en que desaparece el doble paso «apagar, mandar el comando, encender».
Existía porque el `command_state` de `command_line` tardaba en ponerse al día;
aquí el interruptor lee el estado en vivo y se refresca solo tras cada cambio.

**`configuration.yaml`** — quita también las entradas de `shell_command`
relacionadas con la Foscam, si las tienes ahí.

Después de borrar, reinicia Home Assistant y elimina en
*Ajustes → Dispositivos y servicios → Entidades* las entidades que queden
marcadas como «no disponible» con el prefijo antiguo.

## 5. Automatizaciones

Sólo cambia el `entity_id` del objetivo. En
[`examples/automatizaciones.yaml`](../examples/automatizaciones.yaml) están las
dos de casa ya reescritas.

Dos cosas que conviene revisar de paso:

* **«Sistema - En casa» no tiene condiciones.** «Salir de casa» sí comprueba
  `input_boolean.modo_alguien_en_casa`. Si la idea es que la detección no se
  apague cuando llegas tú pero sigue habiendo alguien fuera, la condición
  debería estar en las dos, o en ninguna.
* **La automatización de captura usa el sensor Tuya, no la cámara.** Está bien
  así: un sensor de movimiento dedicado suele ser más fiable y rápido que la
  detección por vídeo. Si quieres que también dispare con lo que ve la cámara,
  duplica la automatización apuntando a `binary_sensor.foscam_dormitorio_movimiento`
  en vez de sustituir el sensor Tuya.

## 6. Comprobación final

1. Apaga y enciende el interruptor desde la interfaz y verifica en el panel web
   de la cámara que la sensibilidad, los horarios y las áreas **siguen como
   estaban**. Esto es justo lo que el montaje anterior estropeaba.
2. Sal de casa (o cambia a mano el estado de `person.tu_usuario` desde
   *Herramientas para desarrolladores*) y comprueba que la detección se activa.
3. Mira el historial del `binary_sensor` de movimiento tras un día: deberías ver
   eventos discretos en vez de un sensor de texto rebotando.
