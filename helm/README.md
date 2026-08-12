# helm/

Our own charts — `backend/`, `frontend/`, `reverse-proxy/`. Each deploys a `Deployment` + `Service` for the corresponding Dockerized app; Ingress routing lives separately in `infra/ingress/manifests/` instead (`app-ingress.yaml` for backend/frontend; `reverse-proxy` is reached via ingress-nginx's *default backend*, not a host-matched Ingress rule — see the comment in `infra/ingress/ingress-nginx-values.yaml`), same as how every other component in this project keeps its Ingress separate from its Helm release (see `infra/ingress/manifests/localstack-ingress.yaml`).

Reconciled by Argo CD (`argocd/applications/*.yaml`) — not installed directly via `helm install`. For manual testing/linting:
```
helm template helm/backend
helm template helm/frontend
helm template helm/reverse-proxy
```

`backend/` expects a `backend-secrets` Secret in `ai-builder` (see `../infra/PHASE4-RUNBOOK.md`); `reverse-proxy/` expects `reverse-proxy-secrets` (see `../infra/PHASE4-RUNBOOK-B.md`) — both created out-of-band, never templated by the chart itself.

`backend/values.yaml` and `frontend/values.yaml`'s `image.repository`/`image.tag` are **not meant to be hand-edited day to day** — `.github/workflows/backend-image.yml`/`frontend-image.yml` overwrite them automatically on every push to `main` that touches the corresponding app directory, pointing at the newly-built `ghcr.io/tomkoren1/ai-builder-*` image. `reverse-proxy/values.yaml` has no such workflow yet (still built/loaded locally per `../infra/PHASE4-RUNBOOK-B.md`).
