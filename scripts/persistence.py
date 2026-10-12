"""Verify a real demo ticket survives API/DB pod replacement and Helm rollback."""
import argparse
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, HTTPCookieProcessor, build_opener

ROOT = Path(__file__).resolve().parents[1]
KUBE = ['kubectl', '--context=minikube', '-n', 'seatlock']
browser = build_opener(HTTPCookieProcessor(CookieJar()))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rollback-revision', type=int, required=True, help='Previously healthy, schema-compatible Helm revision whose images remain available')
args = parser.parse_args()


def run(args):
    return subprocess.check_output(args, cwd=ROOT, text=True, timeout=240)


def api(path, method='GET', data=None):
    headers = {'Host': 'seatlock.local', 'X-Seatlock-Request': '1', 'Content-Type': 'application/json'}
    with browser.open(Request('http://127.0.0.1:3004/api'+path, headers=headers, method=method,
                             data=json.dumps(data).encode() if data is not None else None), timeout=8) as response:
        return json.load(response)


def resources():
    pods = json.loads(run(KUBE + ['get', 'pods', '-o', 'json']))['items']
    pvc = json.loads(run(KUBE + ['get', 'pvc', 'data-seatlock-postgres-0', '-o', 'json']))
    return {'time': datetime.now(timezone.utc).isoformat(), 'pvc_uid': pvc['metadata']['uid'],
            'pods': [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'],
                      'ready': all(c.get('ready') for c in p['status'].get('containerStatuses', [])),
                      'images': [c.get('imageID') for c in p['status'].get('containerStatuses', [])]}
                     for p in pods if p['metadata']['labels'].get('app.kubernetes.io/name') in
                     {'seatlock-backend', 'seatlock-postgres'}]}


def wait_for(callback):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            result = callback()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError('Recovery was not verified within 120 seconds')


def verify_ticket(ticket):
    actual = api('/holds/'+ticket['id'])
    assert actual['reference'] == ticket['reference']
    assert actual['total_paise'] == ticket['total_paise'] and actual['status'] == 'confirmed'
    assert any(b['id'] == ticket['id'] for b in api('/bookings'))
    return True


if run(['kubectl', 'config', 'current-context']).strip() != 'minikube':
    raise SystemExit('Select the local minikube context first.')
history = json.loads(run(['helm','history','seatlock','--kube-context','minikube','-n','seatlock','-o','json']))
assert any(int(r['revision']) == args.rollback_revision and r['status'] == 'superseded' for r in history), 'Choose a previous healthy Helm revision.'
saved_values = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
saved_values.write(run(['helm','get','values','seatlock','--kube-context','minikube','-n','seatlock','-o','json']))
saved_values.close()

def restore_current():
    command = ['helm','upgrade','seatlock','helm/seatlock','--kube-context','minikube','-n','seatlock',
               '-f',saved_values.name,'--wait','--wait-for-jobs','--timeout','3m']
    if run(['helm','version','--short']).startswith('v4.'):
        command.append('--force-conflicts')
    run(command)

api('/session')
event = api('/events')[0]['id']
seat = next(s['id'] for s in api(f'/events/{event}/seats')['seats'] if s['status'] == 'available')
hold = api('/holds', 'POST', {'event_id': event, 'seat_ids': [seat]})
ticket = api('/holds/'+hold['id']+'/confirm', 'POST')
record = {'namespace': 'seatlock', 'context': 'minikube', 'demo_reference': ticket['reference'],
          'before': resources(), 'steps': []}
try:
    old_ids = {p['uid'] for p in record['before']['pods']}
    run(KUBE + ['delete', 'pod', '-l', 'app.kubernetes.io/name=seatlock-backend', '--timeout=45s'])
    wait_for(lambda: all(p['uid'] not in old_ids and p['ready'] for p in resources()['pods']
                        if p['name'].startswith('seatlock-backend-')) and verify_ticket(ticket))
    record['steps'].append({'action': 'Replace API pods', 'ticket_preserved': True, 'resources': resources()})
    old_db = next(p['uid'] for p in record['before']['pods'] if p['name'] == 'seatlock-postgres-0')
    run(KUBE + ['delete', 'pod', 'seatlock-postgres-0', '--timeout=45s'])
    wait_for(lambda: any(p['name'] == 'seatlock-postgres-0' and p['uid'] != old_db and p['ready']
                        for p in resources()['pods']) and verify_ticket(ticket))
    assert resources()['pvc_uid'] == record['before']['pvc_uid']
    record['steps'].append({'action': 'Replace PostgreSQL pod', 'same_pvc': True,
                            'ticket_preserved': True, 'resources': resources()})
    run(['helm', 'rollback', 'seatlock', str(args.rollback_revision), '--kube-context', 'minikube', '-n', 'seatlock',
         '--wait', '--wait-for-jobs', '--timeout', '3m'])
    wait_for(lambda: verify_ticket(ticket))
    record['steps'].append({'action': f'Helm rollback to healthy revision {args.rollback_revision}',
                            'ticket_preserved': True, 'resources': resources()})
    restore_current()
    wait_for(lambda: verify_ticket(ticket))
    record['steps'].append({'action': 'Restore saved current release values',
                            'ticket_preserved': True, 'resources': resources()})
finally:
    # Restore the working release even if an intermediate check fails.
    restore_current()
    Path(saved_values.name).unlink(missing_ok=True)
    wait_for(lambda: api('/bookings/'+ticket['id']+'/cancel', 'POST')['status'] == 'cancelled')
    record['demo_ticket_cancelled'] = True
    (ROOT/'docs/evidence/persistence.json').write_text(json.dumps(record, indent=2)+'\n')
print('Same ticket survived API replacement, DB replacement, Helm rollback and upgrade; PVC preserved.')
