#!/bin/bash
# NOTE (public repo): the socat forwarder below bridges this host to the
# Mosquitto broker over the egress proxy. Set MQTT_BROKER_HOST to your
# broker's LAN address (default 192.168.1.25). If you run the listener
# on the same host as Mosquitto, point it at 127.0.0.1:1883 instead
# and drop the forwarder entirely.
# Porch face-listener watchdog — run every 5 min by cron.
# Ensures the MQTT socat forwarder (127.0.0.1:11883) and the face
# listener (porch_face_listener.py) are running; starts them if not.
# Both are long-running background processes that die on VM replacement,
# so this watchdog restores them. Logs to /tmp/porch-watchdog.log.
LOG=/tmp/porch-watchdog.log
echo "[$(date -Is)] watchdog check" >> "$LOG"

# 1. MQTT forwarder: is 127.0.0.1:11883 listening?
if ! timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/11883' 2>/dev/null; then
  echo "[$(date -Is)] forwarder down — restarting socat" >> "$LOG"
  proxy_auth="${HTTPS_PROXY#*://}"; proxy_auth="${proxy_auth%%@*}"
  setsid nohup socat TCP-LISTEN:11883,fork,bind=127.0.0.1 \
    PROXY:hatch-egress-proxy:${MQTT_BROKER_HOST:-192.168.1.25}:1883,proxyport=3130,proxyauth="$proxy_auth" \
    >> "$LOG" 2>&1 < /dev/null &
  sleep 2
  if timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/11883' 2>/dev/null; then
    echo "[$(date -Is)] forwarder back up" >> "$LOG"
  else
    echo "[$(date -Is)] forwarder FAILED to start" >> "$LOG"
  fi
fi

# 2. Face listener: is the process running?
# NOTE: match the FULL command line (python3 + script path). A bare
# "porch_face_listener.py" pattern self-matches any shell whose command
# line merely mentions that name (e.g. the watchdog's own caller), so the
# listener looked "up" when it was actually down.
LISTENER_CMD="python3 /home/hatch/workspace/scripts/porch_face_listener.py"
if ! pgrep -f "$LISTENER_CMD" >/dev/null 2>&1; then
  echo "[$(date -Is)] listener down — restarting" >> "$LOG"
  setsid nohup python3 /home/hatch/workspace/scripts/porch_face_listener.py \
    >> /tmp/porch-face-listener.log 2>&1 < /dev/null &
  sleep 3
  if pgrep -f "$LISTENER_CMD" >/dev/null 2>&1; then
    echo "[$(date -Is)] listener back up" >> "$LOG"
  else
    echo "[$(date -Is)] listener FAILED to start" >> "$LOG"
  fi
fi
