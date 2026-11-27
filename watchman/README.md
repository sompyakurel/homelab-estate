# Night watchman

Health checker for the whole estate — 15 checks, every 30 min, plus a
Sunday 09:00 heartbeat. Mails Som on change (Resend) and stays silent
when everything is green. Runs on the Proxmox host (pve).

## Files

- `night-watchman.sh` — the live script from `/usr/local/sbin/` on
  pve. Secrets (restic password, k8s token, Resend key) are file paths
  only — no values in it. LAN IPs (.21/.24/.26) are the check targets.
- `watchman-mail.py` — the mail helper from `/usr/local/sbin/`.
  **Sanitized:** sender and recipient are now env vars
  (`WATCHMAN_FROM`, `WATCHMAN_TO` — see `../.env.example`); the
  Resend key is read from `/etc/watchman/resend.key` at runtime.

## Checks

Frigate detection, HA, Immich, vault/restic, disks, snapshots, NIC
link-downs, k3s pods, and more. State in `/var/lib/watchman/`.

## Known behaviour

- A `detection_fps` of 0 on a still scene is NORMAL — Frigate only
  runs the object detector on frames where motion was detected. The
  check reports OK ("porch idle, frames flowing, no motion") in that
  case; it only FAILs when the stats API itself is unreadable.
