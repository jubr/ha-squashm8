"""Runtime execution logic for SquashM8."""

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
    CONF_DELETE_FOR_EVERYONE,
    CONF_DELETE_OLDER_MESSAGES,
    CONF_DELETE_ONLY_IF_NO_INTERVENING,
    CONF_EDIT_WINDOW_MINUTES,
    CONF_TARGET_MAP,
    CONF_NOTIFY_SERVICE,
    CONF_REQUEST_TIMEOUT,
    CONF_VERIFY_SSL,
    DEFAULT_DELETE_FOR_EVERYONE,
    DEFAULT_DELETE_OLDER_MESSAGES,
    DEFAULT_DELETE_ONLY_IF_NO_INTERVENING,
    DEFAULT_EDIT_WINDOW_MINUTES,
)
from .state import DayMessageStateStore

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SquashM8Result:
    """Result of a SquashM8 run."""

    status: str
    sent_messages: int = 0
    num_updates: int | None = None
    skipped_reasons: list[str] = field(default_factory=list)
    edited_messages: int = 0
    deleted_messages: int = 0
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
        edit_window_minutes: int,
        delete_older_messages: bool,
        delete_for_everyone: bool,
        delete_only_if_no_intervening: bool,
        state_store: DayMessageStateStore,
    ) -> None:
        """Initialize client."""
        self._hass = hass
        self._endpoint = endpoint
        self._change_id = change_id
        self._notify_service = notify_service
        self._group_targets = dict(group_targets)
        self._request_timeout = request_timeout
        self._verify_ssl = verify_ssl
        self._edit_window_minutes = edit_window_minutes
        self._delete_older_messages = delete_older_messages
        self._delete_for_everyone = delete_for_everyone
        self._delete_only_if_no_intervening = delete_only_if_no_intervening
        self._state_store = state_store

    async def run(
        self,
        *,
        peek: bool,
        delta: bool,
        override_target: str | None,
        ts: int | None = None,
        dry_run: bool = False,
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
        edited_messages = 0
        deleted_messages = 0
        skipped: list[str] = []
        now_ts = int(datetime.now(timezone.utc).timestamp())

        for group_name, items in body.items():
            if group_name == "SquashM8":
                continue
            if not isinstance(items, list):
                skipped.append(f"{group_name}:not_a_list")
                continue

            target = override_target or self._group_targets.get(group_name) or group_name
            if not target:
                skipped.append(f"{group_name}:empty_target")
                continue

            for item in items:
                if not isinstance(item, dict):
                    skipped.append(f"{group_name}:item_not_object")
                    continue

                sentence = item.get("sentence")
                if not sentence:
                    skipped.append(f"{group_name}:empty_sentence")
                    continue

                sent_or_edited, msg_id, operation = await self._upsert_message_for_day(
                    target=target,
                    sentence=str(sentence),
                    item=item,
                    now_ts=now_ts,
                    dry_run=dry_run,
                )
                if sent_or_edited:
                    if operation == "edit":
                        edited_messages += 1
                    else:
                        sent_messages += 1
                day_key = self._day_key(item)
                if msg_id and day_key:
                    prev_id = self._state_store.get_message_id(target=target, day_key=day_key)
                    if self._delete_older_messages and prev_id and prev_id != msg_id:
                        can_delete = True
                        if self._delete_only_if_no_intervening:
                            can_delete = await self._can_delete_prev_safely(
                                target=target,
                                prev_message_id=prev_id,
                                now_ts=now_ts,
                            )
                        if can_delete:
                            if not dry_run:
                                await self._notify_delete_message(
                                    message_id=prev_id,
                                    delete_for_everyone=self._delete_for_everyone,
                                )
                            deleted_messages += 1
                    if not dry_run:
                        self._state_store.set_message_id(
                            target=target,
                            day_key=day_key,
                            message_id=msg_id,
                            timestamp=now_ts,
                        )

        return SquashM8Result(
            status="ok",
            sent_messages=sent_messages,
            edited_messages=edited_messages,
            deleted_messages=deleted_messages,
            num_updates=num_updates,
            endpoint_url=endpoint_url,
            skipped_reasons=skipped,
            raw=body,
        )

    async def _upsert_message_for_day(
        self,
        *,
        target: str,
        sentence: str,
        item: Mapping[str, Any],
        now_ts: int,
        dry_run: bool,
    ) -> tuple[bool, str | None, str]:
        """Edit an existing recent same-day bot message or send new."""
        day_key = self._day_key(item)
        if day_key:
            state_msg_id = self._state_store.get_message_id(target=target, day_key=day_key)
            state_ts = self._state_store.get_timestamp(target=target, day_key=day_key)
            if (
                state_msg_id
                and state_ts is not None
                and now_ts - state_ts <= self._edit_window_minutes * 60
            ):
                try:
                    if not dry_run:
                        await self._notify_edit_message(
                            message_id=state_msg_id,
                            message=sentence,
                        )
                    return True, state_msg_id, "edit"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Edit fallback to send for target=%s day_key=%s msg_id=%s: %s",
                        target,
                        day_key,
                        state_msg_id,
                        err,
                    )

        if dry_run:
            return True, None, "send"
        message_id = await self._notify_send_message(target=target, message=sentence)
        return bool(message_id), message_id, "send"

    async def _can_delete_prev_safely(
        self,
        *,
        target: str,
        prev_message_id: str,
        now_ts: int,
    ) -> bool:
        """Check if old bot message can be safely deleted-for-everyone."""
        details = await self._fetch_message_details(prev_message_id)
        if not details:
            return False
        if not _is_from_me(details):
            return False
        prev_ts = _message_timestamp(details)
        if prev_ts is None:
            return False
        if now_ts - prev_ts > self._edit_window_minutes * 60:
            return False
        has_foreign = await self._has_non_bot_messages_between(
            target=target,
            start_ts=prev_ts,
            end_ts=now_ts,
        )
        return not has_foreign

    async def _fetch_message_details(self, message_id: str) -> dict[str, Any] | None:
        """Fetch message details from add-on message endpoint."""
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
        url = f"{self._endpoint}?squash=getMessageById&messageId={aiohttp.helpers.quote(message_id)}"
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url) as response:
                if response.status == 404:
                    return None
                response.raise_for_status()
                data = await response.json(content_type=None)
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, dict):
                return msg
        return None

    async def _has_non_bot_messages_between(
        self,
        *,
        target: str,
        start_ts: int,
        end_ts: int,
    ) -> bool:
        """Ask add-on if foreign messages exist in interval."""
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
        url = (
            f"{self._endpoint}?squash=hasForeignMessagesInWindow"
            f"&target={aiohttp.helpers.quote(target, safe='@._-')}"
            f"&startTs={start_ts}&endTs={end_ts}"
        )
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url) as response:
                if response.status == 404:
                    return True
                response.raise_for_status()
                data = await response.json(content_type=None)
        if isinstance(data, dict):
            return bool(data.get("hasForeignMessages", True))
        return True

    async def _notify_send_message(self, *, target: str, message: str) -> str | None:
        """Send message and return resulting message id when available."""
        domain, service = self._notify_service.split(".", 1)
        response = await self._hass.services.async_call(
            domain,
            service,
            {"target": target, "message": message},
            blocking=True,
            return_response=True,
        )
        return _extract_message_id_from_response(response)

    async def _notify_edit_message(self, *, message_id: str, message: str) -> None:
        """Edit previously sent message via notify service route."""
        domain, service = self._notify_service.split(".", 1)
        await self._hass.services.async_call(
            domain,
            service,
            {
                "message": message,
                "data": {"edit_message_id": message_id},
            },
            blocking=True,
        )

    async def _notify_delete_message(self, *, message_id: str, delete_for_everyone: bool) -> None:
        """Delete message via notify service route."""
        domain, service = self._notify_service.split(".", 1)
        await self._hass.services.async_call(
            domain,
            service,
            {
                "message": "ignored for delete route",
                "data": {
                    "delete_message_id": message_id,
                    "delete_for_everyone": delete_for_everyone,
                },
            },
            blocking=True,
        )

    def _find_edit_candidate(
        self,
        *,
        recent_messages: list[dict[str, Any]],
        day_key: str,
        now_ts: int,
    ) -> dict[str, Any] | None:
        """Find newest editable same-day bot message within edit window."""
        for msg in recent_messages:
            msg_id = str(msg.get("id") or "")
            if not msg_id:
                continue
            if not _is_from_me(msg):
                continue
            body = str(msg.get("body") or "")
            if day_key not in body:
                continue
            msg_ts = _message_timestamp(msg)
            if msg_ts is None:
                continue
            if now_ts - msg_ts > self._edit_window_minutes * 60:
                continue
            return msg
        return None

    @staticmethod
    def _day_key(item: Mapping[str, Any]) -> str | None:
        """Get stable day key for grouping message edits/cleanup."""
        day_col_key = item.get("dayColKey")
        if isinstance(day_col_key, str) and day_col_key.strip():
            return day_col_key.strip()
        day = item.get("day")
        if isinstance(day, str) and day.strip():
            return day.strip()
        return None

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
            edit_window_minutes=int(
                merged.get(CONF_EDIT_WINDOW_MINUTES, DEFAULT_EDIT_WINDOW_MINUTES)
            ),
            delete_older_messages=bool(
                merged.get(CONF_DELETE_OLDER_MESSAGES, DEFAULT_DELETE_OLDER_MESSAGES)
            ),
            delete_for_everyone=bool(
                merged.get(CONF_DELETE_FOR_EVERYONE, DEFAULT_DELETE_FOR_EVERYONE)
            ),
            delete_only_if_no_intervening=bool(
                merged.get(
                    CONF_DELETE_ONLY_IF_NO_INTERVENING,
                    DEFAULT_DELETE_ONLY_IF_NO_INTERVENING,
                )
            ),
            state_store=DayMessageStateStore(hass),
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


def _extract_message_id_from_response(response: Any) -> str | None:
    """Try to extract message id from notify service response."""
    if isinstance(response, dict):
        for key in ("message_id", "messageId", "id"):
            value = response.get(key)
            if isinstance(value, str) and value:
                return value
        nested = response.get("result")
        if isinstance(nested, dict):
            return _extract_message_id_from_response(nested)
    return None


def _is_from_me(message: Mapping[str, Any]) -> bool:
    """Normalize sender ownership flag from different payload shapes."""
    value = message.get("fromMe")
    if value is None:
        value = message.get("from_me")
    return bool(value)


def _message_timestamp(message: Mapping[str, Any]) -> int | None:
    """Extract unix timestamp in seconds from message payload."""
    raw = message.get("timestamp")
    if raw is None:
        raw = message.get("ts")
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None


