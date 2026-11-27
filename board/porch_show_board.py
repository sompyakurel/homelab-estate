#!/usr/bin/env python3
"""End-to-end driver for the Echo Show 11 Memory Wall / Who's Here board.

Given a recognised person's name, this script:
  1. Picks photos of them — up to 8 Immich memory photos when an Immich
     API key is configured (see ~/.immich-board-key), else the live porch
     snapshot from Home Assistant's camera.porch. (Rotating GIF, 8 photos
     ~3s each, is Som's ask 2026-11-26 — was 5, raised to 8.)
  2. Builds the 1280x800 board (porch_board.py) with today's
     porch-digest counts and the front-door state — an animated GIF when
     several photos are available, a plain JPEG when only one is.
  3. Uploads the board to the Ghar backend (/board/upload, public HTTPS
     URL). The backend hosts board files so the board fires automatically
     — remote-storage uploads trigger a per-upload approval card, which
     broke the automatic board (Som, 2026-11-26: "i had to approve to
     show myself"). Upload token in ~/.board-upload-token (chmod 600).
  4. Sends it to the Echo Show 11 via Voice Monkey (announce API with
     video + display_seconds) — PROVEN live 2026-11-26: one MP4 video,
     all 8 photos rotating inside it, ONE Voice Monkey request per
     arrival. The video loops to ~5 min; if the Show drops it early,
     that is accepted. TV + phone keep the rotating GIF. Needs a Voice
     Monkey Speaker linked to the Show by an Alexa Routine, token in
     ~/.voicemonkey-token and Speaker device id in ~/.voicemonkey-device
     (both chmod 600). The old HA play_media background attempt is dead
     and kept only as a harmless no-op.
  5. Opens the board on the bedroom TV's webOS browser via Home Assistant
     (webostv.command system.launcher/open) — the working TV display,
     proven 2026-11-26: the browser opens and shows the board image.

Usage:
  porch_show_board.py --name Som
  porch_show_board.py --name Mom --photo /path/to/photo.jpg   (override photo)

Immich key: put a read-only API key (asset.read + person.read + search)
on one line in ~/.immich-board-key (chmod 600). Without it, the live
porch snapshot is used as the photo.
Requires: HA token in ~/.ha-token, $HTTPS_PROXY set (tunnel proxy on 3130).
"""
import argparse
import base64
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.request

HA_HOST = os.environ.get("HA_HOST", "http://192.168.1.26:8123")
IMMICH_HOST = os.environ.get("IMMICH_HOST", "http://192.168.1.24:2283")
SHOW_ENTITY = "media_player.som_s_echo_show_11"
BEDROOM_TV_ENTITY = "media_player.bedroom_lg_webos_tv_qned85taa"
VOICEMONKEY_ANNOUNCE_URL = "https://api-v3.voicemonkey.io/announce"
# Voice Monkey Speaker for the Echo Show 11, created 2026-11-26 by Som
# ("Echo Show 11", device id echo-show-t32gg) and linked to the physical
# Show by an Alexa Routine. The announce API's `device` is the Speaker id,
# NOT the raw Echo id — the first test used the Echo id before the Speaker
# existed and the Show stayed silent despite an HTTP 200.
# Som named everyone in Immich with a "P" in front of their name, or with
# their first letter replaced by "P" (his joke, 2026-11-26). The porch
# recogniser uses plain names (Som/Mom/Sami), so map them to the Immich
# names here. "Mom" is "Ama" (mother) with a P in front.
IMMICH_NAME_MAP = {
    "som": "Psom",
    "mom": "Pama",
    "sami": "Pami",
}


def tunnel_proxy():
    https_proxy = os.environ.get("HTTPS_PROXY", "")
    # tunnel_proxy is "<scheme>://...:3130" minus the trailing path
    return https_proxy.rsplit(":", 1)[0] + ":3130" if https_proxy else ""


def ha_token():
    return open(os.path.expanduser("~/.ha-token")).read().strip()


