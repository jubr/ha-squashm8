"""Lightweight state store for per-day message tracking."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_STATE_KEY = "day_message_state"


class DayMessageStateStore:
    """Track the latest message id/timestamp by target + day key."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize in-memory state store scoped to this integration."""
        domain_data = hass.data.setdefault(DOMAIN, {})
        self._state: dict[str, dict[str, Any]] = domain_data.setdefault(_STATE_KEY, {})

    @staticmethod
    def _key(*, target: str, day_key: str) -> str:
        return f"{target}::{day_key}"

    def get_message_id(self, *, target: str, day_key: str) -> str | None:
        """Get tracked message id for target/day."""
        entry = self._state.get(self._key(target=target, day_key=day_key), {})
        message_id = str(entry.get("message_id") or "")
        return message_id if message_id else None

    def get_timestamp(self, *, target: str, day_key: str) -> int | None:
        """Get tracked timestamp for target/day."""
        entry = self._state.get(self._key(target=target, day_key=day_key), {})
        raw = entry.get("timestamp")
        try:
            timestamp = int(raw)
        except (TypeError, ValueError):
            return None
        return timestamp if timestamp > 0 else None

    def get_body(self, *, target: str, day_key: str) -> str | None:
        """Get last tracked message body for target/day."""
        entry = self._state.get(self._key(target=target, day_key=day_key), {})
        value = entry.get("body")
        if isinstance(value, str):
            normalized = value.strip()
            return normalized if normalized else None
        return None

    def set_message_id(
        self,
        *,
        target: str,
        day_key: str,
        message_id: str,
        timestamp: int,
        body: str | None = None,
    ) -> None:
        """Track message id + timestamp for target/day."""
        payload: dict[str, Any] = {
            "message_id": message_id,
            "timestamp": int(timestamp),
        }
        if body:
            payload["body"] = body
        self._state[self._key(target=target, day_key=day_key)] = payload

    def set_message_observation(
        self,
        *,
        target: str,
        day_key: str,
        timestamp: int,
        body: str | None = None,
    ) -> None:
        """Track timestamp/body even when provider message id is unavailable."""
        payload: dict[str, Any] = {
            "timestamp": int(timestamp),
        }
        if body:
            payload["body"] = body
        self._state[self._key(target=target, day_key=day_key)] = payload

