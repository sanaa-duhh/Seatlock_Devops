# SeatLock architecture and decisions

## System overview

```mermaid
flowchart LR
    User[Browser] -->|HTTP| LB[AWS NLB]
    LB --> Traefik[Traefik Ingress]
    Traefik -->|/| FE[frontend x2<br/>Nginx + React]
    Traefik -->|/api| BE[backend x2-5<br/>FastAPI, HPA]
    FE -.->|/api proxy| BE
    BE --> PG[(PostgreSQL<br/>StatefulSet + gp3 EBS)]
    Prom[Prometheus] -->|ServiceMonitor /metrics| BE
    Prom --> Graf[Grafana]
    Alloy -->|pod logs| Loki --> Graf
```

Everything inside the cluster runs in private subnets. Only the load balancer sits in the
public subnets. One release of the Helm chart owns the application; the Ingress controller
and monitoring stack are separate platform releases installed once by `scripts/eks-bootstrap.sh`.

## Booking correctness

The browser displays availability and a countdown; PostgreSQL decides who owns a seat. Every API replica uses the same database and transaction rules.

1. Acquire a shared event-row lock. Buyers can share it, while an organizer edit waits.
2. Lock all requested seat rows in ascending ID order, avoiding inconsistent multi-seat lock ordering.
3. Recheck event start time and hold expiry after obtaining the locks.
4. Reject the entire request if any seat is booked or actively held. Otherwise insert a hold, assign every seat, and add its audit entry in one transaction.
5. Confirmation locks the hold and its allocated seats, checks expiry/allocation, and records a stable reference. Retrying confirmation returns that reference.
6. Release/cancellation locks the hold and its seats, clears only its current allocation, and commits an audit event with the state change.

~~~mermaid
stateDiagram-v2
    [*] --> Active: atomically acquire seats
    Active --> Confirmed: confirm before expiry
    Active --> Released: release
    Active --> Expired: server time passes expiry
    Expired --> [*]: seats can be reassigned
    Confirmed --> Confirmed: retry returns same reference
    Confirmed --> Cancelled: cancel before event starts
    Cancelled --> Cancelled: retry succeeds
    Released --> Released: retry succeeds
~~~

Expiry is a derived state for an active hold. A worker is unnecessary for inventory correctness: availability and acquisition both check the server timestamp. Old holds/audit records remain as history. A stale holder cannot confirm seats that have been reassigned.

Money is stored in integer paise and snapshotted per hold. The UI shows that snapshot after reservation and preserves fractional rupees. Organizer title/date edits are refused after any reservation; shared event locks close the race between that check and a buyer creating the first hold.

## Delivery pipeline

```mermaid
flowchart LR
    Push[git push main] --> T[backend: ruff, pytest, bandit, pip-audit]
    Push --> F[frontend: prettier, npm audit, build]
    Push --> I[iac: gitleaks, terraform validate, helm lint, trivy config]
    T & F & I --> B[build images :SHA<br/>trivy image gate]
    T & F --> E[Playwright on Compose]
    B & E --> K[kind cluster: helm install + Playwright]
    K --> P[push to GHCR :SHA]
    P --> D[EKS: OIDC role, helm upgrade,<br/>rollback on failure, smoke test]
```

- **Build once, promote the same bytes.** Each image is built a single time, scanned, saved as
  a workflow artifact, tested in kind, and only then pushed. GHCR receives exactly the image
  that passed every gate, never a rebuild.
- **Commit SHA tags only.** `ghcr.io/<owner>/seatlock-backend:<sha>` maps any running Pod back
  to its source commit. There is no `latest` tag to drift.
- **No long-lived cloud credentials.** The deploy job exchanges GitHub's OIDC token for a
  one-hour AWS role session. The IAM trust policy accepts only this repository's
  `production` environment, and the EKS access entry limits that role to the `seatlock`
  namespace.