def ha_get(path):
    proxy = tunnel_proxy()
    req = urllib.request.Request(HA_HOST + path)
    req.add_header("Authorization", "Bearer " + ha_token())
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else None
    )
    with opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode())


def ha_post_service(domain, service, payload):
    proxy = tunnel_proxy()
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{HA_HOST}/api/services/{domain}/{service}", data=data, method="POST"
    )
    req.add_header("Authorization", "Bearer " + ha_token())
    req.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else None
    )
    with opener.open(req, timeout=60) as r:
        return r.read().decode()


def immich_key():
    p = os.path.expanduser("~/.immich-board-key")
    if os.path.exists(p):
        return open(p).read().strip()
    return None


def immich_get(path, key):
    proxy = tunnel_proxy()
    req = urllib.request.Request(IMMICH_HOST + path)
    req.add_header("x-api-key", key)
    req.add_header("Accept", "application/json")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else None
    )
    with opener.open(req, timeout=30) as r:
        return r.read()


def pick_immich_photos(name, key, count=5):
    """Return a list of local paths of memory photos of `name` (up to `count`), or []."""
    # Map the porch name to the Immich name (P-prefix convention).
    immich_name = IMMICH_NAME_MAP.get(name.strip().lower(), name)
    try:
        data = json.loads(immich_get("/api/people", key).decode())
    except Exception as e:
        print(f"Immich people list failed: {e}", file=sys.stderr)
        return []
    # Immich v3 returns a paginated object {people: [...], total, ...};
    # older versions returned a bare list. Accept both.
    people = data.get("people", []) if isinstance(data, dict) else data
    person = None
    for p in people:
        if (p.get("name") or "").strip().lower() == immich_name.strip().lower():
            person = p
            break
    if not person:
        print(f"Immich: no person named {immich_name!r} (porch name {name!r})", file=sys.stderr)
        return []
    pid = person.get("id")
    # Randomise: fetch a pool of the person's assets, then sample 5 at
    # random — otherwise the board would always show the 5 most recent
    # photos (the search's default order), and the Memory Wall would look
    # the same every time. Som asked for random, 2026-11-26.
    try:
        body = json.dumps({"personIds": [pid], "size": 100}).encode()
        proxy = tunnel_proxy()
        req = urllib.request.Request(
            IMMICH_HOST + "/api/search/metadata", data=body, method="POST"
        )
        req.add_header("x-api-key", key)
        req.add_header("Content-Type", "application/json")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else None
        )
        with opener.open(req, timeout=30) as r:
            result = json.loads(r.read().decode())
    except Exception as e:
        print(f"Immich search failed: {e}", file=sys.stderr)
        return []
    assets = result.get("assets", {}).get("items", []) or result.get("assets", [])
    if not assets:
        print(f"Immich: no assets for {name!r}", file=sys.stderr)
        return []
    # Sample `count` at random from the pool (different set every run).
    chosen = random.sample(assets, min(count, len(assets)))
    paths = []
    for i, asset in enumerate(chosen):
        asset_id = asset.get("id")
        if not asset_id:
            continue
        try:
            data = immich_get(f"/api/assets/{asset_id}/thumbnail?size=preview", key)
        except Exception as e:
            print(f"Immich thumbnail {asset_id} failed: {e}", file=sys.stderr)
            continue
        path = os.path.join(tempfile.gettempdir(), f"immich-{name.lower()}-{i}.jpg")
        open(path, "wb").write(data)
        paths.append(path)
    print(f"Immich photos for {name}: {len(paths)} ({[os.path.basename(p) for p in paths]})")
    return paths


def porch_snapshot():
    proxy = tunnel_proxy()
    req = urllib.request.Request(HA_HOST + "/api/camera_proxy/camera.porch")
    req.add_header("Authorization", "Bearer " + ha_token())
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else None
    )
    with opener.open(req, timeout=30) as r:
        data = r.read()
    path = os.path.join(tempfile.gettempdir(), "porch_snap.jpg")
    open(path, "wb").write(data)
    return path


