#!/usr/bin/env bash
# Only an ephemeral Linux x86_64 GitHub runner. Binaries have fixed release hashes.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo 'This bootstrap targets an ephemeral Linux x86_64 GitHub runner.' >&2
  exit 1
}
seatlock_tools="$RUNNER_TEMP/seatlock-tools"
seatlock_bin="$RUNNER_TEMP/seatlock-bin"
mkdir -p "$seatlock_tools" "$seatlock_bin"
curl --fail --location --retry 3 --output "$seatlock_tools/kind" \
  https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64
printf '%s  %s\n' aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d "$seatlock_tools/kind" | sha256sum --check -
curl --fail --location --retry 3 --output "$seatlock_tools/helm.tar.gz" \
  https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz
printf '%s  %s\n' 86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb "$seatlock_tools/helm.tar.gz" | sha256sum --check -
tar -xzf "$seatlock_tools/helm.tar.gz" -C "$seatlock_tools"
install -m 755 "$seatlock_tools/kind" "$seatlock_bin/kind"
install -m 755 "$seatlock_tools/linux-amd64/helm" "$seatlock_bin/helm"
printf '%s\n' "$seatlock_bin" >> "$GITHUB_PATH"
