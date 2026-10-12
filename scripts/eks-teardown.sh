#!/usr/bin/env bash
# Remove everything that costs money, in the order AWS needs.
#
# Kubernetes creates some AWS resources itself (the Network Load Balancer for the
# Ingress, EBS volumes for PVCs). Terraform does not know about them, so if they
# still exist, `terraform destroy` stalls on the VPC and the disks keep billing.
# Delete them through Kubernetes first, then destroy the infrastructure.
set -euo pipefail
cd "$(dirname "$0")/.."

region="$(terraform -chdir=terraform output -raw region)"
cluster="$(terraform -chdir=terraform output -raw cluster_name)"

if aws eks describe-cluster --region "$region" --name "$cluster" >/dev/null 2>&1; then
  aws eks update-kubeconfig --region "$region" --name "$cluster" >/dev/null
  echo "==> Removing workloads that own AWS load balancers and volumes"
  helm uninstall seatlock -n seatlock --wait 2>/dev/null || true
  helm uninstall traefik -n ingress --wait 2>/dev/null || true
  kubectl delete -f monitoring/logs.yaml --ignore-not-found --wait=true || true
  helm uninstall monitoring -n seatlock-monitoring --wait 2>/dev/null || true
  # StatefulSet volume claims survive helm uninstall by design; delete them explicitly.
  kubectl delete pvc --all -n seatlock --wait=true || true
  kubectl delete pvc --all -n seatlock-monitoring --wait=true || true

  echo "==> Waiting for the load balancer to disappear"
  vpc="$(terraform -chdir=terraform output -raw vpc_id)"
  for _ in $(seq 1 40); do
    count="$(aws elbv2 describe-load-balancers --region "$region" \
      --query "length(LoadBalancers[?VpcId=='$vpc'])" --output text)"
    [[ "$count" == "0" ]] && break
    sleep 10
  done
fi

echo "==> Disabling the CI deploy job (it skips while EKS_CLUSTER_NAME is unset)"
gh variable delete EKS_CLUSTER_NAME 2>/dev/null || true

echo "==> terraform destroy"
terraform -chdir=terraform destroy -auto-approve

echo "==> Leftover check (all should be empty)"
aws ec2 describe-volumes --region "$region" \
  --filters "Name=tag-key,Values=kubernetes.io/created-for/pvc/name" --query 'Volumes[].VolumeId' --output text
aws eks list-clusters --region "$region" --query 'clusters' --output text
