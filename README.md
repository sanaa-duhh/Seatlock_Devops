# SeatLock

**An event-ticketing app where two people can never book the same seat, shipped through a
production-style DevOps platform:** tested and security-scanned in GitHub Actions, packaged
as SHA-tagged images in GHCR, provisioned on AWS EKS with Terraform, deployed with Helm
by a namespace-scoped CI identity, and observed with Prometheus, Grafana and Loki.

[![CI/CD](https://github.com/OWNER/seatlock/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/seatlock/actions/workflows/ci.yml)

![SeatLock running behind the Kubernetes Ingress](docs/screenshots/e2e/seatlock-ingress-desktop.png)

## Highlights

- **Correct under concurrency.** Seat holds use ordered PostgreSQL row locks inside one
  transaction, so competing buyers on different API replicas cannot double-book. The test
  suite runs real competing transactions to prove it.
- **Thirteen pipeline gates.** Lint, format, pytest (88% coverage), Bandit, pip-audit,
  npm audit, Gitleaks over the full history, Terraform validate, Helm lint, Trivy IaC scan,
  a Trivy image scan of both images, Playwright on Docker Compose, and Playwright again on
  a throwaway kind cluster. All of them must pass before anything is published.
- **Build once, deploy the same bytes.** Each image is built once, tagged with the commit
  SHA, scanned, tested in Kubernetes, then pushed to GHCR and deployed. Every running Pod
  traces back to the commit it came from, and the UI shows that commit.
- **Least-privilege deploys.** By default GitHub Actions assumes a one-hour AWS role through
  OIDC, trusted only for this repo's `production` environment, so no AWS keys are stored.
  The CI identity can only describe the cluster and touch the `seatlock` namespace. For
  AWS accounts whose policies forbid OIDC providers, one Terraform variable switches to a
  deploy-only IAM user whose key is destroyed with the cluster.
- **Hardened runtime.** Non-root containers, read-only root filesystems, all capabilities
  dropped, and startup, liveness and readiness probes with distinct meanings. A failed
  rollout reverts itself (`helm upgrade --rollback-on-failure`).
- **Real findings, fixed.** Scanning found 46 HIGH CVEs in the original backend image and a
  libtiff CVE hidden by a stale build cache. Both were fixed without suppressions; see
  [security/README.md](security/README.md).
- **Operability.** HPA scaling 2→4 under load, a Grafana dashboard of request rate, p95
  latency, errors and seat conflicts, request-ID logs in Loki, and fault-injection drills
  with recorded recoveries.

## Architecture

```mermaid
flowchart LR
    Dev[Developer] -->|git push| GH[GitHub]
    GH --> CI[GitHub Actions<br/>test · scan · kind deploy]
    CI -->|SHA-tagged images| GHCR[(GHCR)]
    CI -->|scoped deploy identity, helm upgrade| EKS
    TF[Terraform] -->|VPC, EKS, IAM| AWS
    subgraph AWS [AWS ap-southeast-2]
      subgraph EKS [EKS cluster]
        Ingress[Traefik Ingress] -->|/| FE[frontend x2]
        Ingress -->|/api| BE[backend x2-5 HPA]
        BE --> PG[(PostgreSQL<br/>gp3 volume)]
        Prom[Prometheus] --> BE
        Prom --> Graf[Grafana]
      end
      NLB[NLB, or node port 80] --> Ingress
    end
    GHCR -.->|pull| EKS
    User[Browser] --> NLB
```

Design decisions and the booking state machine are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tech stack

| Area | Tools |
|---|---|
| Frontend | React 19, TypeScript, Vite, served by unprivileged Nginx |
| Backend | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 15, prometheus-client |
| Testing | Pytest (real PostgreSQL), Playwright (desktop + mobile) |
| Containers | Docker multi-stage builds, Docker Compose |
| CI/CD | GitHub Actions, GHCR, Dependabot |
| Security | Trivy (images + IaC), Gitleaks, Bandit, pip-audit, npm audit |
| Infrastructure | Terraform (terraform-aws-modules VPC + EKS), AWS EKS, EBS CSI, EKS Pod Identity, IAM OIDC |
| Kubernetes | Helm, Traefik Ingress, HPA + metrics-server, StatefulSet + PVC |
| Observability | kube-prometheus-stack (Prometheus, Grafana, Alertmanager), Loki, Grafana Alloy |

## Repository layout

```text
backend/            FastAPI app, Alembic migrations, pytest suite, Dockerfile
frontend/           React app, Playwright tests, Nginx config, Dockerfile
docker-compose.yml  Local stack: postgres → migrate → backend → frontend
.github/workflows/  CI/CD pipeline
terraform/          AWS VPC, EKS, node group, add-ons, GitHub deploy identity
k8s/                Namespace, EKS StorageClass, Ingress controller values
helm/seatlock/      Application chart (values.yaml local, values-eks.yaml cloud)
monitoring/         Prometheus/Grafana values, dashboards, alerts, Loki/Alloy
troubleshooting/    Deliberately broken manifests with diagnosis guides
scripts/            EKS bootstrap/teardown, load, drills, backup/restore
security/           Gate policy, findings and scan reports
docs/               Architecture, drill records, screenshots
```

## Quick start (local)

Requirements: Docker with Compose, Python 3.11, Node 24, `make`.

```bash
make up          # generates a private .env, builds and starts all services
```

| URL | What |
|---|---|
| http://localhost:3000 | SeatLock UI |
| http://localhost:8000/docs | Swagger UI for the API |
| http://localhost:8000/health, `/ready`, `/metrics` | liveness, readiness, Prometheus metrics |

`make monitoring` adds Prometheus (http://localhost:9090) and Grafana
(http://localhost:3002, user `admin`, password = `ADMIN_TOKEN` in `.env`).
`make down` stops everything and keeps the data; `docker compose down -v` also deletes it.
Run `make help` for every shortcut.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/events`, `/api/events/{id}`, `/api/events/{id}/seats` | Browse events and live seat availability |
| POST | `/api/holds` | Hold up to six seats for five minutes (all-or-nothing) |
| GET | `/api/holds/{id}` | Hold status and countdown |
| POST | `/api/holds/{id}/confirm` | Confirm a booking (retry-safe) |
| DELETE | `/api/holds/{id}` | Release a hold |
| GET | `/api/bookings` | The current guest's tickets |
| POST | `/api/bookings/{id}/cancel` | Cancel a booking |
| POST / PUT | `/api/events`, `/api/events/{id}` | Organizer create and update (admin token) |
| GET | `/health`, `/ready`, `/metrics` | Probes and metrics |

## Testing

```bash
make test        # 28 pytest tests against a throwaway PostgreSQL, 88% coverage
make lint        # ruff, bandit, prettier, terraform fmt, helm lint
make e2e         # Playwright booking journey on desktop and mobile (stack must be up)
make scan        # Trivy image + IaC scan, same policy as CI
```

The pytest fixtures refuse to run against anything except the dedicated test database,
so the demo data can never be truncated by a test run.

## CI/CD pipeline

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and every
push to `main`:

```text
backend tests + SAST ─┐
frontend build ───────┼─► build + Trivy-scan images (:SHA) ─┐
IaC + secret scan ────┘                                     ├─► Helm on kind + Playwright ─► push to GHCR ─► deploy to EKS
                         Playwright on Docker Compose ──────┘                                 (main only)     (main only)
```

- A failing test or a HIGH/CRITICAL vulnerability stops the pipeline before anything is
  pushed.
- Images are tagged only with the full commit SHA, for example
  `ghcr.io/OWNER/seatlock-backend:<sha>`.
- The deploy job runs `helm upgrade --rollback-on-failure`, then smoke-tests the public URL
  and checks that the running image tag matches the commit. It skips itself when no cluster
  exists, so the pipeline stays green between demos.
- Actions are pinned to commit SHAs; scanner images are pinned by digest.

## Kubernetes and Helm

The chart in [`helm/seatlock`](helm/seatlock) deploys:

- frontend and backend Deployments with 2 replicas each (the backend autoscales 2→5 on
  CPU through an HPA)
- ClusterIP Services for both
- an Ingress routing `/` to the frontend and `/api` to the backend
- PostgreSQL as a StatefulSet with a persistent volume
- a migration Job per release
- a ConfigMap, and Secret references
- a ServiceMonitor and alert rules

**Local (minikube):**

```bash
minikube start --cpus=4 --memory=6000 && minikube addons enable metrics-server
make k8s-local                      # builds, loads images, installs the chart
bash scripts/local-platform.sh      # optional: Traefik, Prometheus/Grafana, Loki/Alloy
kubectl -n seatlock get pods,svc,hpa,ingress
```

## AWS: Terraform, EKS and deployment

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars   # set github_repository
make tf-plan       # terraform init + plan
make eks-up        # apply (~15 min), then scripts/eks-bootstrap.sh
#                    add the printed variables/secrets in GitHub, then:
#                    Actions -> CI/CD -> Run workflow   (first deploy)
make eks-down      # delete LB + volumes, terraform destroy, check for leftovers
```

Terraform creates:

- a VPC with two public and two private subnets across two AZs
- an EKS 1.37 cluster with a managed node group (2 × t3.medium)
- the CoreDNS, kube-proxy, VPC CNI, metrics-server and Pod Identity add-ons
- the EBS CSI driver, which gets its AWS permissions through EKS Pod Identity rather than
  an IAM OIDC provider
- the GitHub deploy identity

`eks-bootstrap.sh` then installs Traefik, kube-prometheus-stack and Loki, creates the app
Secret, and prints the GitHub settings the deploy job needs.

Two settings adapt the same code to what an AWS account allows:

| Variable | Default | Alternative |
|---|---|---|
| `ingress_mode` | `nlb`: private nodes, NAT gateway, Traefik behind an AWS Network Load Balancer (about $0.31/h in Sydney) | `hostport`: nodes in public subnets, Traefik on port 80 of each node, no NAT or LB (about $0.22/h) |
| `github_deploy_auth` | `oidc`: keyless, short-lived role sessions | `access_key`: deploy-only IAM user, key stored as GitHub secrets, destroyed with the cluster |

The recorded demo ran in an AWS account whose organization policies allow a single region
(`ap-southeast-2`) and forbid IAM OIDC providers, and where load balancer creation was not
yet enabled. It therefore used `hostport` and `access_key`; the probes that found these
limits are described under *Lessons learned*.

`make eks-down` removes any Kubernetes-created load balancer and the EBS volumes *before*
`terraform destroy`, so the VPC deletion does not stall and no orphaned disks keep billing.
It finishes by listing leftover clusters, volumes, load balancers, NAT gateways and
Elastic IPs, all of which should be empty.

## Monitoring

- The backend exports `seatlock_http_requests_total`, `seatlock_http_duration_seconds`,
  `seatlock_seat_conflicts_total` and `seatlock_bookings_confirmed_total`.
- A ServiceMonitor makes Prometheus scrape every backend replica.
- The **SeatLock: Booking Reliability** Grafana dashboard shows request rate, p95 latency,
  5xx rate, seat conflicts, confirmations and scrape availability.
- Alerts fire when the API is unreachable or returning server errors.
- Alloy ships JSON request logs to Loki; each log line carries the request ID that the API
  also returns in the `X-Request-ID` header.

```bash
kubectl -n seatlock-monitoring port-forward svc/monitoring-grafana 3006:80
python3 scripts/load.py --url http://<app-host>/api/events/1/seats --seconds 120 --workers 16   # watch: kubectl -n seatlock get hpa -w
```

![Grafana dashboard with live SeatLock metrics](docs/screenshots/monitoring/grafana-kubernetes.png)

## Troubleshooting

- [`troubleshooting/`](troubleshooting/README.md) has four broken manifests to diagnose by
  hand, each with symptoms, commands and the fix:
  - ImagePullBackOff
  - a Service with no endpoints
  - a failing readiness probe
  - a missing Secret key
- `scripts/drill.sh run-all` injects faults into a full SeatLock release, captures the
  evidence, restores it and re-verifies a booking. The recorded runs, including a combined
  three-fault incident, are in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Lessons learned

- **Locks belong in the database.** A client-side countdown cannot stop two replicas
  selling one seat. Ordered row locks and rechecking expiry *after* acquiring them can.
- **A dependency audit is not an image scan.** pip-audit was clean while the image carried
  44 vulnerable OS packages and old build tools. Switching to an Alpine base and removing
  pip/wheel from the runtime fixed it.
- **A cached image can be a stale image.** A clean scan of a cached `apk upgrade` layer hid
  a libtiff CVE that a fresh build fixed. Security scans should run on fresh builds.
- **Read-only root filesystems need testing.** Turning them on broke nothing in the
  manifests' YAML but would have broken nginx and Postgres without the right scratch mounts.
  Redeploying and re-running the browser tests is what proved the change safe.
- **Terraform doesn't know what Kubernetes created.** Load balancers and volumes made by the
  cluster must be removed before `terraform destroy`, or teardown stalls and keeps billing.
- **Every AWS account has its own guardrails.** The demo account's organization allowed one
  region, denied IAM OIDC providers, and had load balancers disabled. Free probes found each
  limit before anything was created: `--dry-run` calls, and deliberately invalid requests
  whose error type shows whether the policy allows the action. The infrastructure was made
  switchable (`ingress_mode`, `github_deploy_auth`, Pod Identity instead of IRSA) instead of
  being rewritten for one account.
- **Advertised capacity isn't real capacity.** minikube reported more memory than its Docker
  container actually had, which showed up as Grafana probe failures until the limits were
  measured and raised.

## Capstone rubric map

<details>
<summary>Where each graded item lives</summary>

| Module | Evidence in this repo |
|---|---|
| M1 Application | `backend/app/`, `backend/alembic/versions/0001_seatlock.py`, `backend/requirements.txt`, `frontend/`, `docker-compose.yml`, [screenshots](docs/screenshots/e2e/) |
| M2 Testing | `backend/tests/` (28 tests across 10+ endpoints), `backend/pytest.ini`, `backend/tests/conftest.py` (isolated test DB) |
| M3 Git/GitHub | this repository, its commit history, `.gitignore` |
| M4 Docker | `backend/Dockerfile`, `frontend/Dockerfile` (Node build → Nginx), non-root users, `docker-compose.yml` on http://localhost:3000 |
| M5 CI/CD | `.github/workflows/ci.yml`: push to `main`, pytest gate, frontend build, both images, GHCR push, SHA tags |
| M6 Trivy | `image` job in `ci.yml` (both images, `--exit-code 1` on HIGH/CRITICAL), [findings explained](security/README.md) |
| M7 Terraform | `terraform/*.tf`, `terraform/terraform.tfvars.example`, `scripts/eks-teardown.sh` |
| M8 Kubernetes/Helm | `k8s/namespace.yaml`, `helm/seatlock/` (Chart, values, templates), 2+ replicas, ClusterIP Services, Ingress `/` + `/api`, HPA |
| M9 Observability | `/metrics`, `monitoring/kube-prometheus-values.yaml`, ServiceMonitor, `monitoring/dashboards/seatlock.json` |
| M10 Docs/demo | this README; the live demo is a commit → pipeline → new SHA visible in the UI |

</details>
