"""Local fault drills with fixed namespace and bounded operations; never uses AWS."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
from urllib.request import Request, HTTPCookieProcessor, build_opener
from http.cookiejar import CookieJar

ROOT = Path(__file__).resolve().parents[1]
NS = 'seatlock-drill'
KUBE = ['kubectl', '--context=minikube', '-n', NS]
BACKEND_TAG = os.environ.get('SEATLOCK_BACKEND_TAG', 'local')
FRONTEND_TAG = os.environ.get('SEATLOCK_FRONTEND_TAG', 'local')
CASES = {
    'T01': ('Invalid image', 'The new pod references a nonexistent image tag. An old ready replica may still serve.'),
    'T02': ('Service selector', 'The Service selector matches no pod labels, leaving no ready backend endpoints.'),
    'T03': ('Secret key', 'DATABASE_URL references a nonexistent Secret key, preventing container creation.'),
    'T05': ('Readiness path', 'The readiness URL /ready-typo returns 404, excluding the new pod from traffic.'),
    'T07': ('Storage class', 'The disposable claim requests a nonexistent StorageClass and remains Pending.'),
    'T09': ('Monitoring port', 'The ServiceMonitor references a port absent from the API Service, preventing target discovery.'),
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def run(args, check=True, input=None):
    p = subprocess.run(args, cwd=ROOT, input=input, capture_output=True, text=True, timeout=240)
    if check and p.returncode:
        raise RuntimeError(' '.join(args) + '\n' + p.stderr)
    return p.stdout + p.stderr


def get(kind, name=None):
    return json.loads(run(KUBE + ['get', kind] + ([name] if name else []) + ['-o', 'json']))


def patch(kind, name, value, kind_of_patch='strategic'):
    run(KUBE + ['patch', kind, name, '--type='+kind_of_patch, '-p', json.dumps(value)])


def restore():
    run(KUBE + ['delete', 'pvc', 'storage-drill', '--ignore-not-found', '--timeout=30s'])
    helm = ['helm', 'upgrade', '--install', 'seatlock-drill', 'helm/seatlock', '--kube-context', 'minikube', '-n', NS,
         '--set-string', 'backend.tag='+BACKEND_TAG, '--set-string', 'frontend.tag='+FRONTEND_TAG, '--set', 'hpa.enabled=false',
         '--set', 'replicaCount=1', '--set', 'monitoring.enabled=true', '--set', 'ingress.enabled=true',
         '--set', 'ingress.host=seatlock-drill.local', '--wait', '--wait-for-jobs', '--timeout', '3m']
    if run(['helm', 'version', '--short']).startswith('v4.'):
        helm.append('--force-conflicts')
    run(helm)


def prepare():
    run(['kubectl', '--context=minikube', 'create', 'namespace', NS], check=False)
    run(['python3', 'scripts/kube-secret.py', '--namespace', NS])
    restore()


def inject(case):
    if case == 'T01':
        # Never makes a missing LOCAL tag deterministic without registry timeouts.
        patch('deployment', 'seatlock-backend', {'spec': {'template': {'spec': {'containers': [
            {'name': 'backend', 'image': 'seatlock-backend:nonexistent-drill', 'imagePullPolicy': 'Never'}]}}}})
    elif case == 'T02':
        patch('service', 'backend', {'spec': {'selector': {'app.kubernetes.io/name': 'wrong-selector'}}}, 'merge')
    elif case == 'T03':
        patch('deployment', 'seatlock-backend', {'spec': {'template': {'spec': {'containers': [
            {'name': 'backend', 'env': [{'name': 'DATABASE_URL', 'valueFrom': {
                'secretKeyRef': {'name': 'seatlock-runtime', 'key': 'database-url-typo'}}}]}]}}}})
    elif case == 'T05':
        patch('deployment', 'seatlock-backend', {'spec': {'template': {'spec': {'containers': [
            {'name': 'backend', 'readinessProbe': {'httpGet': {'path': '/ready-typo'}}}]}}}})
    elif case == 'T07':
        claim = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'storage-drill', 'namespace': NS},
                 'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'seatlock-does-not-exist',
                          'resources': {'requests': {'storage': '32Mi'}}}}
        run(KUBE + ['apply', '-f', '-'], input=json.dumps(claim))
    elif case == 'T09':
        patch('servicemonitor', 'seatlock', {'spec': {'endpoints': [
            {'port': 'http-typo', 'path': '/metrics', 'interval': '15s'}]}}, 'merge')


def targets():
    with urlopen('http://127.0.0.1:9091/api/v1/targets', timeout=5) as response:
        data = json.load(response)
    return [t for t in data['data']['activeTargets']
            if t['labels'].get('namespace') == NS and t['labels'].get('job') == 'seatlock']


def symptom(case):
    if case in {'T01', 'T03'}:
        for pod in get('pods')['items']:
            if pod['metadata']['labels'].get('app.kubernetes.io/name') != 'seatlock-backend':
                continue
            for container in pod['status'].get('containerStatuses', []):
                reason = container.get('state', {}).get('waiting', {}).get('reason', '')
                if case == 'T01' and reason in {'ErrImagePull', 'ImagePullBackOff', 'ErrImageNeverPull'}:
                    return reason
                if case == 'T03' and reason == 'CreateContainerConfigError':
                    return reason
    elif case == 'T05':
        if any('Readiness' in e.get('message', '') and '404' in e.get('message', '') for e in get('events')['items']):
            return 'Readiness probe returned HTTP 404'
    elif case == 'T02':
        ready = [e for s in get('endpointslices')['items']
                 if s['metadata']['labels'].get('kubernetes.io/service-name') == 'backend'
                 for e in (s.get('endpoints') or []) if e.get('conditions', {}).get('ready')]
        if not ready:
            return 'Zero ready backend Service endpoints'
    elif case == 'T07':
        if get('pvc', 'storage-drill').get('status', {}).get('phase') == 'Pending':
            return 'Scratch PVC Pending with missing StorageClass'
    elif case == 'T09' and not targets():
        return 'No discovered drill API scrape targets'
    return None


def wait_for(callback, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = callback()
        if result:
            return result
        time.sleep(2)
    raise RuntimeError('Expected condition not observed within bounded timeout')


def snapshot():
    # Only references to Secrets are collected; never obtain Secret values.
    commands = [['get', 'pods,svc,endpointslices,pvc'], ['get', 'events', '--sort-by=.lastTimestamp'],
                ['describe', 'deployment', 'seatlock-backend'], ['describe', 'service', 'backend'],
                ['get', 'servicemonitor', 'seatlock', '-o', 'yaml'],
                ['logs', 'deployment/seatlock-backend', '--tail=8']]
    if run(KUBE + ['get', 'pvc', 'storage-drill'], check=False).startswith('NAME'):
        commands.append(['describe', 'pvc', 'storage-drill'])
    return [{'command': ' '.join(KUBE + c), 'output': run(KUBE + c, check=False)} for c in commands]


def verify():
    deployment = get('deployment', 'seatlock-backend')
    assert deployment['status'].get('readyReplicas') == deployment['spec']['replicas']
    assert deployment['status'].get('updatedReplicas') == deployment['spec']['replicas']
    browser = build_opener(HTTPCookieProcessor(CookieJar()))
    def request(path, method='GET', data=None):
        headers = {'Host': 'seatlock-drill.local', 'X-Seatlock-Request': '1', 'Content-Type': 'application/json'}
        payload = json.dumps(data).encode() if data is not None else None
        with browser.open(Request('http://127.0.0.1:3004/api'+path, headers=headers, method=method, data=payload), timeout=10) as response:
            return json.load(response)
    request('/session')
    events = request('/events')
    assert len(events) >= 4
    event = events[0]['id']
    seat = next(s['id'] for s in request(f'/events/{event}/seats')['seats'] if s['status'] == 'available')
    hold = request('/holds', 'POST', {'event_id': event, 'seat_ids': [seat]})
    booking = request('/holds/'+hold['id']+'/confirm', 'POST')
    assert booking['status'] == 'confirmed' and booking['reference']
    assert any(b['id'] == booking['id'] for b in request('/bookings'))
    assert request('/bookings/'+booking['id']+'/cancel', 'POST')['status'] == 'cancelled'
    assert next(s for s in request(f'/events/{event}/seats')['seats'] if s['id'] == seat)['status'] == 'available'
    wait_for(lambda: targets() and all(t['health'] == 'up' for t in targets()))
    return 'Ingress routing, hold, confirmation, private tickets, cancellation and target UP passed'


def run_all():
    evidence = ROOT / 'docs/evidence/troubleshooting'
    evidence.mkdir(parents=True, exist_ok=True)
    prepare()
    verify()
    for case, (title, cause) in CASES.items():
        start = timestamp()
        print(f'{case}: introducing {title}', flush=True)
        inject(case)
        observed = wait_for(lambda: symptom(case))
        record = {'scenario': case, 'title': title, 'namespace': NS, 'context': 'minikube',
                  'source': 'Standalone working tree; Git initialization reserved for owner',
                  'started_at': start, 'fault_observed_at': timestamp(), 'symptom': observed,
                  'root_cause': cause, 'investigation': snapshot(), 'fix': 'Restore Helm desired state'}
        restore()
        record['verification'] = verify()
        record['recovered_at'] = timestamp()
        record['after'] = snapshot()
        (evidence / (case + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        print(f'{case}: {observed}; restored and verified', flush=True)
    print('Combined challenge: image, Service, and monitoring faults', flush=True)
    record = {'scenario': 'combined T01+T02+T09', 'started_at': timestamp(), 'namespace': NS, 'context': 'minikube', 'steps': []}
    for case in ['T01', 'T02', 'T09']:
        inject(case)
    for case in ['T01', 'T02', 'T09']:
        record['steps'].append({'time': timestamp(), 'scenario': case,
                                'observed': wait_for(lambda: symptom(case)), 'root_cause': CASES[case][1]})
    record['investigation'] = snapshot()
    patch('deployment', 'seatlock-backend', {'spec': {'template': {'spec': {'containers': [
        {'name': 'backend', 'image': 'seatlock-backend:'+BACKEND_TAG, 'imagePullPolicy': 'IfNotPresent'}]}}}})
    run(KUBE + ['rollout', 'status', 'deployment/seatlock-backend', '--timeout=90s'])
    record['steps'].append({'time': timestamp(), 'fix': 'Restore API image',
                            'remaining': [symptom('T02'), symptom('T09')]})
    patch('service', 'backend', {'spec': {'selector': {'app.kubernetes.io/name': 'seatlock-backend'}}}, 'merge')
    wait_for(lambda: not symptom('T02'))
    record['steps'].append({'time': timestamp(), 'fix': 'Restore Service selector', 'remaining': symptom('T09')})
    restore()
    record['verification'] = verify()
    record['recovered_at'] = timestamp()
    record['after'] = snapshot()
    (evidence / 'combined.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Six individual drills and combined challenge recovered.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'inject', 'inspect', 'restore', 'verify', 'run-all'])
    parser.add_argument('--scenario', choices=list(CASES), default='T01')
    args = parser.parse_args()
    if run(['kubectl', 'config', 'current-context']).strip() != 'minikube':
        raise SystemExit('Select the local minikube context first.')
    if args.operation == 'inject':
        inject(args.scenario)
    elif args.operation == 'inspect':
        print(json.dumps(snapshot(), indent=2))
    elif args.operation == 'verify':
        print(verify())
    else:
        if args.operation == 'run-all':
            try:
                run_all()
            finally:
                restore()
        else:
            {'prepare': prepare, 'restore': restore}[args.operation]()
