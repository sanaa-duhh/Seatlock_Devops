#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 2 || ! "$1" =~ ^[a-z0-9][a-z0-9-]*$ || ! "$2" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Usage: scripts/publish.sh lowercase-github-owner full-source-commit-sha' >&2
  exit 2
fi
owner="$1"
source_sha="$2"
mkdir -p .artifacts
for component in backend frontend; do
  image="seatlock-${component}:${source_sha}"
  docker image inspect "$image" >/dev/null
  # Re-scan loaded artifacts before this manual publication boundary.
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.75.0 \
    image --severity HIGH,CRITICAL --exit-code 1 "$image"
done
for component in backend frontend; do
  remote="ghcr.io/${owner}/seatlock-${component}:${source_sha}"
  docker tag "seatlock-${component}:${source_sha}" "$remote"
  docker push "$remote"
  docker inspect --format '{{json .RepoDigests}}' "$remote" > ".artifacts/${component}-digests.json"
done
echo 'Published scanned images; digests saved in .artifacts/.'
