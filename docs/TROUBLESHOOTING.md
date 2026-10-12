# Troubleshooting drills: recorded runs

Executed on 7 October 2026, local Minikube, namespace **seatlock-drill**. Six individual faults and an independent three-fault challenge were investigated and recovered. Each report stores actual timestamps, commands, events, resource state, application logs, the root cause, Helm restoration, and post-recovery transaction checks.

## Isolation and repeatability

The harness fixes its context and namespace. It does not accept the primary application namespace or a remote cluster. Drill credentials and database PVC are separate from the demo. Storage experiments create only the disposable `storage-drill` claim. Credentials are passed privately; report snapshots inspect references and key names, never Secret values.

Prerequisites: the working app images loaded in Minikube, `scripts/local-platform.sh` completed, and port-forwards to Traefik on 3004 and Kubernetes Prometheus on 9091. Default image tags are `local`; the original development cluster used versioned tags. To use those existing images:

```bash
SEATLOCK_BACKEND_TAG=local-v3 SEATLOCK_FRONTEND_TAG=local-v4 bash scripts/drill.sh run-all
```

On a fresh setup with the README's loaded `:local` images, use `bash scripts/drill.sh run-all`. The harness restores healthy Helm state in a `finally` block when a run fails. Helm 4 needs `--force-conflicts` after intentional patches; the harness detects and supplies it for this release. Individual operations:

```bash
bash scripts/drill.sh prepare
bash scripts/drill.sh inject --scenario T02
bash scripts/drill.sh inspect
bash scripts/drill.sh restore
bash scripts/drill.sh verify
```

Inspection is also available through ordinary `kubectl --context=minikube -n seatlock-drill` commands. End by restoring, even if you stop an investigation early.

## Recorded individual scenarios

| Report | Injected fault | Actual observation | Injection → verified recovery |
|---|---|---|---|
| [T01](evidence/troubleshooting/T01.json) | Invalid image | ErrImageNeverPull | 13.2 s |
| [T02](evidence/troubleshooting/T02.json) | Service selector | Zero ready backend Service endpoints | 10.6 s |
| [T03](evidence/troubleshooting/T03.json) | Secret key | CreateContainerConfigError | 12.6 s |
| [T05](evidence/troubleshooting/T05.json) | Readiness path | Readiness probe returned HTTP 404 | 17.6 s |
| [T07](evidence/troubleshooting/T07.json) | Storage class | Scratch PVC Pending with missing StorageClass | 10.6 s |
| [T09](evidence/troubleshooting/T09.json) | Monitoring port | No discovered drill API scrape targets | 135.5 s |

Durations include fault observation, resource/log collection, Helm restore, a booking transaction, and monitoring recovery. They describe these local runs; they are not production incident SLAs.

T01 uses `imagePullPolicy: Never` with an absent local tag to avoid registry timeout ambiguity. Its actual failure is **ErrImageNeverPull**, not ImagePullBackOff. An old ready API pod can continue serving while the new rollout is broken. Restore a known image and verify the updated ready replicas and actual image identity.

T02 changes the API Service selector to a value absent from pod labels. EndpointSlices have no ready backend addresses, so `/api` through Ingress fails even though the frontend and healthy pods can exist. Comparing Service selectors, pod labels and endpoints isolates the routing failure; the healthy Helm chart restores the selector.

T03 references a nonexistent key in the existing runtime Secret. Events identify the key failure before application startup. Fixing the reference allows the container to start; dumping the Secret would add no useful diagnosis and would expose credentials.

T05 sets the readiness URL to `/ready-typo`. Events show HTTP 404 and the new pod remains unready. Correcting that readiness path permits traffic. Process liveness stays distinct from database/schema readiness.

T07 requests a nonexistent StorageClass on a **scratch claim**. The claim remains Pending. No application DB pod uses it; this run does not claim the real database failed to start. Restore deletes only the disposable claim, leaving both application database volumes intact.

T09 changes ServiceMonitor's endpoint to a named port absent from the API Service. The app can still work, while Prometheus has no discovered drill API targets. The restored named-port configuration produces a target with health UP. This run took longer than the other cases while monitoring/discovery recovered under the recorded local workload.

## Combined T01 + T02 + T09

[The completed combined report](evidence/troubleshooting/combined.json) began at 12:56:34 UTC and finished at 12:56:48 UTC. Three faults were introduced together: invalid API image, empty Service endpoints, and missing monitoring discovery.

1. Pod events showed ErrImageNeverPull. Restoring the image made the rollout ready; Service routing and monitoring remained broken.
2. Comparing labels/selectors/EndpointSlices identified the selector mismatch. Restoring the selector recovered API routing; the incorrect metrics port remained.
3. Restoring Helm's ServiceMonitor configuration recovered discovery and UP scraping.
4. Verification traversed Traefik using `seatlock-drill.local`: session → event inventory → seat hold → confirm → private ticket history → cancellation → released inventory. It also required the updated API replicas to be ready and the Prometheus target to be UP.

Fixing the first visible pod problem could not solve the independent networking and observability failures. The layered checks make that distinction explicit.

## Related operational investigations

The project also recorded [persistent ticket recovery](evidence/persistence.json), [backup/restore](evidence/backup-restore.json), [HPA scale-up](evidence/hpa-load.json), and [alert firing/recovery](evidence/alert-recovery.json).

Grafana had a slow cold start under a Minikube container limited to 2 CPUs / 4000 MiB despite greater advertised node capacity. It exited with reason Error/code 2; OOM was not established. More actual local headroom, a startup probe, and removal of unused default dashboards resolved startup. A later long-running Grafana instance reached its CPU limit and stopped responding. The recorded [resource/liveness adjustment](evidence/monitoring-recovery.json) recovered health and a populated [log panel](screenshots/monitoring/grafana-logs-kubernetes.png); exact internals and a multi-hour soak remain unproven. A stale ingress-nginx validating webhook left over from earlier coursework also rejected the Traefik Ingress; scoping that webhook away from the `seatlock-traefik` class fixed it without weakening validation for other classes.

## Future optional scenarios

Wrong live DB credentials, impossible resource requests and missing HPA CPU requests are useful extensions; they are not recorded as completed drills. For hands-on practice without the harness, see the standalone manifests in [`troubleshooting/`](../troubleshooting/README.md).
