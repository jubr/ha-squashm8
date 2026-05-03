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
- `dry_run` (bool): simulate send/edit/delete without mutating WhatsApp messages

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

## No-feature-flag message lifecycle behavior

This integration now directly uses the latest Whatsapper notify contract from
`docs/homeassistant-integration.md` and applies edit/delete lifecycle management
without feature flags.

### Required Whatsapper capabilities (already documented in latest PR)

- `notify.whatsapper` / `notify.whatsappur` supports:
  - `data.edit_message_id`
  - `data.delete_message_id`
  - `data.delete_for_everyone`
- Add-on HTTP endpoints:
  - `POST /api/v1/messages/edit`
  - `POST /api/v1/messages/delete`
- The integration tracks per-target/day bot message history in HA storage and
  relies on Whatsapper notify edit/delete routing for mutation.

### Automatic behavior for each outgoing day update

1. Fetch recent messages for the target chat and parse entries.
2. Find recent bot-owned message for same logical day (`dayColKey`/`day`) in the
   configured edit window.
3. If found, edit that message using `data.edit_message_id` instead of sending a
   new message.
4. If no editable candidate is found, send a new message and record its id.
5. Attempt cleanup of stale bot messages for the same day:
   - only when no non-bot messages are between stale message and current message
   - delete uses `data.delete_message_id` + `data.delete_for_everyone: true`
6. Any edit/delete failure falls back safely to keep notification delivery.

