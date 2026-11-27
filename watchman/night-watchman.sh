#!/usr/bin/env bash
WATCHMAN_MODE="${1:-check}"
# night-watchman.sh — Witch Hazel estate checker (runs on the Proxmox host)
set -u
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
REPO=/mnt/vault
PWFILE=/root/.restic-vault-password
STATEDIR=/var/lib/watchman
STATE=$STATEDIR/state
mkdir -p "$STATEDIR"
touch "$STATE"
fails=0
declare -a RESULTS=()
record() {
  RESULTS+=("$2 $1 $3")
  if [ "$2" = FAIL ]; then fails=$((fails+1)); fi
  return 0
}
http_code() {
  local c
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$1" 2>/dev/null)
  echo "${c:-000}"
}
# --- services ---
if curl -fsS -m 10 http://192.168.1.24:2283/api/server/ping 2>/dev/null | grep -q pong; then
  record immich OK "Immich answering (pong)"
else
  record immich FAIL "Immich not answering at 192.168.1.24:2283"
fi
for svc in "landing 30090 /" "grafana 30030 /api/health" "kuma 30095 /" "demo 30080 /"; do
  set -- $svc
  code=$(http_code "http://192.168.1.21:$2$3")
  if [ "$code" -ge 200 ] && [ "$code" -lt 400 ]; then
    record "$1" OK "answering on :$2 (HTTP $code)"
  else
    record "$1" FAIL "HTTP $code on :$2"
  fi
done
# --- guests ---
vmfail=""
for id in 101 102 103; do
  qm status $id 2>/dev/null | grep -q 'status: running' || vmfail="$vmfail $id"
done
if [ -z "$vmfail" ]; then record vms OK "VMs 101/102/103 running"; else record vms FAIL "VMs not running:$vmfail"; fi
if pct status 104 2>/dev/null | grep -q 'status: running'; then
  record immich-ct OK "CT 104 running"
else
  record immich-ct FAIL "CT 104 not running"
fi
# --- storage ---
if findmnt -n /mnt/vault >/dev/null 2>&1; then
  record vault-mount OK "/mnt/vault mounted"
else
  record vault-mount FAIL "/mnt/vault NOT mounted"
fi
pct_used() { df --output=pcent "$1" 2>/dev/null | tail -1 | tr -dc '0-9'; }
u=$(pct_used /)
if [ -n "$u" ] && [ "$u" -lt 85 ]; then record disk-root OK "host root ${u}%"; else record disk-root FAIL "host root ${u:-?}% (limit 85%)"; fi
u=$(pct_used /srv/immich)
if [ -n "$u" ] && [ "$u" -lt 85 ]; then record disk-library OK "library volume ${u}%"; else record disk-library FAIL "library volume ${u:-?}% (limit 85%)"; fi
if findmnt -n /mnt/vault >/dev/null 2>&1; then
  u=$(pct_used /mnt/vault)
  if [ -n "$u" ] && [ "$u" -lt 90 ]; then record disk-vault OK "vault drive ${u}%"; else record disk-vault FAIL "vault drive ${u:-?}% (limit 90%)"; fi
fi
p=$(lvs --noheadings -o data_percent pve/data 2>/dev/null | tr -d ' ' | cut -d. -f1)
if [ -n "$p" ] && [ "$p" -lt 85 ]; then record disk-pool OK "thin pool data ${p}%"; else record disk-pool FAIL "thin pool data ${p:-?}% (limit 85%)"; fi
# --- backup freshness ---
if systemctl is-active --quiet vault-backup.service || systemctl is-active --quiet immich-vault-backup.service; then
  record snapshot OK "backup in progress now"
