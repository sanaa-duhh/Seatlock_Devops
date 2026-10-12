# Troubleshooting lab

Four deliberately broken manifests, each reproducing a failure that is common in real
clusters. They are self-contained (they do not touch the SeatLock release) and run in
the `seatlock-drill` namespace.

```bash
kubectl create namespace seatlock-drill   # once; already present after eks-bootstrap.sh
kubectl apply -f troubleshooting/<lab>.yaml
```

The general method is the same every time:

```text
symptom  →  kubectl get  →  kubectl describe / events / logs  →  root cause  →  fix  →  verify
```

---

## Lab 1: `broken-image.yaml` (ImagePullBackOff)

**Symptom**

```console
$ kubectl -n seatlock-drill get pods -l app=lab-web
lab-web-658d495dd5-gmq5f   0/1   ImagePullBackOff   0   40s
```

**Investigate**

```bash
kubectl -n seatlock-drill describe pod -l app=lab-web | grep -A5 Events
kubectl -n seatlock-drill get events --sort-by=.lastTimestamp
```

The events show `Failed to pull image "nginxinc/nginx-unprivileged:1.99-does-not-exist": not found`.

**Root cause:** the image tag does not exist in the registry.
**Fix:** use a real tag (`stable-alpine`) and re-apply. In the SeatLock pipeline this cannot
reach production by accident: images are tagged with the commit SHA and pushed *before*
`helm upgrade` runs, and `--rollback-on-failure` restores the previous release if Pods
never become ready.

---

## Lab 2: `broken-service.yaml` (Service with no endpoints)

**Symptom:** both Pods are `Running` and `1/1` Ready, yet requests to the Service fail.

**Investigate**

```bash
kubectl -n seatlock-drill get svc lab-api -o wide          # SELECTOR app=lab-api-v2
kubectl -n seatlock-drill get endpointslices -l kubernetes.io/service-name=lab-api
kubectl -n seatlock-drill get pods --show-labels           # Pods carry app=lab-api
```

The EndpointSlice has no addresses.

**Root cause:** a Service selects Pods by label; `app=lab-api-v2` matches nothing.
No matching labels means no endpoints, and no endpoints means no traffic.
**Fix:** set the selector to `app: lab-api`. The EndpointSlice immediately lists both Pod IPs.

---

## Lab 3: `broken-readiness.yaml` (Running but never Ready)

**Symptom**

```console
$ kubectl -n seatlock-drill get pods -l app=lab-ready
lab-ready-64f75c54f9-2rpkt   0/1   Running   0   40s
```

**Investigate**

```bash
kubectl -n seatlock-drill describe pod -l app=lab-ready | grep -i readiness
# Readiness probe failed: HTTP probe failed with statuscode: 404
```

**Root cause:** the readiness probe checks `/healthz-typo`, which returns 404. The
container is alive (so liveness would pass), but Kubernetes keeps it out of every Service.
**Fix:** probe a real path. SeatLock separates the two questions on purpose:
`/health` (liveness: is the process alive?) and `/ready` (readiness: can it reach
PostgreSQL and serve traffic now?).

---

## Lab 4: `broken-secret.yaml` (CreateContainerConfigError)

**Symptom**

```console
$ kubectl -n seatlock-drill get pods -l app=lab-config
lab-config-659695d956-khrpb   0/1   CreateContainerConfigError   0   40s
```

**Investigate**

```bash
kubectl -n seatlock-drill describe pod -l app=lab-config | grep -A3 Events
# Error: couldn't find key database_url in Secret seatlock-drill/lab-db
kubectl -n seatlock-drill get secret lab-db -o jsonpath='{.data}' | python3 -c "import json,sys; print(list(json.load(sys.stdin)))"
# ['database-url']   (key names only; never print the values)
```

**Root cause:** the Deployment asks for key `database_url`, but the Secret defines `database-url`.
**Fix:** reference the correct key. The container is never created, so there are no logs;
`describe` and events are the only evidence.

---

## Clean up

```bash
kubectl delete -f troubleshooting/
```

## Automated drills against the real application

`scripts/troubleshoot.py` (wrapped by `scripts/drill.sh`) injects faults into a full SeatLock
release in `seatlock-drill`, captures the evidence, restores the healthy Helm state and
verifies a booking end to end. It covers a bad image, a broken Service selector, a missing
Secret key, a wrong readiness path, a missing StorageClass, a ServiceMonitor port mismatch,
and all three of the first, second and last at once. Recorded runs are in
[`docs/TROUBLESHOOTING.md`](../docs/TROUBLESHOOTING.md).
