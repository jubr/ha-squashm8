"""SquashM8 custom integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .service import async_register_services, async_unregister_services


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up SquashM8 from YAML (not used)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SquashM8 from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"entry_id": entry.entry_id}

    if len(hass.config_entries.async_entries(DOMAIN)) == 1:
        await async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload SquashM8 entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if not hass.config_entries.async_entries(DOMAIN):
        await async_unregister_services(hass)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)