else
  latest=$(restic snapshots --no-lock --repo "$REPO" --password-file "$PWFILE" --json 2>/dev/null | python3 -c 'import sys,json
try:
  d=json.load(sys.stdin)
  ts=[s["time"] for s in d]
  print(max(ts) if ts else "")
except Exception:
  print("")')
  if [ -z "$latest" ]; then
    record snapshot FAIL "no snapshots found in vault"
  else
    epoch=$(date -d "$latest" +%s 2>/dev/null || echo 0)
    age_h=$(( ( $(date +%s) - epoch ) / 3600 ))
    if [ "$epoch" -gt 0 ] && [ "$age_h" -lt 36 ]; then
      record snapshot OK "latest snapshot ${age_h}h old"
    else
      record snapshot FAIL "latest snapshot ${age_h}h old (limit 36h)"
    fi
  fi
fi
# --- network card (counter-delta: alert only when the all-time total grows) ---
errs=$(ip -s link show nic0 2>/dev/null | awk '/RX:/{getline; r=$3} /TX:/{getline; t=$3} END{print (r+t)+0}')
flap_total=0
for b in 0 -1 -2 -3 -4 -5 -6 -7 -8 -9; do
  c=$(journalctl -k -b $b --no-pager 2>/dev/null | grep -c 'Link is Down' || true)
  flap_total=$((flap_total + ${c:-0}))
done
flap_total=${flap_total:-0}
FLAPFILE=$STATEDIR/nic-flaps-total
flap_note=""
flap_fail=0
if [ -f "$FLAPFILE" ]; then
  prev=$(cat "$FLAPFILE" 2>/dev/null || echo 0)
  if [ "$flap_total" -gt "$prev" ]; then
    flap_fail=1
    flap_note="$((flap_total - prev)) NEW link-down events (total $flap_total)"
  elif [ "$flap_total" -lt "$prev" ]; then
    flap_note="flap counter reset (journal rotated; total now $flap_total)"
  else
    flap_note="no new link-downs (total $flap_total)"
  fi
else
  flap_note="flap baseline set at $flap_total"
fi
if [ "$WATCHMAN_MODE" != "heartbeat" ]; then echo "$flap_total" > "$FLAPFILE"; fi
if [ "$flap_fail" -eq 0 ] && [ "${errs:-0}" -eq 0 ]; then
  record nic OK "nic0: $flap_note; 0 errors"
else
  record nic FAIL "nic0: $flap_note; errors=${errs:-?}"
fi
# --- cluster pods (view-only token; API over LAN HTTPS) ---
if [ -s /etc/watchman/k8s-token ] && [ -s /etc/watchman/k8s-ca.crt ]; then
  pods_out=$(python3 - <<'K8SPY'
import json, ssl, urllib.request
from datetime import datetime, timezone
tok = open('/etc/watchman/k8s-token').read().strip()
ctx = ssl.create_default_context(cafile='/etc/watchman/k8s-ca.crt')
req = urllib.request.Request('https://192.168.1.21:6443/api/v1/pods', headers={'Authorization': 'Bearer ' + tok})
try:
    data = json.load(urllib.request.urlopen(req, context=ctx, timeout=20))
except Exception as e:
    print('FAIL|pods API unreachable: %s' % e)
    raise SystemExit
bad = []
total = 0
for pod in data.get('items', []):
    total += 1
    md = pod.get('metadata', {})
    name = md.get('namespace', '?') + '/' + md.get('name', '?')
    st = pod.get('status', {})
    phase = st.get('phase')
    if phase == 'Succeeded':
        continue
    if phase != 'Running':
        bad.append('%s phase=%s' % (name, phase))
        continue
    css = st.get('containerStatuses') or []
    if not css:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(md.get('creationTimestamp', '').replace('Z', '+00:00'))).total_seconds()
        except Exception:
            age = 9999
        if age > 600:
            bad.append('%s no container statuses after %dm' % (name, int(age // 60)))
        continue
    for cs in css:
        if not cs.get('ready'):
            w = (cs.get('state', {}) or {}).get('waiting', {}) or {}
            bad.append('%s %s not ready (%s)' % (name, cs.get('name'), w.get('reason', 'waiting')))
if bad:
    print('FAIL|%d of %d pods unwell: %s' % (len(bad), total, '; '.join(bad[:4])))
else:
    print('OK|%d pods, none unwell' % total)
K8SPY
)
  case "$pods_out" in OK*|FAIL*) ;; *) pods_out='FAIL|pods check produced no verdict';; esac
  record pods "${pods_out%%|*}" "${pods_out#*|}"
else
  record pods FAIL 'cluster credential files missing'
fi
# --- frigate detection + home assistant ---
if pct status 105 2>/dev/null | grep -q 'status: running'; then
  frig_stats=$(pct exec 105 -- docker exec frigate curl -s http://localhost:5000/api/stats 2>/dev/null)
  frig_verdict=$(FRIG_STATS="$frig_stats" python3 - <<'FRIGPY'
import json, os
try:
    d = json.loads(os.environ.get('FRIG_STATS') or '')
    cam = d.get('cameras', {}).get('porch', {})
    cf = float(cam.get('camera_fps') or 0)
    df = float(cam.get('detection_fps') or 0)
    if cf > 0 and df == 0:
        print('OK|porch idle, frames flowing (%.1f fps) no motion, detection 0.0 fps (normal)' % cf)
    elif cf == 0:
        print('OK|camera off (0 fps in, 0 detected)')
    else:
        print('OK|porch detection %.1f fps (camera %.1f fps)' % (df, cf))
except Exception as e:
    print('FAIL|stats unreadable: %s' % e)
FRIGPY
)
  case "$frig_verdict" in OK*|FAIL*) ;; *) frig_verdict='FAIL|frigate check produced no verdict';; esac
  record frigate-detect "${frig_verdict%%|*}" "${frig_verdict#*|}"
