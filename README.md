# SquashM8 Home Assistant Integration (HACS)

Custom integration that replaces the current `automation + script + rest_command` SquashM8 flow with a single HA service:

- `squashm8.run`

It keeps compatibility with your current behavior:

- `peek` (maps to SquashM8 endpoint `peek` query arg)
- `delta` (skip outbound messages when `numUpdates == 0`)
- `override_target` (force all messages to one logical group)
- same WhatsApp notify flow (`notify.whatsappur`)
- same default group mapping currently used in your automations

---

## Current live behavior reverse-engineered from HA traces

Your current hourly chain is:

1. `automation.squashm8_hourly_monday` (time_pattern trigger, hourly)
2. calls `script.squashm8_run` with:
   - `peek: false`
   - `delta: true`
   - `override_target: "SquashM8"`
3. script calls `rest_command.squashm8_get_messages` against:
   - `https://www.squashmatties.nl/SquashM8.php?squash=getGroupMessages&changeId=HomeAssistant&peek=0&ts=<epoch>`
4. parses payload groups (`Maandag squash`, `Squashmatties`, etc.)
5. sends each `sentence` to `notify.whatsappur` target mapping
6. if `numUpdates == 0` and delta-mode is active, no outbound posts

This integration preserves that behavior directly in Python.

---

## Installation via HACS (custom repository)

1. Push this repo to GitHub.
2. In HACS → Integrations → menu → Custom repositories:
   - URL: this repo URL
   - Category: Integration
3. Install **SquashM8**
4. Restart Home Assistant
5. Add integration in HA UI: **Settings → Devices & Services → Add Integration → SquashM8**

---

## Service

### `squashm8.run`

Optional fields:

- `entry_id` (string): choose specific config entry (if multiple)
- `peek` (bool)
- `delta` (bool)
- `override_target` (string)
- `ts` (int): optional epoch override (for replay/testing)

Service returns response data including:

- `status`
- `sent_messages`
- `num_updates`
- `endpoint_url`
- `skipped_reasons`

---

## Example automation replacing old hourly + script flow

```yaml
alias: SquashM8 Hourly
triggers:
  - trigger: time_pattern
    minutes: "0"
actions:
  - action: squashm8.run
    data:
      peek: false
      delta: true
      override_target: SquashM8
mode: single
```

---

## Configurability parity with existing setup

Config entry/options expose:

- API URL (`api_base_url`)
- change ID (`change_id`)
- notify service (`notify_service`)
- request timeout / SSL verification
- default values for:
  - `peek`
  - `delta`
  - `override_target`
- group target map (logical group name → WhatsApp chat id)

Default group target map is preloaded from your existing HA setup.

---

## Roadmap: message edit/delete strategy (future)

You asked for functionality to avoid noisy short-interval updates by editing same-day messages and optionally delete-for-everyone old bot messages when safe.

### Proposed integration-level feature flags

- `update_mode`: `send_new | try_edit_recent`
- `edit_window_minutes` (default e.g. 20)
- `same_day_only` (default true)
- `coalesce_when_short_interval` (default true)
- `delete_old_bot_messages` (default false)
- `delete_only_if_no_intervening_nonbot_messages` (default true)

### Needed Whatsapper API additions (likely in `jubr/whatsapper`)

Current notify API is send-only. For robust edit/delete semantics we likely need:

1. **List recent chat messages** endpoint, including:
   - message id
   - sender/self flag
   - timestamp
   - text snippet
2. **Edit message** endpoint:
   - target chat id
   - message id
   - new text
3. **Delete for everyone** endpoint:
   - target chat id
   - message id
   - mode (for_everyone)
4. Consistent error codes for:
   - edit window expired
   - message not owned by bot account
   - cannot delete-for-everyone

### Safe algorithm outline

For each outgoing day-group message:

1. Discover last bot-owned message for same `dayColKey` within `edit_window`.
2. If found and policy allows:
   - edit existing message instead of sending new
3. If sending new and delete policy enabled:
   - identify older bot messages for same day
   - ensure no non-bot messages between old and new
   - then delete-for-everyone old ones
4. Fallback: send as new message on any API limitation.

This can be added without breaking the current `squashm8.run` service contract by introducing optional strategy keys.