def build_board_video(name, photos, visitors, strangers, deliveries, door):
    """Build an MP4 of the board (one shot per photo, looped) for the Echo Show.

    One video = one Voice Monkey request, with all 8 photos rotating
    inside it (Som, 2026-11-26 — "still 8 pics one vid send like
    before"). The Show renders an animated GIF as a still, and rotating
    through separate still images would cost one request per photo, so
    the video is the only way to rotate on 1 request. The video loops
    the photo cycle to ~300s (5 min); if the Show drops it early, that
    is accepted — leave it (Som, 2026-11-26). Returns the MP4 path, or
    None on failure. (TV + phone keep the GIF — they animate it fine.)
    """
    frames = []
    for i, photo in enumerate(photos):
        out = os.path.join(tempfile.gettempdir(), f"porch-board-{name.lower()}-frame{i}.jpg")
        cmd = [
            sys.executable,
            os.path.expanduser("~/workspace/scripts/porch_board.py"),
            "--name", name,
            "--visitors", str(visitors), "--strangers", str(strangers),
            "--deliveries", str(deliveries), "--door", door,
            "--photo", photo, "--out", out,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except Exception as e:
            print(f"board video frame {i} failed: {e}", file=sys.stderr)
            return None
        frames.append(out)
    if not frames:
        return None
    mp4 = os.path.join(tempfile.gettempdir(), f"porch-board-{name.lower()}.mp4")
    concat = os.path.join(tempfile.gettempdir(), "porch-board-frames.txt")
    # 2s per photo, looped to ~300s (8 photos x 2s = 16s per cycle,
    # 19 cycles = ~304s). 960x600 + CRF 30 keeps the 5-min video small
    # (~6 MB) so it streams reliably on the Show.
    cycles = 19
    with open(concat, "w") as f:
        for _ in range(cycles):
            for fr in frames:
                f.write(f"file '{fr}'\nduration 2\n")
        f.write(f"file '{frames[-1]}'\n")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat,
            "-vf", "scale=960:600,format=yuv420p",
            "-c:v", "libx264", "-crf", "30", "-r", "15", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", mp4,
        ], check=True, capture_output=True, text=True)
    except Exception as e:
        print(f"board video ffmpeg failed: {e}", file=sys.stderr)
        return None
    return mp4


