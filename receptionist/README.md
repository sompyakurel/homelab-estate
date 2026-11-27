# AI receptionist

A stranger at the door hears Alexa ask what they need. The porch
camera's microphone records, Whisper transcribes locally, Gemini
answers, and Alexa speaks the reply. Up to 3 exchanges per visit.

## Files

- `receptionist.py` — the service. Listens on MQTT, records 12 s of
  audio from the C120 RTSP stream on a start signal, transcribes with
  faster-whisper (small model), asks Gemini, publishes the reply.
- `receptionist.service` — systemd unit (`Restart=always`). Logs to
  `/tmp/receptionist.log`.

## Guardrails (tested)

- Never reveal who is home or who lives here.
- Never open the door for anyone — packages stay at the door.
- Refuses bathroom-entry, sales pitches, and "is anyone home?" probes.
- Test mode: publish text to `porch/receptionist/test` and the service
  treats it as a transcription (no porch trip needed).

## Model

Gemini `gemini-3.5-flash-lite` (the only model that answered for a new
API key — the 2.0/2.5 families return 404 retired, 3.8-flash 503s).
Key in `/root/.gemini-api-key` (chmod 600) on CT 105.

## Known flaw

Fixed 12 s recording windows — misses slow responders, truncates long
talkers, and the mic isn't continuously listening. The proper fix is
Voice Activity Detection (Silero VAD) + empty-transcription handling.
Decision: test live first; rebuild with VAD only if real usage shows
the flaws matter.

## MQTT topics (broker: localhost:1883 on CT 105)

- `porch/receptionist/start` — HA publishes this when a stranger is
  detected (opener already spoken by Alexa).
- `porch/receptionist/reply` — service publishes the LLM reply; HA
  speaks it.
- `porch/receptionist/done` — service publishes when the conversation
  ends (3 exchanges or goodbye).
- `porch/receptionist/test` — text test mode.
