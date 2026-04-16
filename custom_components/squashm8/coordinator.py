"""Data update coordinator for SquashM8."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any

import aiohttp
from homeassistant.components.notify import DOMAIN as NOTIFY_DOMAIN
from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_BASE_URL,
    CONF_CHANGE_ID,
    CONF_TARGET_MAP,
    CONF_NOTIFY_SERVICE,
    CONF_REQUEST_TIMEOUT,
    CONF_VERIFY_SSL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SquashM8Result:
    """Result of a SquashM8 run."""

    status: str
    sent_messages: int = 0
    num_updates: int | None = None
    skipped_reasons: list[str] = field(default_factory=list)
    endpoint_url: str | None = None
    raw: dict[str, Any] | None = None


class SquashM8Client:
    """Client wrapper around SquashM8 endpoint + WhatsApp notify."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        endpoint: str,
        change_id: str,
        notify_service: str,
        group_targets: Mapping[str, str],
        request_timeout: float,
        verify_ssl: bool,
    ) -> None:
        """Initialize client."""
        self._hass = hass
        self._endpoint = endpoint
        self._change_id = change_id
        self._notify_service = notify_service
        self._group_targets = dict(group_targets)
        self._request_timeout = request_timeout
        self._verify_ssl = verify_ssl

    async def run(
        self,
        *,
        peek: bool,
        delta: bool,
        override_target: str | None,
        ts: int | None = None,
    ) -> SquashM8Result:
        """Execute SquashM8 fetch + optional notify fanout."""
        self.validate_notify_service(self._notify_service)
        if ts is None:
            ts = int(datetime.now(timezone.utc).timestamp())
        peek_int = 1 if peek else 0
        endpoint_url = (
            f"{self._endpoint}"
            f"?squash=getGroupMessages"
            f"&changeId={self._change_id}"
            f"&peek={peek_int}"
            f"&ts={ts}"
        )
        _LOGGER.debug("Calling SquashM8 endpoint: %s", endpoint_url)

        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl)

        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(endpoint_url) as response:
                response.raise_for_status()
                body: dict[str, Any] = await response.json(content_type=None)

        num_updates = _extract_num_updates(body)
        if delta and num_updates == 0:
            return SquashM8Result(
                status="ok",
                num_updates=0,
                endpoint_url=endpoint_url,
                skipped_reasons=["delta_enabled_and_no_updates"],
                raw=body,
            )

        sent_messages = 0
        skipped: list[str] = []

        for group_name, items in body.items():
            if group_name == "SquashM8":
                continue
            if not isinstance(items, list):
                skipped.append(f"{group_name}:not_a_list")
                continue

            target = override_target or self._group_targets.get(group_name) or group_name

            for item in items:
                if not isinstance(item, dict):
                    skipped.append(f"{group_name}:item_not_object")
                    continue

                sentence = item.get("sentence")
                if not sentence:
                    skipped.append(f"{group_name}:empty_sentence")
                    continue

                if "." not in self._notify_service:
                    skipped.append(f"{group_name}:invalid_notify_service")
                    continue

                domain, service = self._notify_service.split(".", 1)
                await self._hass.services.async_call(
                    domain,
                    service,
                    {"target": target, "message": sentence},
                    blocking=True,
                )
                sent_messages += 1

        return SquashM8Result(
            status="ok",
            sent_messages=sent_messages,
            num_updates=num_updates,
            endpoint_url=endpoint_url,
            skipped_reasons=skipped,
            raw=body,
        )

    @staticmethod
    def validate_notify_service(notify_service: str) -> None:
        """Validate notify service identifier."""
        if "." not in notify_service:
            raise ValueError(
                "notify_service must be in '<domain>.<service>' format "
                "(example: notify.whatsappur)"
            )
        domain, _ = notify_service.split(".", 1)
        if domain != NOTIFY_DOMAIN:
            raise ValueError("notify_service must be a notify.* service")

    @classmethod
    def from_config_entry(
        cls,
        hass: HomeAssistant,
        data: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> "SquashM8Client":
        """Create client using config entry data+options."""
        merged = {**data, **options}
        notify_service = str(merged[CONF_NOTIFY_SERVICE])
        cls.validate_notify_service(notify_service)
        return cls(
            hass,
            endpoint=str(merged[CONF_API_BASE_URL]),
            change_id=str(merged[CONF_CHANGE_ID]),
            notify_service=notify_service,
            group_targets=_normalize_group_targets(merged.get(CONF_TARGET_MAP)),
            request_timeout=float(merged.get(CONF_REQUEST_TIMEOUT, 10)),
            verify_ssl=bool(merged.get(CONF_VERIFY_SSL, True)),
        )


def _normalize_group_targets(value: Any) -> dict[str, str]:
    """Normalize group targets input."""
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {}


def _extract_num_updates(body: dict[str, Any]) -> int | None:
    """Extract numUpdates from SquashM8 response shape."""
    meta = body.get("SquashM8")
    if isinstance(meta, list) and meta and isinstance(meta[0], dict):
        num_updates = meta[0].get("numUpdates")
        if isinstance(num_updates, int):
            return num_updates
    return None
