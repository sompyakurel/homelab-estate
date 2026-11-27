# MQTT helpers

Small tools for working with the Mosquitto broker. They connect to the
local socat forwarder on 127.0.0.1:11883 (start it first — see
`board/porch_watchdog.sh` for the pattern). Uses paho-mqtt from
`/home/hatch/mqtt-libs` (a durable path — system installs like
mosquitto-clients vanish on VM replacement).

- `mqtt_pub.py pub <topic> <payload> [retain]` — publish one message.
- `mqtt_pub.py sub <topic>` — print one retained message, then exit.
- `mqtt_listen.py <topic>...` — listen for `LISTEN_SECS` (default 30)
  and summarise per-topic counts plus a digest of Frigate messages.
  Default topic is `frigate/#`.
