#!/usr/bin/env python3
"""Durable MQTT helper for the Muse VM.

Uses paho-mqtt installed into /home/hatch/mqtt-libs, which survives VM
replacement — /usr/bin installs (mosquitto-clients) do NOT; they vanished
between the 09:24 and 11:00 runs on 2026-11-25 and would have broken the
morning-briefing assembler.

Usage:
  mqtt_pub.py pub <topic> <payload> [retain]
  mqtt_pub.py sub <topic>   (prints one retained message, then exits)

Connects to the local socat forwarder on 127.0.0.1:11883 — the caller must
have started it first (see the assembler cron body for the pattern).
"""
import os, sys, time
sys.path.insert(0, os.path.expanduser('~/mqtt-libs'))
import paho.mqtt.client as mqtt


def _client():
    connected = []

    def on_connect(client, userdata, flags, rc):
        connected.append(rc == 0)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    c.on_connect = on_connect
    c.connect('127.0.0.1', 11883, 60)
    c.loop_start()
    for _ in range(100):
        if connected:
            break
        time.sleep(0.1)
    if not connected or not connected[0]:
        print('FAILED to connect to local forwarder', file=sys.stderr)
        sys.exit(1)
    return c


if sys.argv[1] == 'pub':
    topic, payload = sys.argv[2], sys.argv[3]
    retain = len(sys.argv) > 4 and sys.argv[4] == 'retain'
    c = _client()
    c.publish(topic, payload, retain=retain)
    time.sleep(0.5)
    c.loop_stop()
    c.disconnect()
    print('published', topic, '=', payload, '(retained)' if retain else '')
elif sys.argv[1] == 'sub':
    topic = sys.argv[2]
    got = []

    def on_message(client, userdata, msg):
        got.append(msg.payload.decode())

    c = _client()
    c.on_message = on_message
    c.subscribe(topic)
    for _ in range(100):
        if got:
            break
        time.sleep(0.1)
    c.loop_stop()
    c.disconnect()
    print(got[0] if got else 'NO MESSAGE')
