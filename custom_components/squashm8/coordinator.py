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
from homeassistant.exceptions import HomeAssistantError

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
        payload_summary = _summarize_payload(body)
        _LOGGER.info(
            (
                "SquashM8 endpoint response: endpoint=%s peek=%s delta=%s "
                "num_updates=%s summary=%s"
            ),
            endpoint_url,
            peek,
            delta,
            num_updates,
            payload_summary,
        )
        if delta and num_updates == 0:
            _LOGGER.info(
                "Delta mode active and num_updates=0; skipping outbound notify fanout"
            )
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
                _LOGGER.debug(
                    "Skipping group '%s': expected list but got %s",
                    group_name,
                    type(items).__name__,
                )
                continue

            target = override_target or self._group_targets.get(group_name) or group_name
            if not target:
                skipped.append(f"{group_name}:empty_target")
                _LOGGER.debug("Skipping group '%s': empty resolved target", group_name)
                continue
            _LOGGER.debug(
                (
                    "Processing group '%s': items=%s resolved_target='%s' "
                    "override_target='%s'"
                ),
                group_name,
                len(items),
                target,
                override_target,
            )

            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    skipped.append(f"{group_name}:item_not_object")
                    _LOGGER.debug(
                        "Skipping %s item #%s: expected object but got %s",
                        group_name,
                        item_index,
                        type(item).__name__,
                    )
                    continue

                sentence = item.get("sentence")
                if not sentence:
                    skipped.append(f"{group_name}:empty_sentence")
                    _LOGGER.debug(
                        "Skipping %s item #%s: empty sentence. keys=%s",
                        group_name,
                        item_index,
                        sorted(item.keys()),
                    )
                    continue

                day_key = self._day_key(item)
                update_marker = _extract_update_marker(item)
                if delta and not update_marker:
                    skip_day_key = day_key or "unknown_day"
                    skipped.append(f"{group_name}:{skip_day_key}:delta_no_update")
                    _LOGGER.debug(
                        (
                            "Delta skip for %s item #%s: update marker empty "
                            "day_key=%s target=%s raw_update=%r"
                        ),
                        group_name,
                        item_index,
                        skip_day_key,
                        target,
                        item.get("update"),
                    )
                    continue
                if (
                    delta
                    and day_key
                    and update_marker
                    and self._state_store.get_update_marker(target=target, day_key=day_key)
                    == update_marker
                ):
                    skipped.append(f"{group_name}:{day_key}:delta_unchanged_update_marker")
                    _LOGGER.debug(
                        (
                            "Delta skip for %s item #%s: unchanged update marker "
                            "day_key=%s target=%s"
                        ),
                        group_name,
                        item_index,
                        day_key,
                        target,
                    )
                    continue
                _LOGGER.debug(
                    "Upserting %s item #%s day_key=%s sentence_preview=%r",
                    group_name,
                    item_index,
                    day_key,
                    _preview_sentence(str(sentence)),
                )
                sent_or_edited, msg_id, operation = await self._upsert_message_for_day(
                    target=target,
                    sentence=str(sentence),
                    item=item,
                    now_ts=now_ts,
                    dry_run=dry_run,
                )
                _LOGGER.debug(
                    (
                        "Upsert result for %s item #%s: operation=%s "
                        "sent_or_edited=%s msg_id=%s"
                    ),
                    group_name,
                    item_index,
                    operation,
                    sent_or_edited,
                    msg_id,
                )
                if sent_or_edited:
                    if operation == "edit":
                        edited_messages += 1
                    elif operation == "send":
                        sent_messages += 1
                if day_key and update_marker and not dry_run:
                    self._state_store.set_update_marker(
                        target=target,
                        day_key=day_key,
                        update_marker=update_marker,
                    )
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
                            _LOGGER.debug(
                                "Deleted stale message for target=%s day_key=%s msg_id=%s",
                                target,
                                day_key,
                                prev_id,
                            )
                    if not dry_run:
                        self._state_store.set_message_id(
                            target=target,
                            day_key=day_key,
                            message_id=msg_id,
                            timestamp=now_ts,
                            body=str(sentence),
                        )
                        _LOGGER.debug(
                            "Stored state message_id for target=%s day_key=%s msg_id=%s",
                            target,
                            day_key,
                            msg_id,
                        )
                elif day_key and operation == "send" and sent_or_edited and not dry_run:
                    self._state_store.set_message_observation(
                        target=target,
                        day_key=day_key,
                        timestamp=now_ts,
                        body=str(sentence),
                    )
                    _LOGGER.debug(
                        "Stored state observation without message_id for target=%s day_key=%s",
                        target,
                        day_key,
                    )

        _LOGGER.info(
            (
                "SquashM8 notify fanout completed: sent=%s edited=%s deleted=%s "
                "num_updates=%s skipped=%s"
            ),
            sent_messages,
            edited_messages,
            deleted_messages,
            num_updates,
            skipped,
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
        edit_candidate_msg_id: str | None = None
        state_ts: int | None = None
        state_body: str | None = None
        if day_key:
            state_msg_id = self._state_store.get_message_id(target=target, day_key=day_key)
            state_ts = self._state_store.get_timestamp(target=target, day_key=day_key)
            state_body = self._state_store.get_body(target=target, day_key=day_key)
            if (
                state_msg_id
                and state_ts is not None
                and now_ts - state_ts <= self._edit_window_minutes * 60
            ):
                edit_candidate_msg_id = state_msg_id
                _LOGGER.debug(
                    "Using state-store edit candidate target=%s day_key=%s msg_id=%s",
                    target,
                    day_key,
                    edit_candidate_msg_id,
                )

            # Fallback path: recover a candidate from channel history when the notify
            # send response did not include a message id in earlier runs.
            if not edit_candidate_msg_id:
                edit_candidate_msg_id = await self._find_edit_candidate_from_recent_messages(
                    target=target,
                    item=item,
                    now_ts=now_ts,
                )
                if edit_candidate_msg_id:
                    _LOGGER.debug(
                        "Using history-derived edit candidate target=%s day_key=%s msg_id=%s",
                        target,
                        day_key,
                        edit_candidate_msg_id,
                    )

            # Last-resort fallback: if we recently sent the same body for this day but
            # did not get a provider message id, avoid sending duplicates.
            if (
                not edit_candidate_msg_id
                and state_ts is not None
                and now_ts - state_ts <= self._edit_window_minutes * 60
                and isinstance(state_body, str)
                and state_body == sentence.strip()
            ):
                _LOGGER.debug(
                    (
                        "Skipping duplicate send (idless recent state match) "
                        "target=%s day_key=%s"
                    ),
                    target,
                    day_key,
                )
                return False, None, "skip"

        if edit_candidate_msg_id:
            try:
                if not dry_run:
                    await self._notify_edit_message(
                        message_id=edit_candidate_msg_id,
                        message=sentence,
                    )
                _LOGGER.debug(
                    "Edit succeeded for target=%s day_key=%s msg_id=%s",
                    target,
                    day_key,
                    edit_candidate_msg_id,
                )
                return True, edit_candidate_msg_id, "edit"
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Edit fallback to send for target=%s day_key=%s msg_id=%s: %s",
                    target,
                    day_key,
                    edit_candidate_msg_id,
                    err,
                )

        if dry_run:
            _LOGGER.debug("Dry run active; skipping send for target=%s", target)
            return True, None, "send"
        message_id = await self._notify_send_message(target=target, message=sentence)
        if not message_id:
            message_id = await self._find_recent_message_id_for_body(
                target=target,
                body=sentence,
                now_ts=now_ts,
            )
        _LOGGER.debug(
            "Send attempted for target=%s returned message_id=%s", target, message_id
        )
        # Sending succeeded if no exception was raised, even when provider response
        # does not include an explicit message id.
        return True, message_id, "send"

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
        service_data = {"target": target, "message": message}
        try:
            response = await self._hass.services.async_call(
                domain,
                service,
                service_data,
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            # Some notify services do not expose responses. In that case, send the
            # message without requesting a response and continue gracefully.
            if "return_response=True" not in str(err):
                raise
            _LOGGER.debug(
                (
                    "Notify service %s does not support return responses; "
                    "sending without response payload"
                ),
                self._notify_service,
            )
            await self._hass.services.async_call(
                domain,
                service,
                service_data,
                blocking=True,
            )
            return None
        message_id = _extract_message_id_from_response(response)
        _LOGGER.debug(
            "Notify response for target=%s extracted message_id=%s raw_response=%s",
            target,
            message_id,
            response,
        )
        return message_id

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

    async def _find_edit_candidate_from_recent_messages(
        self,
        *,
        target: str,
        item: Mapping[str, Any],
        now_ts: int,
    ) -> str | None:
        """Find a recent same-day bot message id by reading channel history."""
        recent_messages = await self._list_recent_messages(
            target=target,
            limit=50,
            from_me=True,
        )
        for message in reversed(recent_messages):
            if not _is_from_me(message):
                continue
            body = str(message.get("body") or "")
            if not _message_matches_item_day(body, item):
                continue
            msg_ts = _message_timestamp(message)
            if msg_ts is None:
                continue
            if now_ts - msg_ts > self._edit_window_minutes * 60:
                continue
            msg_id = str(message.get("id") or "")
            if msg_id:
                return msg_id
        return None

    async def _find_recent_message_id_for_body(
        self,
        *,
        target: str,
        body: str,
        now_ts: int,
    ) -> str | None:
        """Recover newly sent message id via history when notify returns none."""
        recent_messages = await self._list_recent_messages(
            target=target,
            limit=30,
            from_me=True,
        )
        normalized_body = body.strip()
        for msg in reversed(recent_messages):
            if not _is_from_me(msg):
                continue
            msg_id = str(msg.get("id") or "")
            if not msg_id:
                continue
            msg_body = str(msg.get("body") or "").strip()
            if msg_body != normalized_body:
                continue
            msg_ts = _message_timestamp(msg)
            if msg_ts is not None and abs(now_ts - msg_ts) > 300:
                continue
            return msg_id
        return None

    async def _list_recent_messages(
        self,
        *,
        target: str,
        limit: int,
        from_me: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Read channel history through whatsappur/whatsapper list service."""
        if "." not in self._notify_service:
            return []
        _, notify_service_name = self._notify_service.split(".", 1)
        channel_domain = notify_service_name
        if not self._hass.services.has_service(channel_domain, "channel_msg_list"):
            return []
        request_data: dict[str, Any] = {"target": target, "limit": limit}
        if from_me is not None:
            request_data["from_me"] = from_me
        try:
            response = await self._hass.services.async_call(
                channel_domain,
                "channel_msg_list",
                request_data,
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Unable to fetch recent messages via %s.channel_msg_list: %s",
                channel_domain,
                err,
            )
            return []

        if not isinstance(response, Mapping):
            return []
        messages = response.get("messages")
        if isinstance(messages, list):
            return [m for m in messages if isinstance(m, dict)]
        return []

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


def _summarize_payload(body: Mapping[str, Any]) -> dict[str, Any]:
    """Build a compact response summary for debug logging."""
    summary: dict[str, Any] = {"groups": {}}
    for group_name, items in body.items():
        if group_name == "SquashM8":
            continue
        if not isinstance(items, list):
            summary["groups"][group_name] = {
                "type": type(items).__name__,
            }
            continue
        sentence_count = 0
        update_count = 0
        for item in items:
            if not isinstance(item, Mapping):
                continue
            if item.get("sentence"):
                sentence_count += 1
            if item.get("update"):
                update_count += 1
        summary["groups"][group_name] = {
            "items": len(items),
            "with_sentence": sentence_count,
            "with_update": update_count,
        }
    return summary


def _preview_sentence(value: str, max_len: int = 120) -> str:
    """Return single-line preview of a message body for logs."""
    normalized = " ".join(value.split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3] + "..."


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


def _message_matches_item_day(message_body: str, item: Mapping[str, Any]) -> bool:
    """Best-effort day matching between endpoint payload item and sent message body."""
    normalized_body = message_body.strip()
    if not normalized_body:
        return False

    day = item.get("day")
    if isinstance(day, str) and day.strip() and day.strip() in normalized_body:
        return True

    day_col_key = item.get("dayColKey")
    if (
        isinstance(day_col_key, str)
        and day_col_key.strip()
        and day_col_key.strip() in normalized_body
    ):
        return True

    return False


def _extract_update_marker(item: Mapping[str, Any]) -> str | None:
    """Extract a stable update marker per day entry from upstream payload."""
    raw_update = item.get("update")
    if isinstance(raw_update, str):
        normalized = raw_update.strip()
        return normalized if normalized else None

    # Some payload shapes expose update as boolean/integer signal only.
    # Fall back to sentence text as marker so changed content still diffs.
    if isinstance(raw_update, bool) or isinstance(raw_update, int):
        if not bool(raw_update):
            return None
        sentence = item.get("sentence")
        if isinstance(sentence, str):
            normalized_sentence = sentence.strip()
            if normalized_sentence:
                return normalized_sentence
        return str(raw_update)

    if raw_update is None:
        return None
    normalized_fallback = str(raw_update).strip()
    return normalized_fallback if normalized_fallback else None


def _item_marked_updated(item: Mapping[str, Any]) -> bool:
    """Backward-compatible helper to indicate whether an item has update signal."""
    if _extract_update_marker(item):
        return True
    raw_update = item.get("update")
    if isinstance(raw_update, bool):
        return raw_update
    if isinstance(raw_update, int):
        return raw_update != 0
    if isinstance(raw_update, str):
        normalized = raw_update.strip().lower()
        if not normalized:
            return False
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        # Server-side delta currently uses non-empty strings to indicate updates.
        return True
    return False


