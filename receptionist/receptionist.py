#!/usr/bin/env python3
"""AI receptionist service for the porch (Option 1).

Runs on CT 105 (Frigate box). Listens on MQTT for a start signal from
Home Assistant, then: records audio from the C120 RTSP stream,
transcribes it with faster-whisper (small model), sends the text to
Google Gemini 2.0 Flash, and publishes the reply back to MQTT for HA
to speak via Alexa. Loops for up to 2 more exchanges if the stranger
keeps talking, then ends.

MQTT topics (broker: localhost:1883, the Frigate Mosquitto):
  porch/receptionist/start  - HA publishes (any payload) to start a
                              conversation. Sent after HA speaks the
                              opener on the porch Dot.
  porch/receptionist/reply  - Service publishes the LLM reply text here.
                              HA speaks it via Alexa Media Player.
  porch/receptionist/done   - Service publishes "done" when the
                              conversation ends (so HA can reset state).
  porch/receptionist/test   - TEST ONLY: publish a text line here and the
                              service treats it as if Whisper had just
                              transcribed it from the porch mic, then
                              calls Gemini and publishes the reply. Lets
                              Som test the Gemini + reply chain by typing
                              instead of walking to the porch.

Files:
  /root/.gemini-api-key     - Gemini API key (chmod 600), one line.
  /opt/frigate/config/config.yml - C120 RTSP URL (go2rtc porch stream).

Run: /opt/whisper-venv/bin/python /opt/receptionist/receptionist.py
  (runs in the foreground; use nohup or a systemd unit to keep it up)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, "/opt/whisper-venv/lib/python3.13/site-packages")

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
TOPIC_START = "porch/receptionist/start"
TOPIC_REPLY = "porch/receptionist/reply"
TOPIC_DONE = "porch/receptionist/done"
TOPIC_TEST = "porch/receptionist/test"

GEMINI_KEY_FILE = "/root/.gemini-api-key"
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL + ":generateContent"
)

# Seconds to wait after the start signal before recording (lets the
# stranger start talking after the opener finishes).
WAIT_AFTER_START = 5
# Seconds of audio to record per exchange.
RECORD_SECONDS = 12
# Max exchanges per conversation (initial + follow-ups).
MAX_EXCHANGES = 3
# Seconds to wait after publishing a reply before listening again
# (reply spoken aloud + stranger responds).
WAIT_AFTER_REPLY = 8

SYSTEM_PROMPT = """You are a polite porch assistant speaking to a stranger at the front door of a family home. You reply in short spoken sentences (1-2 sentences max) because your words are read aloud by a speaker.

