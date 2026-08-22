# Referencia rápida de la API CGI de Foscam

Resumen de lo que usa esta integración. La referencia completa es la *Foscam
IPCamera CGI User Guide* del fabricante.

## Forma de las peticiones

```
https://<host>:<puerto>/cgi-bin/CGIProxy.fcgi?cmd=<comando>&usr=<usuario>&pwd=<contraseña>[&param=valor…]
```

La respuesta es XML plano:

```xml
<CGI_Result>
  <result>0</result>
  <isEnable>1</isEnable>
</CGI_Result>
```

Dos rarezas del firmware que la integración tiene en cuenta:

* El XML **no siempre es válido**. Un SSID con un `&` sin escapar rompe cualquier
  parser estricto, así que `api.py` cae a una extracción por expresión regular
  cuando el parseo falla, en vez de dejar la entidad indisponible.
* Algunos firmwares **no descodifican el porcentaje** en `usr` y `pwd`. Si la
  autenticación falla con las credenciales codificadas, el cliente reintenta una
  vez enviándolas en crudo y recuerda cuál de los dos modos funciona.

## Códigos de `result`

| Código | Significado |
| --- | --- |
| `0` | Correcto |
| `-1` | Error de formato en la petición CGI |
| `-2` | Usuario o contraseña incorrectos |
| `-3` | Acceso denegado (privilegios insuficientes) |
| `-4` | Fallo al ejecutar el CGI |
| `-5` | Tiempo de espera agotado |
| `-6` a `-8` | Reservado / error desconocido |

En la práctica, `-1`, `-4`, `-7` y `-8` son también lo que devuelve una cámara
cuando el comando **no existe en su firmware**. La integración usa eso para
descubrir qué soporta cada modelo (`api.async_probe`).

## Comandos que usa la integración

| Comando | Para qué | Privilegio |
| --- | --- | --- |
| `getDevState` | Alarmas en vivo, tarjeta SD, wifi, LED IR | admin |
| `getDevInfo` | Modelo, firmware, MAC, número de serie | admin |
| `getMotionDetectConfig` / `getMotionDetectConfig1` | Configuración de detección | admin |
| `setMotionDetectConfig` / `setMotionDetectConfig1` | Escribir esa configuración | admin |
| `getInfraLedConfig`, `setInfraLedConfig`, `openInfraLed`, `closeInfraLed` | LED infrarrojo | admin |
| `getSirenConfig`, `setSirenConfig` | Sirena, en los modelos que la llevan | admin |
| `snapPicture2` | Foto fija (devuelve el JPEG directamente) | visitor |
| `rebootSystem` | Reiniciar | admin |

## Campos de `getDevState`

| Campo | Valores |
| --- | --- |
| `motionDetectAlarm` | `0` desactivada · `1` sin alarma · `2` movimiento detectado |
| `soundAlarm` | Igual que el anterior |
| `IOAlarm` | Igual, para la entrada de alarma externa |
| `record` | `0` no graba · `1` grabando |
| `sdState` | `0` sin tarjeta · `1` correcta · `2` sólo lectura |
| `sdFreeSpace`, `sdTotalSpace` | Kilobytes |
| `ntpState`, `ddnsState`, `upnpState` | `0` desactivado · `1` correcto · `2` fallo |
| `isWifiConnected`, `wifiConnectedAP` | Conexión wifi y SSID |
| `infraLedState` | `0` apagado · `1` encendido |

Que `motionDetectAlarm` valga `0` cuando la detección está desactivada es lo que
permite que el interruptor de esta integración responda en segundos: no hace
falta releer la configuración completa para saber si está encendido.

## Los tres campos raros de la configuración de movimiento

### `linkage`

Máscara de bits con lo que hace la cámara al detectar movimiento:

| Bit | Valor | Acción |
| --- | --- | --- |
| 0 | 1 | Zumbador |
| 1 | 2 | Enviar email |
| 2 | 4 | Guardar foto |
| 3 | 8 | Grabar vídeo |

Un `linkage=142` son los bits 1, 2, 3 y 7: email, foto, grabación y un bit
adicional propio del firmware. La integración expone los cuatro documentados
como interruptores y **conserva intactos los bits que no conoce**.

### `schedule0` … `schedule6`

Un entero de 48 bits por día de la semana (`schedule0` = domingo), donde cada
bit es media hora. `281474976710655` es `2^48 - 1`: las 24 horas activas.

### `area0` … `area9`

Una fila cada uno de la rejilla de detección, 10 bits por fila. `1023` es
`2^10 - 1`: la fila entera activa.

## El detalle que importa

`setMotionDetectConfig` **no** es una actualización parcial: los parámetros que
no envías se pierden. Por eso la configuración basada en `curl` tenía que
repetir los veinte campos en cada llamada, y por eso un error de copia y pega
en esa URL te reseteaba las áreas de detección sin avisar.

`FoscamClient.async_update_motion_config()` lee la configuración actual, aplica
encima sólo lo que cambias y reenvía el conjunto completo. Es la razón principal
de que exista esta integración.

## Explorar por tu cuenta

```bash
python tools/probe_camera.py --host 192.0.2.10 --port 443 --user camera_user
```

O desde Home Assistant, sin salir de la interfaz:

```yaml
action: foscam_c1.cgi_command
data:
  device_id: "{{ device_id('switch.foscam_deteccion_de_movimiento') }}"
  command: getImageSetting
response_variable: respuesta
```
