# homelab-estate

Local-first smart-home automation for a single-family house — no cloud
dependency for the core loop. A Tapo camera watches the porch, Frigate
detects people and faces on-device (OpenVINO on the iGPU), and Home
Assistant turns those detections into greetings, door unlocks, package
notes, a stranger-intercom (AI receptionist), and a nightly digest.
Everything decision-critical runs on the LAN; the only cloud calls are
an optional LLM for the receptionist and Voice Monkey for Echo Show
announcements.

Built on a Proxmox homelab (see
[homelab-terraform](https://github.com/sompyakurel/homelab-terraform),
[homelab-ansible](https://github.com/sompyakurel/homelab-ansible),
[homelab-gitops](https://github.com/sompyakurel/homelab-gitops)).
This repo is the application layer that runs on top of that
infrastructure.

## Architecture

```
Tapo C120 (porch) ──RTSP──> Frigate (CT 105, OpenVINO/iGPU)
Tapo C120 (porch) ──RTSP──> Frigate ──MQTT──> Mosquitto (CT 105 :1883)
NVR ch3 (garage)  ──RTSP──> Frigate ──MQTT──> Mosquitto
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
              Home Assistant        Receptionist         Face listener
              (CT 106 :8123)        (CT 105)             (bridge VM)
              greeting/unlock       Whisper STT +        Frigate face events
              package note          Gemini LLM +         → Memory Wall board
              stranger alert        Alexa TTS            → Echo Show 11
              driveway warning                           → bedroom TV
              nightly digest                             → phone
                    │                     │                     │
                    └────────── Alexa (Media Player) ──────────┘
```

All state that matters is on the LAN. The house keeps working if the
internet goes down — the only things lost are the LLM replies and the
Echo Show video leg (the phone notification and TV legs keep working).

## Layout

| Directory | What it is | Runs on |
|---|---|---|
| `frigate/` | Frigate config (cameras, zones, face recognition, package classifier) + Docker Compose | CT 105 |
| `home-assistant/` | Automations (greeting, unlock, package note, stranger alert, driveway warning, digest, goodnight check) | CT 106 |
| `mosquitto/` | Mosquitto broker config | CT 105 |
| `receptionist/` | AI receptionist: Whisper STT + Gemini + Alexa TTS, MQTT-driven, systemd service | CT 105 |
| `watchman/` | Night-watchman health checker (15 estate checks, Resend mail on change, weekly heartbeat) | Proxmox host |
| `board/` | Memory Wall / Who's Here board: Immich photos → board image/video → Echo Show 11, TV, phone | Bridge VM |
| `mqtt/` | Small MQTT helpers (publish/subscribe/listen) | Bridge VM |

## The flows

**Arrival (recognised family).** Frigate matches a face (score > 0.7) →
MQTT `frigate/tracked_object_update` → the face listener builds a
Memory Wall board from 8 random Immich photos of that person → Echo
Show 11 plays it as video, the bedroom TV shows the GIF, the phone gets
a notification. Home Assistant speaks "Namaste, welcome home, {name}"
and unlocks the door for allowlisted people. No hours limit on unlock
(the household works till 1 AM).

**Package.** A local MobileNetV2 state classifier (`porch_packages`)
watches the doorstep crop. When it flips `clear → package_present`
and holds 20 s, Home Assistant announces "Here goes my wallet again.",
sends a doorstep snapshot to the phone, and increments the digest
delivery count. The 20 s hold + from-`clear` guard stop false positives
from someone standing in the doorway.

**Stranger.** An unrecognised person at the door gets the AI
receptionist: Alexa asks what they need, the C120 microphone records,
Whisper transcribes, Gemini answers under strict guardrails (never
reveal who is home, never open the door, packages stay at the door),
and Alexa speaks the reply. Up to 3 exchanges. Leaving-home is
suppressed (no greeting for someone walking out).

**Driveway.** A zone drawn across the driveway entrance (excluding the
parked car) drives occupancy sensors. A car or person entering fires an
early warning with a snapshot — earlier than the porch camera sees them.

**Nightly digest.** At 23:00 the tallies (visitors, strangers,
deliveries) are spoken, sent to the phone, saved to a retained MQTT
topic, then reset. A 22:00 goodnight check reports the door and camera
state.

## Design decisions

- **Local-first.** Detection, face recognition, and the package
  classifier all run on-device. The cloud is used only where it adds
  something local can't do (LLM conversation, Echo Show delivery).
- **MQTT as the bus.** Every component publishes/subscribes to one
  broker. Adding a new automation means subscribing to a topic, not
  rewiring anything.
- **No liveness detection (known limitation).** Frigate face
  recognition has no liveness check — a photo held up to the camera can
  fool it. Face unlock is convenience, not high security.
- **Secrets live in files, never in code.** API keys, tokens, and
  passwords are read from `chmod 600` files or environment variables
  (see `.env.example`). Nothing in this repo is a real credential.

## Setup

1. Copy `.env.example` to `.env` and fill in your hosts and key-file
   paths.
2. Deploy each directory to its host (see the per-directory README).
3. In the Tapo app, create a camera account for the RTSP/ONVIF stream
   before adding a camera to Frigate.
4. Run the watchman once by hand and confirm all checks are green.

## Status

Live since November 2026. Porch greeting/unlock, package note,
stranger alert, driveway warning, nightly digest, and the Memory Wall
board are all proven with real walk-tests. The receptionist is live
with text-tested guardrails; its first live stranger test is pending.