Rules you must always follow:
- Never say who lives here, their names, or whether anyone is home.
- Never agree to open the door, let anyone in, or unlock anything.
- Never give out addresses, phone numbers, schedules, or any household detail.
- If they ask who lives here, if someone is home, or to be let in, refuse politely without confirming or denying anything.
- Delivery driver: tell them to leave the package by the door and thank them.
- Solicitor or salesperson: politely say not interested and thank them.
- Wrong address: tell them they have the wrong house.
- If you cannot understand what they said, ask them to repeat it briefly.
- If they are rude or threatening, stay calm, say you cannot help, and end the conversation.
- Do not make up facts about the household. If you do not know, say you cannot help with that.
- Keep every reply to 1-2 short sentences.
"""


def gemini_key():
    with open(GEMINI_KEY_FILE) as f:
        return f.read().strip()


def c120_rtsp_url():
    cfg = open("/opt/frigate/config/config.yml").read()
    m = re.search(r"porch:\s*\n\s*-\s*(rtsp://[^\s]+)", cfg)
    if not m:
        raise RuntimeError("no C120 RTSP URL found in Frigate go2rtc config")
    return m.group(1)


def record_audio(url, seconds, out_path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", url, "-t", str(seconds),
         "-vn", "-ac", "1", "-ar", "16000", out_path],
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-500:])


def transcribe(model, wav_path):
    segments, info = model.transcribe(wav_path, language="en")
    text = " ".join(s.text.strip() for s in segments)
    return text


def ask_gemini(api_key, history):
    """history: list of {"role": "user"/"model", "parts": [{"text": ...}]}.
    Returns the reply text. Retries transient errors (503/429/500 and
    read timeouts) up to 3 times with a short delay, since the free
    tier can be briefly busy or slow to respond."""
    import socket
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": history,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 150},
    }).encode()
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(GEMINI_URL, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("x-goog-api-key", api_key)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503) and attempt < 2:
                print("Gemini %s, retrying (%d/3)..." % (e.code, attempt + 1), flush=True)
                time.sleep(2)
                continue
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            last_err = e
            if attempt < 2:
                print("Gemini timeout (%s), retrying (%d/3)..." % (e, attempt + 1), flush=True)
                time.sleep(2)
                continue
            raise
        except (KeyError, IndexError):
            raise RuntimeError("Gemini unexpected response: " + json.dumps(data)[:500])
    raise last_err


def main():
    import threading
    import paho.mqtt.client as mqtt
    from faster_whisper import WhisperModel

    api_key = gemini_key()
    rtsp_url = c120_rtsp_url()
    print("Receptionist starting. Loading Whisper small model...", flush=True)
    model = WhisperModel("small", device="cpu", compute_type="int8")
    print("Model loaded. Connecting to MQTT %s:%d..." % (MQTT_BROKER, MQTT_PORT), flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    def publish(topic, payload):
        """Publish and confirm it went out. Returns True on success."""
        info = client.publish(topic, payload, retain=False)
        info.wait_for_publish(timeout=10)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            print("Publish to %s failed (rc=%s), retrying..." % (topic, info.rc), flush=True)
            try:
                client.reconnect()
            except Exception as e:
                print("Reconnect failed: %s" % e, flush=True)
                return False
            info = client.publish(topic, payload, retain=False)
            info.wait_for_publish(timeout=10)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                print("Publish to %s failed again (rc=%s), giving up." % (topic, info.rc), flush=True)
                return False
        return True

    def handle_conversation():
        history = []
        for exchange in range(MAX_EXCHANGES):
            if exchange == 0:
                time.sleep(WAIT_AFTER_START)
            else:
                time.sleep(WAIT_AFTER_REPLY)
            wav = os.path.join(tempfile.gettempdir(), "receptionist.wav")
            print("Exchange %d: recording %ds..." % (exchange + 1, RECORD_SECONDS), flush=True)
            try:
                record_audio(rtsp_url, RECORD_SECONDS, wav)
            except Exception as e:
                print("Record failed: %s" % e, flush=True)
                break
            text = transcribe(model, wav)
            print("Heard: %r" % text, flush=True)
            if not text or len(text.strip()) < 3:
                print("No speech detected, ending conversation.", flush=True)
                break
            history.append({"role": "user", "parts": [{"text": text}]})
            try:
                reply = ask_gemini(api_key, history)
            except Exception as e:
                print("Gemini failed: %s" % e, flush=True)
                reply = "Sorry, I did not catch that. Could you repeat it?"
            print("Reply: %r" % reply, flush=True)
            history.append({"role": "model", "parts": [{"text": reply}]})
            if publish(TOPIC_REPLY, reply):
                print("Reply published to %s." % TOPIC_REPLY, flush=True)
            if exchange == MAX_EXCHANGES - 1:
                print("Max exchanges reached, ending conversation.", flush=True)
        publish(TOPIC_DONE, "done")
        print("Conversation done.", flush=True)

    busy = {"v": False}

    def handle_test_text(text):
        """Test path: treat `text` as an already-transcribed porch line,
        ask Gemini, and publish the reply. No recording, no Whisper."""
        print("Test text received: %r" % text, flush=True)
        history = [{"role": "user", "parts": [{"text": text}]}]
        try:
            reply = ask_gemini(api_key, history)
        except Exception as e:
            print("Gemini failed: %s" % e, flush=True)
            reply = "Sorry, I did not catch that. Could you repeat it?"
        print("Reply: %r" % reply, flush=True)
        if publish(TOPIC_REPLY, reply):
            print("Reply published to %s." % TOPIC_REPLY, flush=True)

    def on_connect(_client, _userdata, _flags, rc, _props=None):
        if rc == 0:
            client.subscribe(TOPIC_START)
            client.subscribe(TOPIC_TEST)
            print("MQTT connected, subscribed to %s and %s." % (TOPIC_START, TOPIC_TEST), flush=True)
        else:
            print("MQTT connect failed (rc=%s)." % rc, flush=True)

    def on_message(_client, _userdata, msg):
        if msg.topic == TOPIC_TEST:
            text = msg.payload.decode("utf-8", errors="replace").strip()
            if not text:
                return
            threading.Thread(target=handle_test_text, args=(text,), daemon=True).start()
            return
        if msg.topic != TOPIC_START:
            return
        if busy["v"]:
            print("Start received while busy, ignoring.", flush=True)
            return
        busy["v"] = True

        def run():
            try:
                handle_conversation()
            except Exception as e:
                import traceback
                print("Conversation thread crashed: %s" % e, flush=True)
                traceback.print_exc()
            finally:
                busy["v"] = False

        # Run the conversation on its own thread. If it ran inside this
        # callback, the MQTT network loop would stall for the whole
        # (60s+) conversation, the broker would drop us for missing
        # keepalives, and the reply publish would silently fail.
        threading.Thread(target=run, daemon=True).start()

    client.on_connect = on_connect
    client.on_message = on_message
    client.loop_forever()


if __name__ == "__main__":
    main()
