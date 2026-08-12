# argocd/

App-of-apps root for everything Argo CD manages. See `../infra/PHASE4-RUNBOOK.md` for how to bootstrap this.

```
bootstrap/root-application.yaml   Applied once, manually. Everything below is then owned by Argo CD.
applications/                     One Application manifest per component. This directory itself is what root-application.yaml points at.
manifests/                        Raw (non-Helm) Kubernetes manifests that an Application in applications/ sources directly — currently just the ai-builder namespace.
```

## Sync waves

| Wave | Application | What |
|---|---|---|
| `-1` | `infrastructure-namespace` | Creates the `ai-builder` and `observability` namespaces (one file, two `Namespace` objects — see `manifests/namespace.yaml`) — must exist before anything deploys into them. |
| `0` | `kube-prometheus-stack`, `ingress-nginx`, `localstack` | Platform infra. `kube-prometheus-stack` (Phase 5) was the first real use of the **multi-source** Application pattern (public Helm chart + this repo's values file as a second source); `ingress-nginx`/`localstack` use the same pattern but as an **adoption** of already-running releases rather than a fresh install (`infra/up.ps1` still bootstraps them imperatively first — see those files' own comments for why that's deliberate, not superseded). `kube-prometheus-stack`'s CRDs are **not** managed by its Application (`crds.enabled: false`) — Argo CD's own sync pipeline fails on them even with Server-Side Apply; they're installed once, manually, outside GitOps entirely. See `../infra/PHASE5-RUNBOOK.md` step 2 and `../docs/errors.md` for why. |
| `1` | `backend`, `frontend`, `app-ingress`, `reverse-proxy` | The app itself, the Ingress routing `app.local` to backend/frontend, and the Flow B service that serves per-project sites (reached via ingress-nginx's default backend, not a host-matched Ingress rule — see `infra/ingress/ingress-nginx-values.yaml`). |

`ingress-nginx`/`localstack` are adoptions, not fresh installs — `infra/up.ps1` still does the actual first-time bootstrap (Argo CD itself doesn't exist until Phase 4, so Phase 1 can't depend on it), and these Applications take over *ongoing* reconciliation afterward. Verified as a genuine zero-diff adoption before enabling automated sync (pinned to the exact chart versions already live, confirmed all resources `Synced` with no sync operation ever run) — see `docs/errors.md`.

## Adding a new Application

1. Add a manifest/Helm source somewhere in the repo (a `helm/<name>/` chart, or a raw manifest under `manifests/` for cluster-level resources).
2. Add an `Application` YAML for it under `applications/` with the right `argocd.argoproj.io/sync-wave` annotation for where it belongs in the dependency order.
3. Commit and push — the root Application picks up the new file on its next sync (automated, so this usually takes seconds, not a manual `kubectl apply`).
