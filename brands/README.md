# Logo: dónde vive y por qué aquí no hay imágenes

Las imágenes están en **`custom_components/foscam_c1/brand/`**, dentro del
propio paquete de la integración. Desde Home Assistant **2026.3.0** es ahí donde
hay que ponerlas, y las locales tienen prioridad sobre las del CDN de marcas:

```
custom_components/foscam_c1/brand/
├── icon.png        256×256   la marca circular, cuadrada
├── icon@2x.png     512×512
├── logo.png        568×128   el wordmark, lado corto 128
└── logo@2x.png    1135×256   lado corto 256
```

No hace falta tocar `manifest.json` ni abrir ningún PR. Se copian con la
integración y aparecen solas.

## Si tu Home Assistant es anterior a 2026.3.0

En esas versiones el icono se pide a `brands.home-assistant.io` y una carpeta
local no se mira, así que sale el icono genérico de pieza de puzzle. Para
arreglarlo hay que enviar las imágenes al repositorio de marcas:

```bash
git clone https://github.com/home-assistant/brands
mkdir -p brands/custom_integrations/foscam_c1
cp custom_components/foscam_c1/brand/*.png brands/custom_integrations/foscam_c1/
```

Y abrir el PR. Los archivos ya cumplen sus medidas, así que valen tal cual.

Dos límites de esa vía, y por eso no es la principal:

* **No se puede enlazar al logo de la integración oficial.** Sería lo natural
  —el mismo fabricante, el mismo logo, ya está en `core_integrations/foscam`—
  pero *«symlinks are currently not allowed in the custom integrations folder»*.
  Compartir imágenes por enlace sólo vale entre integraciones del core.
* `custom_integrations` está marcada como **carpeta legacy** en ese repositorio.

El logo es una marca registrada de Foscam, usada aquí para identificar el
hardware compatible.
