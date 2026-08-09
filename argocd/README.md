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
| `-1` | `infrastructure-namespace` | Creates the `ai-builder` namespace — must exist before anything deploys into it. |
| `1` | `backend`, `frontend`, `app-ingress`, `reverse-proxy` | The app itself, the Ingress routing `app.local` to backend/frontend, and the Flow B service that serves per-project sites (reached via ingress-nginx's default backend, not a host-matched Ingress rule — see `infra/ingress/ingress-nginx-values.yaml`). |

`ingress-nginx`/LocalStack (wave `0` in `overview.md`'s original plan) aren't here yet — still installed imperatively by `infra/up.ps1`. See the "Known follow-up" note in `PHASE4-RUNBOOK.md`.

## Adding a new Application

1. Add a manifest/Helm source somewhere in the repo (a `helm/<name>/` chart, or a raw manifest under `manifests/` for cluster-level resources).
2. Add an `Application` YAML for it under `applications/` with the right `argocd.argoproj.io/sync-wave` annotation for where it belongs in the dependency order.
3. Commit and push — the root Application picks up the new file on its next sync (automated, so this usually takes seconds, not a manual `kubectl apply`).
