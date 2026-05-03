"""Config flow for SquashM8 integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_API_BASE_URL,
    CONF_CHANGE_ID,
    CONF_DEFAULT_DELTA,
    CONF_DEFAULT_OVERRIDE_TARGET,
    CONF_DEFAULT_PEEK,
    CONF_DELETE_FOR_EVERYONE,
    CONF_DELETE_OLDER_MESSAGES,
    CONF_DELETE_ONLY_IF_NO_INTERVENING,
    CONF_EDIT_WINDOW_MINUTES,
    CONF_NOTIFY_SERVICE,
    CONF_REQUEST_TIMEOUT,
    CONF_TARGET_MAP,
    CONF_VERIFY_SSL,
    DEFAULT_API_BASE_URL,
    DEFAULT_CHANGE_ID,
    DEFAULT_DELTA,
    DEFAULT_DELETE_FOR_EVERYONE,
    DEFAULT_DELETE_OLDER_MESSAGES,
    DEFAULT_DELETE_ONLY_IF_NO_INTERVENING,
    DEFAULT_EDIT_WINDOW_MINUTES,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_OVERRIDE_TARGET,
    DEFAULT_PEEK,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_TARGET_MAP,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

def _base_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Build config schema with defaults."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_API_BASE_URL,
                default=defaults.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL),
            ): str,
            vol.Required(
                CONF_CHANGE_ID,
                default=defaults.get(CONF_CHANGE_ID, DEFAULT_CHANGE_ID),
            ): str,
            vol.Required(
                CONF_NOTIFY_SERVICE,
                default=defaults.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE),
            ): str,
            vol.Required(
                CONF_REQUEST_TIMEOUT,
                default=defaults.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
            vol.Required(
                CONF_DEFAULT_PEEK,
                default=defaults.get(CONF_DEFAULT_PEEK, DEFAULT_PEEK),
            ): bool,
            vol.Required(
                CONF_DEFAULT_DELTA,
                default=defaults.get(CONF_DEFAULT_DELTA, DEFAULT_DELTA),
            ): bool,
            vol.Optional(
                CONF_DEFAULT_OVERRIDE_TARGET,
                default=defaults.get(
                    CONF_DEFAULT_OVERRIDE_TARGET, DEFAULT_OVERRIDE_TARGET
                ),
            ): str,
            vol.Optional(
                CONF_TARGET_MAP,
                default=defaults.get(CONF_TARGET_MAP, DEFAULT_TARGET_MAP),
            ): cv.string,
            vol.Required(
                CONF_EDIT_WINDOW_MINUTES,
                default=defaults.get(CONF_EDIT_WINDOW_MINUTES, DEFAULT_EDIT_WINDOW_MINUTES),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=180)),
            vol.Required(
                CONF_DELETE_OLDER_MESSAGES,
                default=defaults.get(
                    CONF_DELETE_OLDER_MESSAGES, DEFAULT_DELETE_OLDER_MESSAGES
                ),
            ): bool,
            vol.Required(
                CONF_DELETE_FOR_EVERYONE,
                default=defaults.get(CONF_DELETE_FOR_EVERYONE, DEFAULT_DELETE_FOR_EVERYONE),
            ): bool,
            vol.Required(
                CONF_DELETE_ONLY_IF_NO_INTERVENING,
                default=defaults.get(
                    CONF_DELETE_ONLY_IF_NO_INTERVENING,
                    DEFAULT_DELETE_ONLY_IF_NO_INTERVENING,
                ),
            ): bool,
        }
    )


class SquashM8ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle SquashM8 config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            title = str(user_input[CONF_CHANGE_ID])
            return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "SquashM8OptionsFlow":
        """Get the options flow for this handler."""
        return SquashM8OptionsFlow(config_entry)


class SquashM8OptionsFlow(config_entries.OptionsFlow):
    """Handle SquashM8 options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        merged = {
            **self._config_entry.data,
            **self._config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_base_schema(merged),
        )