else
  record frigate-detect FAIL 'CT 105 not running'
fi
code=$(http_code 'http://192.168.1.26:8123/')
if [ "$code" -ge 200 ] && [ "$code" -lt 400 ]; then
  record ha OK "answering on :8123 (HTTP $code)"
else
  record ha FAIL "HTTP $code on :8123"
fi

# --- config backup freshness (tag config) ---
if systemctl is-active --quiet immich-vault-backup.service; then
  record snapshot-config OK "backup in progress now"
else
  latest_cfg=$(restic snapshots --no-lock --repo "$REPO" --password-file "$PWFILE" --tag config --json 2>/dev/null | python3 -c 'import sys,json
try:
  d=json.load(sys.stdin)
  ts=[s["time"] for s in d]
  print(max(ts) if ts else "")
except Exception:
  print("")')
  if [ -z "$latest_cfg" ]; then
    record snapshot-config FAIL "no config snapshots found in vault"
  else
    epoch_cfg=$(date -d "$latest_cfg" +%s 2>/dev/null || echo 0)
    age_cfg=$(( ( $(date +%s) - epoch_cfg ) / 3600 ))
    if [ "$epoch_cfg" -gt 0 ] && [ "$age_cfg" -lt 36 ]; then
      record snapshot-config OK "latest config snapshot ${age_cfg}h old"
    else
      record snapshot-config FAIL "latest config snapshot ${age_cfg}h old (limit 36h)"
    fi
  fi
fi

PENDING=$STATEDIR/pending-mail
wm_send() {
  if python3 /usr/local/sbin/watchman-mail.py "$1" "$2"; then
    return 0
  fi
  { printf '%s\n' "$1"; cat "$2"; } > "$PENDING"
  echo "mail spooled for retry: $1"
  return 1
}
wm_flush() {
  [ -s "$PENDING" ] || return 0
  local subj bodyf
  subj=$(head -n 1 "$PENDING")
  bodyf=$(mktemp)
  tail -n +2 "$PENDING" > "$bodyf"
  if python3 /usr/local/sbin/watchman-mail.py "$subj" "$bodyf"; then
    rm -f "$PENDING"
    echo "spooled mail delivered on retry: $subj"
  fi
  rm -f "$bodyf"
}
# --- report + state ---
echo "night-watchman — $(date '+%Y-%m-%d %H:%M %Z') — pve"
printf '%s\n' "${RESULTS[@]}"
newstate=$(mktemp)
for line in "${RESULTS[@]}"; do
  echo "$(echo "$line" | awk '{print $2}')=$(echo "$line" | awk '{print $1}')" >> "$newstate"
done
if [ -s "$STATE" ]; then
  changes=$(diff <(sort "$STATE") <(sort "$newstate") | grep '^[<>]' || true)
  if [ -n "$changes" ]; then echo "CHANGES vs last run:"; echo "$changes"; else echo "no changes vs last run"; fi
fi
body=$(mktemp)
{
  echo "night-watchman — $(date '+%Y-%m-%d %H:%M %Z') — pve"
  printf '%s\n' "${RESULTS[@]}"
  if [ -n "${changes:-}" ]; then echo "CHANGES vs last run:"; echo "$changes"; else echo "no changes vs last run"; fi
} > "$body"
wm_flush
if [ "$WATCHMAN_MODE" = "heartbeat" ]; then
  if [ "$fails" -eq 0 ]; then
    wm_send "watchman heartbeat — pve: estate is well" "$body"
  else
    wm_send "watchman heartbeat — pve: $fails check(s) FAILING" "$body"
  fi
elif [ -n "${changes:-}" ]; then
  if [ "$fails" -eq 0 ]; then
    wm_send "watchman — pve: changes, all currently OK" "$body"
  else
    wm_send "watchman ALERT — pve: $fails check(s) failing" "$body"
  fi
fi
rm -f "$body"
if [ "$WATCHMAN_MODE" != "heartbeat" ]; then cp "$newstate" "$STATE"; fi
rm -f "$newstate"
[ "$fails" -eq 0 ]
