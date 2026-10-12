#!/usr/bin/env bash
# One-time platform setup on a fresh EKS cluster created by terraform/.
# Installs the Ingress controller and monitoring, creates the app Secret, and
# hands the deploy settings to GitHub so the CI deploy job can take over.
set -euo pipefail
cd "$(dirname "$0")/.."

region="$(terraform -chdir=terraform output -raw region)"
cluster="$(terraform -chdir=terraform output -raw cluster_name)"
role_arn="$(terraform -chdir=terraform output -raw github_deploy_role_arn)"

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

echo "==> Helm charts: kube-prometheus-stack and Traefik"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add traefik https://traefik.github.io/charts >/dev/null
helm repo update prometheus-community traefik >/dev/null
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.1.0 \
  -n seatlock-monitoring -f monitoring/kube-prometheus-values.yaml --wait --timeout 10m
helm upgrade --install traefik traefik/traefik --version 41.6.1 \
  -n ingress --create-namespace -f k8s/traefik-values-eks.yaml --wait --timeout 5m

echo "==> Loki and Alloy for request logs"
kubectl apply -f monitoring/logs.yaml

echo "==> Waiting for the Network Load Balancer hostname"
host=""
for _ in $(seq 1 60); do
  host="$(kubectl -n ingress get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  [[ -n "$host" ]] && break
  sleep 5
done
[[ -n "$host" ]] || { echo "Load balancer hostname not assigned yet; rerun later." >&2; exit 1; }

echo "==> GitHub variables for the deploy job (the production environment scopes the OIDC trust)"
repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
gh api -X PUT "repos/$repo/environments/production" >/dev/null
gh variable set AWS_REGION --body "$region"
gh variable set EKS_CLUSTER_NAME --body "$cluster"
gh variable set AWS_DEPLOY_ROLE_ARN --body "$role_arn"
gh variable set APP_HOSTNAME --body "$host"

cat <<EOF

Platform ready.
  App URL (after the first deploy): http://$host
  Next: gh workflow run ci.yml --ref main   (or push a commit)
EOF
