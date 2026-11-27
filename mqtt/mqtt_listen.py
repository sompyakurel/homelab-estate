#!/usr/bin/env python3
"""Listen on MQTT topics for a fixed window and summarise what flows.

Usage: LISTEN_SECS=30 python3 mqtt_listen.py <topic> [<topic> ...]
Connects to the local socat forwarder on 127.0.0.1:11883 — the caller must
have started it first. Prints per-topic counts plus a readable digest of
Frigate stats / tracked-object / event messages.
"""
import os, sys, time, json
sys.path.insert(0, os.path.expanduser('~/mqtt-libs'))
import paho.mqtt.client as mqtt

duration = float(os.environ.get('LISTEN_SECS', '30'))
topics = sys.argv[1:] or ['frigate/#']
msgs = []

def on_connect(client, userdata, flags, rc):
    for t in topics:
        client.subscribe(t)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        payload = msg.payload.decode()[:200]
    msgs.append((time.time(), msg.topic, payload))

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
client.on_connect = on_connect
client.on_message = on_message
client.connect('127.0.0.1', 11883, 60)
client.loop_start()
time.sleep(duration)
client.loop_stop()
client.disconnect()

from collections import Counter
print('listened %.0fs, %d messages:' % (duration, len(msgs)))
print(Counter(t for _, t, _ in msgs))
for _, topic, p in msgs:
    if topic == 'frigate/stats' and isinstance(p, dict):
        porch = p.get('porch', {})
        print('STATS porch camera_fps=%s detection_fps=%s skipped_fps=%s detectors=%s' % (
            porch.get('camera_fps'), porch.get('detection_fps'),
            porch.get('skipped_fps'), json.dumps(p.get('detectors', {}))))
    elif topic == 'frigate/tracked_object_update' and isinstance(p, dict):
        print('TRACKED type=%s camera=%s name=%s score=%s id=%s' % (
            p.get('type'), p.get('camera'), p.get('name'), p.get('score'), p.get('id')))
    elif topic == 'frigate/events' and isinstance(p, dict):
        after = p.get('after') or {}
        dur = None
        if after.get('start_time') and after.get('end_time'):
            dur = round(after['end_time'] - after['start_time'], 1)
        print('EVENT type=%s label=%s sub_label=%s camera=%s duration=%s' % (
            p.get('type'), after.get('label'), after.get('sub_label'),
            after.get('camera'), dur))
    else:
        print(topic, ':', str(p)[:200])
