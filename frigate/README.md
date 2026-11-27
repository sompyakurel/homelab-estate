# Frigate

Frigate config and Docker Compose for the porch + garage cameras.
Runs on CT 105 (192.168.1.25), UI at https://192.168.1.25:8971
(password-protected; port 5000 is NOT published).

## Files

- `config.yml` — the live config from `/opt/frigate/config/config.yml`
  on CT 105. **Sanitized:** camera and NVR credentials are `${VAR}`
  placeholders (see `../.env.example`) — the live file has the real
  passwords in the RTSP URLs. Header comment updated (the live file
  still says "0.16" and "placeholders until the C120 arrives").
- `docker-compose.yml` — the live compose from `/opt/frigate/`
  (Frigate 0.18.3, Mosquitto 2). No secrets in it.

## Key config

- Cameras: `porch` (Tapo C120, RTSP via go2rtc), `garage` (NVR
  channel 3, RTSP). Detect 1280x720, 10 fps, OpenVINO on the iGPU
  (compose service needs `group_add: ["993", "44"]` — device nodes
  visible in Docker are not usable without those groups).
- Zones: `approach` and `doorstep` on the porch camera; `driveway`
  on the garage camera (right edge excludes the parked car).
- Face recognition: `model_size: large`, lists Som/Mom/Sami, score
  threshold 0.7 for automations (Frigate stamps events above 0.9).
- Package classifier: local MobileNetV2 state model `porch_packages`
  (`package_present` / `clear` / `door opening`), crop tight around
  the doorstep.
- Record/snapshot retain 14 days.
