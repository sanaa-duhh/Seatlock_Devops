#!/usr/bin/env bash
# Install only the local monitoring/Ingress platform, using fixed chart versions.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(kubectl config current-context)" == minikube ]] || { echo 'Select local minikube first.' >&2; exit 1; }
python3 scripts/configure.py
kubectl --context=minikube apply -f k8s/namespace.yaml
# The full platform needs more resources than the small app-only demo.
if docker inspect minikube >/dev/null 2>&1; then
  python3 - <<'PY'
import json, subprocess
host = json.loads(subprocess.check_output(['docker','inspect','minikube']))[0]['HostConfig']
cpu, memory = host.get('NanoCpus', 0), host.get('Memory', 0)
if (cpu and cpu < 4_000_000_000) or (memory and memory < 6000*1024*1024):
    raise SystemExit('Full local platform needs at least 4 CPUs / 6000 MiB; see README resource setup.')
PY
fi
kubectl --context=minikube create namespace seatlock-monitoring --dry-run=client -o yaml | kubectl --context=minikube apply -f -
python3 - <<'PY'
import json, subprocess
from pathlib import Path
values = dict(line.split('=',1) for line in Path('.env').read_text().splitlines() if '=' in line)
secret = {'apiVersion':'v1','kind':'Secret','metadata':{'name':'monitoring-admin','namespace':'seatlock-monitoring'},
          'type':'Opaque','stringData':{'username':'admin','password':values['ADMIN_TOKEN']}}
subprocess.run(['kubectl','--context=minikube','apply','--server-side','-f','-'], input=json.dumps(secret),text=True,check=True)
dashboard = {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'seatlock-dashboard','namespace':'seatlock-monitoring',
             'labels':{'grafana_dashboard':'1'}},'data':{'seatlock.json':Path('monitoring/dashboards/seatlock.json').read_text(),
             'seatlock-logs.json':Path('monitoring/logs-dashboard.json').read_text()}}
subprocess.run(['kubectl','--context=minikube','apply','-f','-'],input=json.dumps(dashboard),text=True,check=True)
PY
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add traefik https://traefik.github.io/charts
helm repo update prometheus-community traefik
helm_flags=()
if [[ "$(helm version --short)" == v4.* ]]; then
  helm_flags+=(--force-conflicts)
fi
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.1.0 \
  --kube-context minikube -n seatlock-monitoring -f monitoring/kube-prometheus-values.yaml --wait --timeout 8m "${helm_flags[@]}"
helm upgrade --install seatlock-ingress traefik/traefik --version 41.6.1 \
  --kube-context minikube -n seatlock-ingress --create-namespace -f k8s/traefik-values.yaml --wait --timeout 3m "${helm_flags[@]}"
kubectl --context=minikube create namespace seatlock-drill --dry-run=client -o yaml | kubectl --context=minikube apply -f -
kubectl --context=minikube apply -f monitoring/logs.yaml
kubectl --context=minikube -n seatlock-monitoring rollout status statefulset/seatlock-loki --timeout=4m
kubectl --context=minikube -n seatlock-monitoring rollout status deployment/seatlock-alloy --timeout=4m
