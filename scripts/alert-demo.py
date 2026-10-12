"""Observe an outage alert and recovery only in the isolated local drill namespace."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

KUBE = ['kubectl', '--context=minikube', '-n', 'seatlock-drill']
ROOT = Path(__file__).resolve().parents[1]
if subprocess.check_output(['kubectl','config','current-context'],text=True).strip() != 'minikube':
    raise SystemExit('Select local minikube first.')


def alerts():
    with urlopen('http://127.0.0.1:9091/api/v1/alerts',timeout=8) as response:
        data = json.load(response)
    return [a for a in data['data']['alerts'] if a['labels'].get('alertname') == 'SeatLockAPIUnavailable'
            and a['labels'].get('namespace') == 'seatlock-drill']


def stamp():
    return datetime.now(timezone.utc).isoformat()


def await_alert(firing):
    deadline = time.monotonic()+150
    while time.monotonic()<deadline:
        current = alerts()
        if (any(a['state']=='firing' for a in current) if firing else not current):
            return current
        time.sleep(5)
    raise RuntimeError('Expected alert state not observed within 150 seconds')


data = json.loads(subprocess.check_output(KUBE+['get','deployment','seatlock-backend','-o','json']))
replicas = data['spec']['replicas']
assert replicas >= 1
record = {'namespace':'seatlock-drill','context':'minikube','started_at':stamp(),'baseline':alerts()}
try:
    subprocess.run(KUBE+['scale','deployment/seatlock-backend','--replicas=0'],check=True)
    record['firing'] = await_alert(True)
    record['firing_observed_at'] = stamp()
    print('SeatLockAPIUnavailable firing for drill namespace.',flush=True)
finally:
    subprocess.run(KUBE+['scale','deployment/seatlock-backend','--replicas='+str(replicas)],check=True)
    subprocess.run(KUBE+['rollout','status','deployment/seatlock-backend','--timeout=90s'],check=True)
    record['after'] = await_alert(False)
    record['recovered_at'] = stamp()
    (ROOT/'docs/evidence/alert-recovery.json').write_text(json.dumps(record,indent=2)+'\n')
print('Outage alert recovered; normal demonstration namespace was preserved.')
