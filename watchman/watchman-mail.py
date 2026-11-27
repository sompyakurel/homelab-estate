#!/usr/bin/env python3
import json, os, subprocess, sys
def main():
    subject = sys.argv[1]
    with open(sys.argv[2]) as f: body = f.read()
    with open('/etc/watchman/resend.key') as f: key = f.read().strip()
    payload = json.dumps({"from": os.environ.get("WATCHMAN_FROM", "Night Watchman <watchman@example.com>"), "to": [os.environ.get("WATCHMAN_TO", "you@example.com")], "subject": subject, "text": body})
    try:
        out = subprocess.run(['curl', '-sS', '-X', 'POST', 'https://api.resend.com/emails', '-H', 'Authorization: Bearer ' + key, '-H', 'Content-Type: application/json', '-d', '@-'], input=payload.encode(), capture_output=True, timeout=40)
        resp = out.stdout.decode(errors='replace')
        if out.returncode == 0 and '"id"' in resp:
            print('mail sent:', resp.strip()[:120])
            return 0
        print('mail FAILED: rc=%s resp=%s err=%s' % (out.returncode, resp.strip()[:200], out.stderr.decode(errors='replace').strip()[:200]), file=sys.stderr)
        return 1
    except Exception as e:
        print('mail FAILED: %s' % e, file=sys.stderr)
        return 1
sys.exit(main())
