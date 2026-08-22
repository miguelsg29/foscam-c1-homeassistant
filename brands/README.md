# Assets para `home-assistant/brands`

Home Assistant **no lee el logo de este repositorio**. La interfaz lo pide a
`brands.home-assistant.io` usando el dominio de la integración, así que mientras
no exista allí, el icono es el genérico de pieza de puzzle.

Estos archivos están generados con las medidas que exige el repositorio de
marcas y listos para enviar:

| Archivo | Tamaño | Qué es |
| --- | --- | --- |
| `icon.png` | 256×256 | La marca circular, cuadrada y centrada |
| `icon@2x.png` | 512×512 | La misma al doble |
| `logo.png` | 512×115 | El wordmark completo |
| `logo@2x.png` | 1024×231 | El mismo al doble |

## Cómo publicarlos

Es un PR a otro repositorio, así que hay que hacerlo a mano:

```bash
git clone https://github.com/home-assistant/brands
cd brands
mkdir -p custom_integrations/foscam_c1
cp /ruta/a/este/repo/brands/custom_integrations/foscam_c1/*.png custom_integrations/foscam_c1/
```

Y se abre el PR. Sus comprobaciones verifican tamaños y transparencia; por eso
los archivos ya salen con las medidas exactas.

El logo es una marca registrada de Foscam. El repositorio de marcas de Home
Assistant aloja logos de fabricantes justamente para identificar el hardware
compatible, que es el uso que se le da aquí.
