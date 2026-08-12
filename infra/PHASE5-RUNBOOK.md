# Phase 5 Runbook — Observability

kube-prometheus-stack via Argo CD (multi-source Application), backend
instrumented with custom metrics, one dashboards-as-code Grafana
dashboard. See `docs/errors.md` for the gotchas already designed around
(ServiceMonitor selector defaults, Kind's fake control-plane targets).

Prerequisite: Phase 4 (Flow A) up and verified.

## 1. Create the Grafana admin Secret

Same out-of-band pattern as every other credential in this project:
```powershell
$password = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 24 | %{[char]$_})
kubectl create namespace observability
kubectl create secret generic grafana-admin-secret -n observability --from-literal=admin-user=admin --from-literal=admin-password=$password
Write-Host "Grafana admin password: $password"
```
Save that password somewhere — Grafana has no other way to show it to you
again short of resetting it. (`kubectl create namespace observability`
here is redundant with what Argo CD will create anyway via
`argocd/manifests/namespace.yaml`, but the Secret needs the namespace to
exist *now*, before the first sync — same ordering lesson as
`backend-secrets` in `PHASE4-RUNBOOK.md`.)

## 2. Push

`argocd/applications/kube-prometheus-stack.yaml` and the new
`helm/backend/templates/servicemonitor.yaml` /
`grafana-dashboard-configmap.yaml` are new files — commit and push them
(if not already part of a batch you're pushing). The already-running
`root` Application picks up the new `kube-prometheus-stack` Application
file automatically; no manual `kubectl apply` needed, unlike bootstrapping
`root` itself back in Phase 4.

Also push the backend changes (`app/metrics.py`, the `/metrics` route, the
`chat.py` instrumentation) if you haven't — `.github/workflows/
backend-image.yml` builds+pushes the new image and bumps the Helm tag
automatically (Phase 4's CI loop), no manual image build needed.

## 3. Watch it come up

```
kubectl get applications -n argocd -w
```
`kube-prometheus-stack` will take a few minutes (it's a much bigger chart
than anything else in this project — Prometheus Operator, Prometheus,
Alertmanager, Grafana, node-exporter, kube-state-metrics all at once).

## 4. Verify Prometheus is scraping the backend

```
kubectl port-forward -n observability svc/kube-prometheus-stack-prometheus 9090:9090
```
→ http://localhost:9090/targets — look for a target from the
`backend`/`ai-builder` ServiceMonitor, state `UP`. If it's missing
entirely (not just down), check `serviceMonitorSelectorNilUsesHelmValues`
actually landed (`kubectl get prometheus -n observability -o yaml | grep
serviceMonitorSelector` — should show `{}`, not absent) — the values file
sets this explicitly for exactly this failure mode.

## 5. Add `grafana.local` to your hosts file

```
127.0.0.1 grafana.local
```
Log in at `http://grafana.local` with `admin` / the password from step 1.
The "AI Website Builder — Backend" dashboard should already be there
(Dashboards → Browse) — no manual import needed, that's the point of the
ConfigMap + sidecar pattern.

## 6. Generate some data to look at

Send a few chat messages and pushes through the app — `llm_requests_total`
and `chat_requests_in_progress` populate immediately from `/chat`;
`deployment_callbacks_total` only populates if Flow B is also wired up
(a push against a project with a registered domain).

## Known follow-ups (not done in this pass)

- **Grafana RBAC (a read-only role)** — deliberately deferred; see
  `docs/errors.md`. Nothing to build until there's a second person to
  scope access for.
- **`/metrics` is reachable through the public `app.local/api/metrics`
  path** — no secrets in it, but not intentionally public either. See the
  comment on the route in `backend/app/main.py`.
- **`kube-prometheus-stack` isn't backed by real alerting yet** —
  Alertmanager is installed and running, but nothing's configured to
  actually page/notify on anything. The bundled default alert rules exist
  but there's no Alertmanager receiver wired up (no Slack/email/etc) —
  they'd just accumulate unseen right now.
