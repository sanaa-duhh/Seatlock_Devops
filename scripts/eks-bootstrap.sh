#!/usr/bin/env bash
# One-time platform setup on a fresh EKS cluster created by terraform/.
# Installs the Ingress controller and monitoring, creates the app Secret, and prints
# the GitHub settings the CI deploy job needs.
set -euo pipefail
cd "$(dirname "$0")/.."

tf() { terraform -chdir=terraform output -raw "$1"; }
region="$(tf region)"
cluster="$(tf cluster_name)"
mode="$(tf ingress_mode)"
auth="$(tf github_deploy_auth)"

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

echo "==> Helm charts: kube-prometheus-stack and Traefik ($mode mode)"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add traefik https://traefik.github.io/charts >/dev/null
helm repo update prometheus-community traefik >/dev/null
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.1.0 \
  -n seatlock-monitoring -f monitoring/kube-prometheus-values.yaml --wait --timeout 10m
traefik_values="k8s/traefik-values-eks.yaml"
[[ "$mode" == hostport ]] && traefik_values="k8s/traefik-values-eks-hostport.yaml"
helm upgrade --install traefik traefik/traefik --version 41.6.1 \
  -n ingress --create-namespace -f "$traefik_values" --wait --timeout 5m

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

cat <<EOF

Platform ready. App URL after the first deploy: http://$host

Add these in GitHub -> repository Settings -> Secrets and variables -> Actions:

  Variables tab
    EKS_CLUSTER_NAME = $cluster
    AWS_REGION       = $region
    APP_HOSTNAME     = $host
EOF
if [[ "$auth" == oidc ]]; then
  cat <<EOF
    AWS_DEPLOY_ROLE_ARN = $(tf github_deploy_role_arn)
EOF
else
  cat <<'EOF'

  Secrets tab (copy each value from the command shown; never paste it into chat):
    AWS_ACCESS_KEY_ID     <- terraform -chdir=terraform output -raw github_deploy_access_key_id | pbcopy
    AWS_SECRET_ACCESS_KEY <- terraform -chdir=terraform output -raw github_deploy_secret_access_key | pbcopy
EOF
fi
cat <<'EOF'

Then trigger a deploy: Actions -> CI/CD -> Run workflow (main), or push a commit.
EOF
