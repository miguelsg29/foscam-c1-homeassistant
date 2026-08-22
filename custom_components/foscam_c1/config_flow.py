"""Flujo de configuración de la integración Foscam C1."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FoscamAuthError, FoscamClient, FoscamError
from .const import (
    CONF_SCAN_INTERVAL_CONFIG,
    CONF_SCAN_INTERVAL_STATE,
    CONF_SSL,
    CONF_VERIFY_SSL,
    CONF_WEB_URL,
    DEFAULT_PORT_HTTPS,
    DEFAULT_SCAN_INTERVAL_CONFIG,
    DEFAULT_SCAN_INTERVAL_STATE,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MAX_SCAN_INTERVAL_STATE,
    MIN_SCAN_INTERVAL_STATE,
)

_LOGGER = logging.getLogger(__name__)


class AccountNotAdminError(FoscamError):
    """Las credenciales valen, pero la cuenta no puede leer la detección."""


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT_HTTPS): vol.Coerce(int),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SSL, default=DEFAULT_SSL): bool,
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


async def _async_validate(hass, data: Mapping[str, Any]) -> dict[str, str]:
    """Comprobar que podemos hablar con la cámara y devolver su información."""
    session = async_get_clientsession(
        hass, verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    )
    client = FoscamClient(
        session,
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        ssl=data.get(CONF_SSL, DEFAULT_SSL),
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    # Primero, ¿valen las credenciales? getDevInfo es la comprobación más
    # barata, y que falle significa inequívocamente usuario o contraseña.
    info = await client.async_get_dev_info()

    # Después, ¿es la cuenta de administrador? Sin ese permiso media
    # integración quedaría inservible, así que es mejor avisar ahora que
    # dejar entidades a medias.
    try:
        await client.async_detect_motion_variant()
    except FoscamAuthError as err:
        raise AccountNotAdminError(str(err)) from err
    return info


class FoscamConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configurar una cámara Foscam desde la interfaz."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pedir los datos de conexión."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _async_validate(self.hass, user_input)
            except AccountNotAdminError:
                errors["base"] = "no_admin"
            except FoscamAuthError:
                errors["base"] = "invalid_auth"
            except FoscamError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Error inesperado validando la cámara")
                errors["base"] = "unknown"
            else:
                unique_id = info.get("serialNo") or info.get("mac")
                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured(updates=dict(user_input))
                else:
                    self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
                title = info.get("devName") or info.get("productName") or "Foscam"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Empezar la reautenticación cuando la cámara rechaza las credenciales."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pedir credenciales nuevas."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            candidate = {**entry.data, **user_input}
            try:
                await _async_validate(self.hass, candidate)
            except AccountNotAdminError:
                errors["base"] = "no_admin"
            except FoscamAuthError:
                errors["base"] = "invalid_auth"
            except FoscamError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Devolver el flujo de opciones."""
        return FoscamOptionsFlow()


class FoscamOptionsFlow(OptionsFlow):
    """Ajustes que se pueden cambiar sin volver a configurar la cámara."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Mostrar y guardar las opciones."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_STATE,
                    default=current.get(CONF_SCAN_INTERVAL_STATE, DEFAULT_SCAN_INTERVAL_STATE),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL_STATE, max=MAX_SCAN_INTERVAL_STATE),
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL_CONFIG,
                    default=current.get(CONF_SCAN_INTERVAL_CONFIG, DEFAULT_SCAN_INTERVAL_CONFIG),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                vol.Required(
                    CONF_VERIFY_SSL,
                    default=current.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                ): bool,
                vol.Optional(CONF_WEB_URL, default=current.get(CONF_WEB_URL, "")): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
