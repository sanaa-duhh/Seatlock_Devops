#!/usr/bin/env bash
# One-time platform setup on a fresh EKS cluster created by terraform/.
# Installs the Ingress controller, monitoring and Argo CD, creates the app Secret, and
# hands the app to Argo CD, which deploys whatever helm/seatlock/values-eks.yaml says.
set -euo pipefail
cd "$(dirname "$0")/.."

tf() { terraform -chdir=terraform output -raw "$1"; }
region="$(tf region)"
cluster="$(tf cluster_name)"
mode="$(tf ingress_mode)"

aws eks update-kubeconfig --region "$region" --name "$cluster"
context="$(kubectl config current-context)"
[[ "$context" == *":cluster/$cluster" ]] || { echo "Unexpected kube context: $context" >&2; exit 1; }

echo "==> Namespaces and storage"
kubectl apply -f k8s/namespace.yaml
for ns in seatlock-monitoring seatlock-drill; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
done
kubectl apply -f k8s/storage-eks.yaml

echo "==> Application Secret (credentials kept in the git-ignored .env.eks)"
python3 scripts/kube-secret.py --namespace seatlock

echo "==> Grafana admin Secret and SeatLock dashboards"
python3 - <<'PY'
import json, subprocess
from pathlib import Path
env = dict(l.split('=', 1) for l in Path('.env.eks').read_text().splitlines() if '=' in l)
def apply(obj, server_side=False):
    cmd = ['kubectl', 'apply'] + (['--server-side'] if server_side else []) + ['-f', '-']
    subprocess.run(cmd, input=json.dumps(obj), text=True, check=True)
apply({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
       'metadata': {'name': 'monitoring-admin', 'namespace': 'seatlock-monitoring'},
       'stringData': {'username': 'admin', 'password': env['ADMIN_TOKEN']}}, server_side=True)
apply({'apiVersion': 'v1', 'kind': 'ConfigMap',
       'metadata': {'name': 'seatlock-dashboard', 'namespace': 'seatlock-monitoring',
                    'labels': {'grafana_dashboard': '1'}},
       'data': {'seatlock.json': Path('monitoring/dashboards/seatlock.json').read_text(),
                'seatlock-logs.json': Path('monitoring/logs-dashboard.json').read_text()}})
PY

echo "==> Helm charts: kube-prometheus-stack, Traefik ($mode mode) and Argo CD"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add traefik https://traefik.github.io/charts >/dev/null
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo update prometheus-community traefik argo >/dev/null
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.1.0 \
  -n seatlock-monitoring -f monitoring/kube-prometheus-values.yaml --wait --timeout 10m
traefik_values="k8s/traefik-values-eks.yaml"
[[ "$mode" == hostport ]] && traefik_values="k8s/traefik-values-eks-hostport.yaml"
helm upgrade --install traefik traefik/traefik --version 41.6.1 \
  -n ingress --create-namespace -f "$traefik_values" --wait --timeout 5m
helm upgrade --install argocd argo/argo-cd --version 10.10.3 \
  -n argocd --create-namespace -f k8s/argocd-values.yaml --wait --timeout 8m

echo "==> Loki and Alloy for request logs"
kubectl apply -f monitoring/logs.yaml

echo "==> Public address of the app"
host=""
for _ in $(seq 1 60); do
  if [[ "$mode" == hostport ]]; then
    host="$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')"
  else
    host="$(kubectl -n ingress get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  fi
  [[ -n "$host" ]] && break
  sleep 5
done
[[ -n "$host" ]] || { echo "No public address yet; rerun this script in a minute." >&2; exit 1; }

echo "==> Handing the app to Argo CD (allowed origin http://$host)"
sed "s#\${APP_ORIGIN}#http://$host#" gitops/application.yaml | kubectl apply -f -
for _ in $(seq 1 60); do
  status="$(kubectl -n argocd get application seatlock \
    -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null || true)"
  echo "   Argo CD: ${status:-pending}"
  [[ "$status" == "Synced/Healthy" ]] && break
  sleep 10
done

echo "==> GitHub variable for the CI rollout check"
if gh variable set APP_HOSTNAME --body "$host" 2>/dev/null; then
  echo "   APP_HOSTNAME=$host"
else
  echo "   Set the repository variable APP_HOSTNAME=$host (Settings -> Secrets and variables -> Actions)"
fi

cat <<MSG

Platform ready.
  App:      http://$host
  Argo CD:  kubectl -n argocd port-forward svc/argocd-server 8080:80   -> http://localhost:8080
            user admin; password:
            kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
  Grafana:  kubectl -n seatlock-monitoring port-forward svc/monitoring-grafana 3006:80
            user admin; password: ADMIN_TOKEN in .env.eks
MSG
