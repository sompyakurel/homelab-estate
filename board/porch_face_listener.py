#!/usr/bin/env python3
"""Watch Frigate face-recognition MQTT events and show the Memory Wall /
Who's Here board on the Echo Show 11 when a known person arrives.

Subscribes to frigate/tracked_object_update. On a face event for
Som/Mom/Sami (camera porch, score > 0.7) it runs porch_show_board.py
for that person, debounced to at most once per 2 minutes per person.

Run as a systemd user service (see porch-face-listener.service) or
directly for testing:
  python3 porch_face_listener.py

MQTT: connects to the local Mosquitto via the socat forwarder on
127.0.0.1:11883 (start it first, see mqtt_pub.py header). Uses paho-mqtt
from /home/hatch/mqtt-libs.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, "/home/hatch/mqtt-libs")

import paho.mqtt.client as mqtt

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 11883
TOPIC = "frigate/tracked_object_update"
KNOWN = {"Som", "Mom", "Sami"}
SCORE_MIN = 0.7
COOLDOWN_S = 120

last_shown = {}  # name -> epoch of last board shown


def show_board(name):
    now = time.time()
    if now - last_shown.get(name, 0) < COOLDOWN_S:
        print(f"skip {name}: cooldown ({int(now - last_shown[name])}s since last)", flush=True)
        return
    last_shown[name] = now
    print(f"face recognised: {name} — showing board", flush=True)
    try:
        r = subprocess.run(
            [sys.executable, os.path.expanduser("~/workspace/scripts/porch_show_board.py"),
             "--name", name],
            capture_output=True, text=True, timeout=180,
        )
        print(r.stdout, flush=True)
        if r.stderr:
            print("stderr:", r.stderr, flush=True)
    except Exception as e:
        print(f"show_board failed for {name}: {e}", flush=True)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        return
    if payload.get("type") != "face":
        return
    if payload.get("camera") != "porch":
        return
    name = payload.get("name")
    score = payload.get("score", 0)
    if name in KNOWN and score and score > SCORE_MIN:
        show_board(name)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT, 60)
    client.subscribe(TOPIC)
    print(f"listening on {TOPIC} (broker {BROKER_HOST}:{BROKER_PORT})", flush=True)
    client.loop_forever()


if __name__ == "__main__":
    main()
