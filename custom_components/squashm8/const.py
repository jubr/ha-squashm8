"""Constants for the SquashM8 integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "squashm8"
SERVICE_RUN: Final = "run"

CONF_API_BASE_URL: Final = "api_base_url"
CONF_CHANGE_ID: Final = "change_id"
CONF_NOTIFY_SERVICE: Final = "notify_service"
CONF_REQUEST_TIMEOUT: Final = "request_timeout"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_DEFAULT_PEEK: Final = "default_peek"
CONF_DEFAULT_DELTA: Final = "default_delta"
CONF_DEFAULT_OVERRIDE_TARGET: Final = "default_override_target"
CONF_TARGET_MAP: Final = "target_map"

ATTR_ENTRY_ID: Final = "entry_id"
ATTR_PEEK: Final = "peek"
ATTR_DELTA: Final = "delta"
ATTR_OVERRIDE_TARGET: Final = "override_target"
ATTR_TS: Final = "ts"

DEFAULT_API_BASE_URL: Final = "https://www.squashmatties.nl/SquashM8.php"
DEFAULT_CHANGE_ID: Final = "HomeAssistant"
DEFAULT_NOTIFY_SERVICE: Final = "notify.whatsappur"
DEFAULT_REQUEST_TIMEOUT: Final = 20
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_PEEK: Final = False
DEFAULT_DELTA: Final = True
DEFAULT_OVERRIDE_TARGET: Final = "SquashM8"

# Mirrors the existing Whatsapper target mapping in current HA automation.
DEFAULT_TARGET_MAP: Final[dict[str, str]] = {
    "Squashmatties": "31634100340-1473282680@g.us",
    "Maandag squash": "31653633644-1557724390@g.us",
    "SquashM8": "31622757549-1355307721@g.us",
    "Home Assistant": "31642497272-1533217925@g.us",
    "Jurgen AutoReminder CopyP": "31651819423-1354469583@g.us",
}

LOGGER = logging.getLogger(__package__)
