"""Entidad base compartida por todas las plataformas de Foscam C1."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_WEB_URL, DOMAIN
from .coordinator import FoscamCoordinator


class FoscamEntity(CoordinatorEntity[FoscamCoordinator]):
    """Base con la identidad de dispositivo y el unique_id ya resueltos."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FoscamCoordinator, description: EntityDescription) -> None:
        """Inicializar la entidad."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Describir la cámara en el registro de dispositivos."""
        entry = self.coordinator.config_entry
        info = self.coordinator.data.info if self.coordinator.data else {}
        options = {**entry.data, **entry.options}

        connections = set()
        if mac := info.get("mac"):
            connections.add((CONNECTION_NETWORK_MAC, _format_mac(mac)))

        return DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            connections=connections,
            manufacturer="Foscam",
            model=info.get("productName") or "Foscam IP camera",
            name=entry.title,
            sw_version=info.get("firmwareVer"),
            hw_version=info.get("hardwareVer"),
            serial_number=info.get("serialNo"),
            configuration_url=options.get(CONF_WEB_URL) or self.coordinator.client.base_url,
        )

    @property
    def available(self) -> bool:
        """La entidad está disponible si la última lectura fue correcta."""
        return super().available and bool(self.coordinator.data)


def _format_mac(mac: str) -> str:
    """Normalizar la MAC que devuelve la cámara (sin separadores) a aa:bb:cc..."""
    clean = mac.replace(":", "").replace("-", "").strip().lower()
    if len(clean) != 12:
        return mac.lower()
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))
