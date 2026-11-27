# Mosquitto

MQTT broker config for CT 105 (192.168.1.25:1883). Every component in
this repo talks through this one broker.

## Files (to be added from CT 105)

- `mosquitto.conf` — from `/opt/frigate/mosquitto/mosquitto.conf`
  (or wherever the compose file mounts it).

## Note

Anonymous access is currently allowed (deliberate decision — the
broker is LAN-only, no public ingress, and the password change touches
six components at once). If that ever changes, update Frigate, Home
Assistant, the receptionist, the face listener, the briefing publisher,
and the forwarder in the same pass, verifying each one connects.