- **Safe rollout.** `helm upgrade --rollback-on-failure --wait --wait-for-jobs` waits for the
  migration Job and ready Pods, and reverts to the previous release automatically if they
  never become healthy. A smoke test then checks the public URL and the running image tag.
- **Pinned supply chain.** Every GitHub Action is pinned to a full commit SHA; Trivy and
  Gitleaks run from digest-pinned images; kind and Helm binaries are checksum-verified.
  Dependabot proposes updates, and each update goes through the full pipeline.

## Infrastructure (Terraform)

| Resource | Choice | Why |
|---|---|---|
| VPC | `10.42.0.0/16`, 2 AZs, 2 public + 2 private subnets | Nodes stay private; load balancers get public subnets via the `kubernetes.io/role/elb` tag |
| NAT | One shared NAT gateway | Lowest cost for a demo; production would run one per AZ |
| EKS | Managed control plane, API-mode access entries | No `aws-auth` ConfigMap to hand-edit; access is declared in Terraform |
| Nodes | Managed node group, 2 × t3.medium (1 to 3) | Fits app, Ingress and monitoring with headroom |
| Add-ons | CoreDNS, kube-proxy, VPC CNI, metrics-server, Pod Identity, EBS CSI (IRSA) | metrics-server feeds the HPA; EBS CSI provisions encrypted gp3 volumes |
| IAM | GitHub OIDC provider + deploy role | Keyless CI deployments |

Kubernetes itself creates two AWS resources Terraform does not track: the NLB for the Ingress
Service and EBS volumes for PVCs. `scripts/eks-teardown.sh` deletes them through Kubernetes
first, waits for the load balancer to disappear, then runs `terraform destroy` and checks
for leftover volumes. Without this order, VPC deletion stalls and orphaned disks keep billing.

## Runtime and recovery

The frontend uses the container's DNS resolver so replacing an API container does not leave Nginx pointing at an old Docker IP. Startup probes accommodate initialization, readiness checks database/schema access, and liveness checks the process. Pod termination includes a short drain delay for endpoint propagation.

PostgreSQL uses a persistent StatefulSet claim. API pods are disposable. The database remains a single-instance demo deployment, so a DB restart can cause a short outage. A Helm rollback changes application/configuration; it cannot reverse a schema migration. Current migration 0001 is compatible with the recorded local image rollback.

Traefik implements Ingress: on minikube it uses a dedicated IngressClass behind a ClusterIP Service, on EKS it is the default class behind an AWS Network Load Balancer. Prometheus Operator discovers API replicas through ServiceMonitor, Grafana consumes live metrics, and Alloy reads only SeatLock namespace pod logs through scoped RBAC. Loki keeps local filesystem data with 24-hour retention. Request IDs remain log fields rather than Loki labels to avoid excessive label cardinality.

## Security model

| Layer | Control |
|---|---|
| Code | Bandit SAST (medium+ fails), Ruff lint |
| Dependencies | pip-audit and npm audit against lockfiles, Dependabot |
| Secrets | Gitleaks over the full Git history; scanner self-test plants a fake token to prove detection |
| Images | Trivy, fail on any HIGH or CRITICAL (fixed or unfixed); Alpine bases with `apk upgrade` |
| IaC | Trivy misconfiguration scan of Terraform, Helm and Dockerfiles; accepted findings justified in `.trivyignore` |
| Runtime | Non-root UIDs, read-only root filesystem, all capabilities dropped, no privilege escalation, no service-account token mounts |
| Cloud access | OIDC role scoped to one repo environment and one namespace |
| App | HttpOnly SameSite session cookie (hash stored server-side), custom-header + Origin check on mutations, separate organizer token |

Known limits, deliberately out of scope for a demo: guest sessions instead of accounts, no
payments, plain HTTP on the load balancer hostname (TLS would need a domain and ACM or
cert-manager), a single-instance PostgreSQL where production would use Amazon RDS Multi-AZ,
and Kubernetes Secrets created from a local file where production would use AWS Secrets
Manager with the External Secrets Operator.
