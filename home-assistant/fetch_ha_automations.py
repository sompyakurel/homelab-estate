#!/usr/bin/env python3
"""Fetch all Home Assistant automations via the REST API and write
them as automations.yaml for the homelab-estate repo.

Uses the long-lived token in ~/.ha-token and the tunnel proxy.
Each automation's config is fetched by its config id (from the state
attributes), then dumped as a YAML list — the same shape as the
automations.yaml file HA itself maintains.

The front-door lock's HA device ID is replaced with the placeholder
YOUR_LOCK_DEVICE_ID on write (it identifies your lock; keep it out of
a public repo). To re-apply the swap on refresh, set LOCK_DEVICE_ID
to your lock's real device ID in the environment before running this
script — the value itself is never written into the repo.
"""
import json
import os
import subprocess
import sys

import yaml

PROXY = os.environ.get("HTTPS_PROXY", "")
# Tunnel proxy is on port 3130; HTTPS_PROXY points at the egress proxy
# on 3128 and carries credentials — strip only the trailing port and
# re-append 3130 (same as ${HTTPS_PROXY%:*}:3130 in shell).
TUNNEL = PROXY.rsplit(":", 1)[0] + ":3130"
HA = "http://192.168.1.26:8123"
TOKEN = open(os.path.expanduser("~/.ha-token")).read().strip()


def ha_get(path):
    out = subprocess.run(
        ["curl", "-s", "-x", TUNNEL, "--max-time", "25",
         "-H", f"Authorization: Bearer {TOKEN}", HA + path],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


states = ha_get("/api/states")
autos = sorted(
    (s for s in states if s.get("entity_id", "").startswith("automation.")),
    key=lambda s: s["entity_id"])

configs = []
for s in autos:
    cid = s.get("attributes", {}).get("id")
    if not cid:
        print(f"SKIP {s['entity_id']}: no config id", file=sys.stderr)
        continue
    cfg = ha_get(f"/api/config/automation/config/{cid}")
    if "message" in cfg and "id" not in cfg:
        print(f"SKIP {s['entity_id']}: {cfg}", file=sys.stderr)
        continue
    configs.append(cfg)
    print(f"fetched {s['entity_id']} (id {cid})")

out_path = os.path.expanduser(
    "~/workspace/homelab-estate/home-assistant/automations.yaml")
with open(out_path, "w") as f:
    f.write("# Home Assistant automations — fetched live from CT 106\n")
    f.write("# via the REST API (config ids from state attributes).\n")
    f.write("# Generated 2026-11-26; re-run fetch_ha_automations.py to refresh.\n")
    f.write("# NOTE: the front-door lock's Home Assistant device ID has been\n")
    f.write("# replaced with the placeholder YOUR_LOCK_DEVICE_ID (it is an\n")
    f.write("# HA-internal UUID, not a credential, but it identifies your lock).\n")
    f.write("# Find yours in HA: Settings -> Devices & services -> Devices ->\n")
    f.write("# your lock -> the ID is in the page URL. Substitute it above.\n\n")
    yaml.safe_dump(configs, f, default_flow_style=False,
                   allow_unicode=True, sort_keys=False)

# Re-apply the lock device-ID placeholder if LOCK_DEVICE_ID is set.
lock_id = os.environ.get("LOCK_DEVICE_ID", "")
if lock_id:
    text = open(out_path).read()
    text = text.replace(lock_id, "YOUR_LOCK_DEVICE_ID")
    open(out_path, "w").write(text)
    print("lock device ID replaced with placeholder")

# Re-apply the home WiFi SSID placeholders if HOME_SSID is set
# (the _EXT network is the same base name with _EXT appended).
home_ssid = os.environ.get("HOME_SSID", "")
if home_ssid:
    text = open(out_path).read()
    text = text.replace(home_ssid + "_EXT", "YOUR_HOME_SSID_EXT")
    text = text.replace(home_ssid, "YOUR_HOME_SSID")
    open(out_path, "w").write(text)
    print("home WiFi SSIDs replaced with placeholders")
print(f"\nwrote {len(configs)} automations to {out_path}")
