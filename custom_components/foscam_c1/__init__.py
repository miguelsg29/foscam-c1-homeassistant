"""Integración Foscam C1 para Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FoscamAuthError, FoscamClient, FoscamError
from .const import (
    CONF_SCAN_INTERVAL_CONFIG,
    CONF_SCAN_INTERVAL_STATE,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL_CONFIG,
    DEFAULT_SCAN_INTERVAL_STATE,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
)
from .coordinator import FoscamConfigEntry, FoscamCoordinator
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: FoscamConfigEntry) -> bool:
    """Configurar una cámara Foscam a partir de una entrada de configuración."""
    options = {**entry.data, **entry.options}

    session = async_get_clientsession(
        hass,
        verify_ssl=options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    client = FoscamClient(
        session,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        ssl=entry.data.get(CONF_SSL, DEFAULT_SSL),
        verify_ssl=options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )

    coordinator = FoscamCoordinator(
        hass,
        entry,
        client,
        state_interval=options.get(CONF_SCAN_INTERVAL_STATE, DEFAULT_SCAN_INTERVAL_STATE),
        config_interval=options.get(CONF_SCAN_INTERVAL_CONFIG, DEFAULT_SCAN_INTERVAL_CONFIG),
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except FoscamAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except FoscamError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator

    async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FoscamConfigEntry) -> bool:
    """Descargar la entrada de configuración."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: FoscamConfigEntry) -> None:
    """Recargar cuando cambien las opciones."""
    await hass.config_entries.async_reload(entry.entry_id)