def build_board_frames(name, photos, visitors, strangers, deliveries, door):
    """Build one JPEG board frame per photo (for the Echo Show).

    (Kept for the single-image fallback; the normal path is the video.)
    """
    frames = []
    for i, photo in enumerate(photos):
        out = os.path.join(tempfile.gettempdir(), f"porch-board-{name.lower()}-frame{i}.jpg")
        cmd = [
            sys.executable,
            os.path.expanduser("~/workspace/scripts/porch_board.py"),
            "--name", name,
            "--visitors", str(visitors), "--strangers", str(strangers),
            "--deliveries", str(deliveries), "--door", door,
            "--photo", photo, "--out", out,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except Exception as e:
            print(f"board frame {i} failed: {e}", file=sys.stderr)
            return []
        frames.append(out)
    return frames


BOARD_BACKEND = os.environ.get("BOARD_BACKEND", "https://backend-patient-wave-3724.fly.dev")
BOARD_UPLOAD_HELPER = os.path.expanduser(
    "~/workspace/custom-connectors/custom.ghar-backend/bin/board_upload.py"
)


def upload_file(path):
    """Upload a board file to the Ghar backend; return its public URL.

    The backend (/board/upload) hosts the file at a public URL so Voice
    Monkey, the phone, and the TV can fetch it. No approval card — the
    backend is Som's own server, unlike remote-storage uploads which
    trigger a per-upload approval and broke the automatic board.
    Auth uses the registered custom.ghar-backend connector credential
    (Bearer token, stored in the Secure Vault); the helper script
    attaches it via the dynamic_credentials surrogate. Do NOT read a
    token from ~/.board-upload-token — that file holds a stale
    VM-generated value that does not match the Fly secret.
    """
    result = subprocess.run(
        [sys.executable, BOARD_UPLOAD_HELPER, "--path", path],
        check=True, capture_output=True, text=True, timeout=120,
    )
    data = json.loads(result.stdout)
    return BOARD_BACKEND + data["url"]


def voicemonkey_announce(name, url, is_video=False, announcement=None, retries=3):
    """Send the board to the Echo Show 11 via Voice Monkey.

    Calls the v3 announce API with the Speaker device id, the greeting
    as the announcement (or an empty string for a SILENT image swap —
    the rotation sends use empty so the Show changes photo without
    re-speaking), and the board as `image` (single JPEG, stays the full
    display_seconds) or `video` (MP4 — the Show drops video early, so
    video is no longer used; kept for compatibility). display_seconds
    300 keeps a still image on screen at least 5 minutes (Som's ask,
    2026-11-26). Retries the transient "Remote end closed connection"
    error. Returns True on success. Skips silently (no exception) when
    the token/device files are absent so a missing Voice Monkey setup
    never breaks the phone/TV delivery.
    """
    token_path = os.path.expanduser("~/.voicemonkey-token")
    device_path = os.path.expanduser("~/.voicemonkey-device")
    if not (os.path.exists(token_path) and os.path.exists(device_path)):
        print("Voice Monkey: token/device file missing, skipping Show send", file=sys.stderr)
        return False
    token = open(token_path).read().strip()
    device = open(device_path).read().strip()
    media_key = "video" if is_video else "image"
    if announcement is None:
        announcement = f"Namaste, welcome home, {name}"
    body = json.dumps({
        "device": device,
        "announcement": announcement,
        media_key: url,
        "display_seconds": 300,
    }).encode()
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(VOICEMONKEY_ANNOUNCE_URL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read().decode())
            print(f"Voice Monkey announce: HTTP {r.status} {result}")
            return bool(result.get("success"))
        except Exception as e:
            print(f"Voice Monkey announce attempt {attempt} failed: {e}", file=sys.stderr)
            if attempt < retries:
                time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--photo", default=None, help="override photo path")
    args = ap.parse_args()
    name = args.name

    # 1. Photos: override (single) > Immich memory (up to 8, rotating GIF)
    #    > live porch snapshot (single JPEG). Rotating GIF is Som's ask
    #    2026-11-26: 8 photos per person, ~3s each, looping (was 5).
    photos = []
    source = "override"
    if args.photo:
        photos = [args.photo]
    else:
        key = immich_key()
        if key:
            photos = pick_immich_photos(name, key, count=8)
            source = "immich"
        if not photos:
            photos = [porch_snapshot()]
            source = "porch-snapshot"
    print(f"photo source: {source} ({len(photos)} photo(s))")

    # 2. Today's counts + door state from HA
    states = {s["entity_id"]: s.get("state") for s in ha_get("/api/states")}
    visitors = states.get("sensor.porch_digest_visitors", "0")
    strangers = states.get("sensor.porch_digest_strangers", "0")
    deliveries = states.get("sensor.porch_digest_deliveries", "0")
    door = "Locked" if states.get("lock.front_door") == "locked" else "Unlocked"

    # 3. Build the board — animated GIF when we have several photos,
    #    plain JPEG when only one.
    multi = len(photos) > 1
    ext = "gif" if multi else "jpg"
    board = os.path.join(tempfile.gettempdir(), f"porch-board-{name.lower()}.{ext}")
    cmd = [
        sys.executable,
        os.path.expanduser("~/workspace/scripts/porch_board.py"),
        "--name", name,
        "--visitors", str(visitors), "--strangers", str(strangers),
        "--deliveries", str(deliveries), "--door", door,
        "--out", board,
    ]
    if multi:
        cmd += ["--photos", ",".join(photos), "--duration", "3000"]
    else:
        cmd += ["--photo", photos[0]]
    subprocess.run(cmd, check=True)

    # 4. Upload to the Ghar backend (public HTTPS URL, no approval card)
    url = upload_file(board)
    print(f"board URL: {url}")

    # 5. Send the board to Som's phone (the delivery that PROVEN works —
    #    Echo Show background and TV play_media both ignore images).
    ha_post_service(
        "notify", "mobile_app_iphone",
        {"title": f"Namaste, welcome home, {name}",
         "message": f"Memory Wall + Who's Here — {name} is home.",
         "data": {"image": url}},
    )
    print(f"board sent to phone notification (image: {url})")

    # 6. Echo Show 11 via Voice Monkey — the working Show delivery
    #    (proven live 2026-11-26). ONE video per arrival: all 8 photos
    #    rotating inside a single MP4, one Voice Monkey request (Som,
    #    2026-11-26 — "still 8 pics one vid send like before"). The
    #    video loops to ~5 min; if the Show drops it early, that is
    #    accepted — leave it. A single still image only shows 1 photo,
    #    and rotating through separate images would cost 8 requests.
    #    TV + phone still get the rotating GIF. The old HA play_media
    #    background attempt is dead and dropped entirely.
    vm_ok = False
    if multi:
        mp4 = build_board_video(name, photos, visitors, strangers, deliveries, door)
        if mp4:
            mp4_url = upload_file(mp4)
            print(f"board video URL: {mp4_url}")
            vm_ok = voicemonkey_announce(name, mp4_url, is_video=True)
            # The video rotates all 8 photos but drops off the Show after
            # ~1-2 min (inconsistent). The static image holds reliably for
            # the full display_seconds, so send it 90 s later as a hold —
            # the Show keeps the board up instead of going blank when the
            # video drops. (Som, 2026-11-26: video showed nothing, image
            # showed and held.)
            if vm_ok:
                print("video sent; waiting 90s, then sending static image as hold")
                time.sleep(90)
                vm_ok = voicemonkey_announce(name, url, is_video=False, announcement="")
        else:
            print("board video build failed; falling back to GIF image for Show", file=sys.stderr)
            vm_ok = voicemonkey_announce(name, url, is_video=False)
    else:
        vm_ok = voicemonkey_announce(name, url, is_video=False)
    show = ha_get(f"/api/states/{SHOW_ENTITY}")
    print(f"Echo Show 11 state: {show.get('state')} (Voice Monkey send: {'OK' if vm_ok else 'failed/skipped'})")

    # 7. Open the board on the bedroom TV's webOS browser (the working
    #    TV display). Wake the TV first if it is off, then launch the
    #    browser at the board URL. The launcher command can be ignored
    #    when the TV is busy (e.g. playing YouTube), so verify the TV
    #    actually switched to the browser and retry once if it did not.
    #    Best-effort: a TV failure must not break the phone delivery.
    try:
        tv = ha_get(f"/api/states/{BEDROOM_TV_ENTITY}")
        if tv.get("state") in ("off", "unavailable"):
            ha_post_service(
                "media_player", "turn_on", {"entity_id": BEDROOM_TV_ENTITY}
            )
            print(f"bedroom TV was {tv.get('state')}; sent turn_on, waiting 5s")
            time.sleep(5)
        for attempt in (1, 2):
            ha_post_service(
                "webostv", "command",
                {"entity_id": BEDROOM_TV_ENTITY,
                 "command": "system.launcher/open",
                 "payload": {"target": url}},
            )
            time.sleep(3)
            tv = ha_get(f"/api/states/{BEDROOM_TV_ENTITY}")
            attrs = tv.get("attributes", {})
            app = attrs.get("app_name") or attrs.get("app_id")
            print(f"bedroom TV after launcher attempt {attempt}: state={tv.get('state')}, source={attrs.get('source')}, app={app}")
            if app == "com.webos.app.browser":
                break
            if attempt == 1:
                print("bedroom TV did not switch to browser; retrying launcher once")
    except Exception as e:
        print(f"bedroom TV open failed (ignored): {e}", file=sys.stderr)

    print(f"Done. Board for {name} ({source}, {len(photos)} photo(s), {'GIF rotating' if multi else 'JPEG'}) sent to phone + Echo Show (Voice Monkey) + bedroom TV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
