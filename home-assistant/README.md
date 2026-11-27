# Home Assistant automations

The automations that turn Frigate detections into porch behaviour.
Runs on CT 106 (192.168.1.26:8123), HA 2026.11.2.

## Files

- `automations.yaml` — all 16 automations, fetched live from CT 106
  via the REST API (see `fetch_ha_automations.py`). Re-run the script
  to refresh. No secrets in it (checked) — it references entity IDs,
  MQTT topics, and device names only. The front-door lock's HA device
  ID is the placeholder `YOUR_LOCK_DEVICE_ID` (an HA-internal UUID,
  not a credential — swapped out so the repo doesn't identify the
  lock); substitute your own lock's ID to use the file as-is.
- `fetch_ha_automations.py` — the fetcher. Reads the HA long-lived
  token from `~/.ha-token` and talks through the tunnel proxy. Set
  `LOCK_DEVICE_ID` in the environment to re-apply the device-ID
  placeholder on refresh.
- `configuration.yaml` — the live file from
  `/opt/homeassistant/config/configuration.yaml` on CT 106. It's the
  stock boilerplate (default_config, frontend themes, includes for
  automations/scripts/scenes) — no secrets, no MQTT/template config.

Two automations in the file are currently OFF and kept for reference:
`Garage motion announcement` (the killed C615F automation) and the
unnamed `New automation` (off since 2026-11-23).

## Automations

| Automation | What it does |
|---|---|
| Greeting | "Namaste, welcome home, {name}" for recognised family, 07:00–22:00, 2-min cooldown |
| Face unlock | Unlocks for Som/Mom/Sami, score > 0.7, only when locked, no hours limit, 1-min cooldown |
| Unknown person | Stranger announcement + snapshot + phone notify; suppressed if the door just moved (leaving) or the person is in the doorstep zone only |
| Package note | Fires on `porch_packages` classifier `clear → package_present` held 20 s; "Here goes my wallet again." |
| Receptionist start/reply | Drives the AI receptionist via MQTT |
| Driveway early warning | Zone occupancy (car or person) → snapshot + phone notify + Alexa announce |
| Porch daily digest | 23:00 — speaks tallies, sends them to the phone, saves to retained MQTT `porch/digest/last`, resets |
| Goodnight check | 22:00 — door lock + porch camera state |

## Notes

- An automation's entity_id comes from its ALIAS slug, not the config
  id (`porch_digest` loads as `automation.porch_daily_digest`).
- Alexa announcements use `notify.alexa_media` with `target` and
  `type: announce` both INSIDE `data:` — a top-level `target:` errors.
- `mqtt.publish` takes `payload`, not `payload_template`.
