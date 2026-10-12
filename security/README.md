# Security gates and findings

Every gate runs in CI on every push and pull request, and fails the pipeline when it fires.

| Gate | Tool | Fails on |
|---|---|---|
| SAST | Bandit | medium or high severity in `backend/app` |
| Python dependencies | pip-audit | any known vulnerability in `requirements.txt` |
| Frontend dependencies | npm audit | high or critical |
| Secrets | Gitleaks | any secret in the full Git history |
| Container images | Trivy | any HIGH or CRITICAL, fixed or unfixed, in either image |
| IaC misconfiguration | Trivy config | HIGH or CRITICAL in Terraform, Helm or Dockerfiles, except the documented entries in [`.trivyignore`](../.trivyignore) |

`scripts/check-security-gates.py` also checks that the scanners themselves still work.
It plants a fake GitHub token and an unsafe `shell=True` call in a temp directory, and
fails unless Gitleaks and Bandit both catch them.

## Findings and what was done about them

### 1. Backend image: 46 HIGH on a Debian base, fixed by changing base image

The first backend image used a Debian 13 based `python:3.11` image. Trivy reported **46 HIGH**:

- 44 in Debian OS packages the API never uses (`util-linux` libraries, `login`, `ncurses`,
  `systemd` libs), for example CVE-2026-16742.
- 2 in Python build tooling left in the runtime image: `wheel` (CVE-2026-24049) and
  `jaraco.context` (CVE-2026-23949).

**Fix:** switch to `python:3.11-alpine`, run `apk upgrade`, and uninstall
`pip`/`setuptools`/`wheel` after installing dependencies, since nothing installs packages
at runtime. Result: **0 HIGH/CRITICAL**, and no suppressions were added. Reports:
[before](reports/backend-before-hardening.json), [after](reports/backend.json).

**Lesson:** pip-audit passed the whole time, because it checks only `requirements.txt`.
Image scanning catches the OS layer and leftover build tools, which a dependency audit never sees.

### 2. Frontend image: CVE-2026-4775 in libtiff, caught by a stale build cache

A rescan on 13 October found **1 HIGH**: `tiff 4.7.1-r0`, CVE-2026-4775 (signed-integer
overflow that can lead to code execution or denial of service from a crafted TIFF). libtiff
comes from the nginx base image. Alpine had already published `4.7.2-r0`, and the
Dockerfile runs `apk upgrade`, but the local build reused a cached layer from before the fix.

**Fix:** rebuild without cache. `tiff-4.7.2-r0` was installed and the rescan was clean.
CI always builds from scratch, and `make scan` now uses `--no-cache` too. Scan output:
[cve-2026-4775.txt](cve-2026-4775.txt).

**Lesson:** a passing scan of a cached image can be stale. Rebuilding regularly (and
Dependabot bumping the pinned base-image digests) is part of keeping images patched.

### 3. Kubernetes manifests: writable root filesystems

Trivy config flagged every container (KSV-0014) for a writable root filesystem. All six
(backend, frontend, migration Job, PostgreSQL, Loki, Alloy) now run with
`readOnlyRootFilesystem: true`, with `emptyDir` mounts only for the scratch paths each one
needs. This was verified on minikube by redeploying and passing the browser tests through
the Ingress.

### 4. Accepted risks

| ID | Finding | Why it is accepted |
|---|---|---|
| AWS-0040 / AWS-0041 | EKS API endpoint is public | GitHub-hosted runners have no fixed IPs. Every request is still IAM-authenticated, and the CI role is limited to one namespace. Narrow `cluster_endpoint_public_access_cidrs` for laptop-only use. |
| AWS-0104 | Node security group allows all egress | Nodes must reach GHCR, ECR and AWS APIs through the NAT gateway. |

## Reports in this folder

`reports/` holds the dated JSON output of each tool: Trivy (`backend*.json`,
`frontend.json`), Bandit, pip-audit, npm audit, Gitleaks and the scanner self-test.
Fresh reports from every CI run are attached to the run as artifacts (`trivy-backend`,
`trivy-frontend`).
