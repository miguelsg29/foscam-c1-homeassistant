"""Diagnósticos de la integración Foscam C1."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_WEB_URL
from .coordinator import FoscamConfigEntry

#: Todo lo que pueda identificar la cámara o su red se oculta: los
#: diagnósticos se pegan en informes de error públicos.
REDACT_CONFIG = {CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_WEB_URL}
REDACT_STATE = {"url", "wifiConnectedAP"}
REDACT_INFO = {"mac", "serialNo", "devName"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FoscamConfigEntry
) -> dict[str, Any]:
    """Devolver los diagnósticos de la entrada de configuración."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": async_redact_data(dict(entry.options), REDACT_CONFIG),
        },
        "motion_variant": coordinator.client.motion_variant,
        "capabilities": data.capabilities,
        "state": async_redact_data(data.state, REDACT_STATE),
        "motion": data.motion,
        "infra": data.infra,
        "siren": data.siren,
        "info": async_redact_data(data.info, REDACT_INFO),
    }
