# Agent Runbook: Deploy Procedure

This repository is deployed to Home Assistant through HACS.

## 1) Source control flow

1. Create a feature branch from `main`.
2. Commit and push changes.
3. Open a PR and merge into `main`.
4. Do **not** manually bump `manifest.json` for normal releases.
   - Version bumps/tags are created by the repository automation after merge.

## 2) Release and install options

Use one of these deploy paths in HACS:

- **Normal release path (preferred):**
  - Wait for the automated release/tag from the merge workflow.
  - Install the latest release in HACS.

- **Fast test path (commit pin):**
  - Install a specific commit hash in HACS for rapid validation.
  - Later move back to the latest tagged release.

## 3) Home Assistant activation steps

After HACS installs an integration update:

1. Run `ha_check_config`.
2. If HACS reports `pending-restart`, restart Home Assistant (`ha_restart`).
3. After restart, or for lightweight reload loops, reload the SquashM8 config entry:
   - `homeassistant.reload_config_entry` with the SquashM8 `entry_id`.

Notes:
- Core reload (`ha_reload_core`) can refresh many HA resources but does not replace a full restart when HACS marks the integration as pending restart.
- For Python code updates in custom components, restart is the safest activation step.

## 4) Post-deploy validation

Run a dry-run service call first:

- `squashm8.run` with:
  - `peek: false`
  - `dry_run: true`
  - `delta: true` (changed-only verification) or `delta: false` (all entries verification)

Then run a real call (`dry_run: false`) if needed, and confirm response fields:
- `status`
- `sent_messages`
- `edited_messages`
- `skipped_reasons`
- `num_updates`

