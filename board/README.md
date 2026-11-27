# Memory Wall / Who's Here board

When a recognised family member arrives, build a board from their
Immich photos and show it on the Echo Show 11 (video), the bedroom TV
(GIF), and the phone (notification). Family-only — strangers never get
a board.

## Files

- `porch_board.py` — renders the 1280x800 board image/GIF. 8 photos
  per person, randomly sampled from a pool of 100. Photos are fitted
  whole inside the photo box (fit-inside, no crop) over a blurred
  darkened copy — centre-cropping chopped heads off, so it was
  replaced with fit-inside.
- `porch_show_board.py` — the driver: picks photos from Immich,
  renders the board, uploads it to the backend, sends the phone
  notification, announces via Voice Monkey to the Echo Show 11, and
  shows it on the bedroom TV via webOS. Sends the MP4, waits 90 s,
  then sends a static GIF hold (the Show drops video after ~1-2 min
  but holds a static image reliably).
- `porch_face_listener.py` — subscribes to
  `frigate/tracked_object_update`, debounced to once per 2 min per
  person, score > 0.7, porch camera only.
- `porch-face-listener.service` — systemd user unit for the listener.
- `porch_watchdog.sh` — cron every 5 min; restarts the MQTT forwarder
  and the listener if either died (both die on VM replacement).

## Config

Hosts and key files come from environment variables (see
`../.env.example`): `HA_HOST`, `IMMICH_HOST`, `BOARD_BACKEND`,
plus key files `~/.ha-token`, `~/.immich-board-key`,
`~/.voicemonkey-token`, `~/.voicemonkey-device` (all chmod 600).

Immich person names are mapped in `porch_show_board.py`
(`IMMICH_NAME_MAP`): porch names Som/Mom/Sami map to Immich people.

## Hosting

Board files are hosted on the backend (`POST /board/upload`, Bearer
token) — remote-storage uploads triggered a per-upload approval card,
which broke the automation. The POST endpoint must be defined BEFORE
the StaticFiles mount in the backend, or POST returns 405.

## Quota

Voice Monkey free plan: 200 requests/month. Each arrival costs 2
(video + delayed GIF hold). ~5 arrivals/day is ~300/month — watch
usage or the Show leg goes silent mid-month with no alert.
