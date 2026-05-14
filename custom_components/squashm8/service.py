"""Service handlers for SquashM8."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_DRY_RUN,
    ATTR_DELTA,
    ATTR_ENTRY_ID,
    ATTR_OVERRIDE_TARGET,
    ATTR_PEEK,
    ATTR_TS,
    CONF_DEFAULT_DELTA,
    CONF_DEFAULT_OVERRIDE_TARGET,
    CONF_DEFAULT_PEEK,
    DOMAIN,
    LOGGER,
    SERVICE_RUN,
)
from .coordinator import SquashM8Client

SERVICE_RUN_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_PEEK): cv.boolean,
        vol.Optional(ATTR_DELTA): cv.boolean,
        vol.Optional(ATTR_OVERRIDE_TARGET): cv.string,
        vol.Optional(ATTR_TS): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_DRY_RUN): cv.boolean,
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register services for this integration."""

    async def _async_handle_run(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        options: Mapping[str, Any] = entry.options
        data: Mapping[str, Any] = entry.data

        client = SquashM8Client.from_config_entry(hass, data=data, options=options)
        default_peek = bool(options.get(CONF_DEFAULT_PEEK, False))
        default_delta = bool(options.get(CONF_DEFAULT_DELTA, True))
        peek = call.data.get(ATTR_PEEK, default_peek)
        delta = call.data.get(ATTR_DELTA, default_delta)
        override_target = call.data.get(
            ATTR_OVERRIDE_TARGET, options.get(CONF_DEFAULT_OVERRIDE_TARGET)
        )
        ts = call.data.get(ATTR_TS)
        dry_run = bool(call.data.get(ATTR_DRY_RUN, False))
        peek_from_service_data = ATTR_PEEK in call.data
        delta_from_service_data = ATTR_DELTA in call.data

        LOGGER.info(
            (
                "Running SquashM8 service: resolved_peek=%s "
                "(source=%s, default_peek=%s), resolved_delta=%s "
                "(source=%s, default_delta=%s), override_target=%s, "
                "entry_id=%s, dry_run=%s"
            ),
            peek,
            "service_call" if peek_from_service_data else "entry_option_default",
            default_peek,
            delta,
            "service_call" if delta_from_service_data else "entry_option_default",
            default_delta,
            override_target,
            entry.entry_id,
            dry_run,
        )
        LOGGER.debug(
            "SquashM8 service call payload keys=%s raw_data=%s",
            sorted(call.data.keys()),
            dict(call.data),
        )
        result = await client.run(
            peek=bool(peek),
            delta=bool(delta),
            override_target=str(override_target) if override_target else None,
            ts=int(ts) if ts is not None else None,
            dry_run=dry_run,
        )
        LOGGER.info(
            (
                "SquashM8 run completed: status=%s entry_id=%s endpoint_url=%s "
                "num_updates=%s sent=%s edited=%s deleted=%s skipped=%s dry_run=%s"
            ),
            result.status,
            entry.entry_id,
            result.endpoint_url,
            result.num_updates,
            result.sent_messages,
            result.edited_messages,
            result.deleted_messages,
            result.skipped_reasons,
            dry_run,
        )
        return {
            "status": result.status,
            "entry_id": entry.entry_id,
            "sent_messages": result.sent_messages,
            "num_updates": result.num_updates,
            "endpoint_url": result.endpoint_url,
            "skipped_reasons": result.skipped_reasons,
            "edited_messages": result.edited_messages,
            "deleted_messages": result.deleted_messages,
            "dry_run": dry_run,
        }

    if hass.services.has_service(DOMAIN, SERVICE_RUN):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN,
        _async_handle_run,
        schema=SERVICE_RUN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN):
        hass.services.async_remove(DOMAIN, SERVICE_RUN)


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    """Resolve config entry for service call."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("No SquashM8 config entries found")

    if entry_id:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise HomeAssistantError(f"SquashM8 entry not found: {entry_id}")

    if len(entries) > 1:
        raise HomeAssistantError(
            "Multiple SquashM8 entries found; pass entry_id to service call"
        )
    return entries[0]
