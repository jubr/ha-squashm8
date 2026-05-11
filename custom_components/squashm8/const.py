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
CONF_EDIT_WINDOW_MINUTES: Final = "edit_window_minutes"
CONF_DELETE_OLDER_MESSAGES: Final = "delete_older_messages"
CONF_DELETE_FOR_EVERYONE: Final = "delete_for_everyone"
CONF_DELETE_ONLY_IF_NO_INTERVENING: Final = "delete_only_if_no_intervening_nonbot"

ATTR_ENTRY_ID: Final = "entry_id"
ATTR_PEEK: Final = "peek"
ATTR_DELTA: Final = "delta"
ATTR_OVERRIDE_TARGET: Final = "override_target"
ATTR_TS: Final = "ts"
ATTR_DRY_RUN: Final = "dry_run"

DEFAULT_API_BASE_URL: Final = "https://www.squashmatties.nl/SquashM8.php"
DEFAULT_CHANGE_ID: Final = "HomeAssistant"
DEFAULT_NOTIFY_SERVICE: Final = "notify.whatsappur"
DEFAULT_REQUEST_TIMEOUT: Final = 20
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_PEEK: Final = False
DEFAULT_DELTA: Final = True
DEFAULT_OVERRIDE_TARGET: Final = "SquashM8"
DEFAULT_EDIT_WINDOW_MINUTES: Final = 20
DEFAULT_DELETE_OLDER_MESSAGES: Final = True
DEFAULT_DELETE_FOR_EVERYONE: Final = False
DEFAULT_DELETE_ONLY_IF_NO_INTERVENING: Final = True

# Mirrors the existing Whatsapper target mapping in current HA automation.
DEFAULT_TARGET_MAP: Final[dict[str, str]] = {
    "Squashmatties": "31634100340-1473282680@g.us",
    "Maandag squash": "31653633644-1557724390@g.us",
    "SquashM8": "31622757549-1355307721@g.us",
    "Home Assistant": "31642497272-1533217925@g.us",
    "Jurgen AutoReminder CopyP": "31651819423-1354469583@g.us",
}

LOGGER = logging.getLogger(__package__)
