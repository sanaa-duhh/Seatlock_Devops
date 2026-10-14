#!/usr/bin/env bash
# Remove everything that costs money, in the order AWS needs.
#
# Kubernetes creates some AWS resources itself (a Network Load Balancer for the Ingress
# in nlb mode, EBS volumes for PVCs). Terraform does not know about them, so if they
# still exist, `terraform destroy` stalls on the VPC and the disks keep billing.
# Delete them through Kubernetes first, then destroy the infrastructure.
set -euo pipefail
cd "$(dirname "$0")/.."

region="$(terraform -chdir=terraform output -raw region)"
cluster="$(terraform -chdir=terraform output -raw cluster_name)"
vpc="$(terraform -chdir=terraform output -raw vpc_id)"

if aws eks describe-cluster --region "$region" --name "$cluster" >/dev/null 2>&1; then
  aws eks update-kubeconfig --region "$region" --name "$cluster" >/dev/null
  echo "==> Removing workloads that own AWS load balancers and volumes"
  # Deleting the Argo CD Application (it has a finalizer) removes everything it deployed.
  kubectl -n argocd delete application seatlock --wait=true --timeout=5m 2>/dev/null || true
  helm uninstall argocd -n argocd --wait 2>/dev/null || true
  helm uninstall traefik -n ingress --wait 2>/dev/null || true
  kubectl delete -f monitoring/logs.yaml --ignore-not-found --wait=true || true
  helm uninstall monitoring -n seatlock-monitoring --wait 2>/dev/null || true
  # StatefulSet volume claims survive their StatefulSet by design; delete them explicitly.
  kubectl delete pvc --all -n seatlock --wait=true || true
  kubectl delete pvc --all -n seatlock-monitoring --wait=true || true

  echo "==> Waiting for any Kubernetes-created load balancer to disappear"
  for _ in $(seq 1 40); do
    count="$(aws elbv2 describe-load-balancers --region "$region" \
      --query "length(LoadBalancers[?VpcId=='$vpc'])" --output text 2>/dev/null || echo 0)"
    [[ "$count" == "0" ]] && break
    sleep 10
  done
fi

echo "==> Disabling the CI rollout check (it skips while APP_HOSTNAME is unset)"
gh variable delete APP_HOSTNAME 2>/dev/null || echo "   Delete the APP_HOSTNAME repository variable in GitHub, if set."

echo "==> terraform destroy"
terraform -chdir=terraform destroy -auto-approve

echo "==> Leftover check (every line should be empty)"
echo "EKS clusters:   $(aws eks list-clusters --region "$region" --query 'clusters' --output text)"
echo "EBS volumes:    $(aws ec2 describe-volumes --region "$region" \
  --filters Name=tag-key,Values=kubernetes.io/created-for/pvc/name --query 'Volumes[].VolumeId' --output text)"
echo "Load balancers: $(aws elbv2 describe-load-balancers --region "$region" --query 'LoadBalancers[].LoadBalancerName' --output text 2>/dev/null)"
echo "NAT gateways:   $(aws ec2 describe-nat-gateways --region "$region" \
  --filter Name=state,Values=available,pending --query 'NatGateways[].NatGatewayId' --output text)"
echo "Elastic IPs:    $(aws ec2 describe-addresses --region "$region" --query 'Addresses[].PublicIp' --output text)"
