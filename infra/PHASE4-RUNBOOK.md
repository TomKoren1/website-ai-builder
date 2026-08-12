# Phase 4 Runbook — Flow A: Argo CD + platform-managed backend/frontend

Covers getting the backend and frontend Dockerized, running in-cluster, and
reconciled by Argo CD via the app-of-apps in `argocd/`. Flow B (per-project
CI → S3 sync) is a separate runbook once it exists.

Prerequisite: Phase 1 (`infra/up.ps1`) and Phase 2 (Postgres + Gitea, see
`PHASE2-RUNBOOK.md`) already up and reachable.

## 1. Build the images

**As of `.github/workflows/backend-image.yml`/`frontend-image.yml`, this
is now automated for any push to `main` that touches `backend/**` or
`frontend/**`** — GitHub Actions builds the image, pushes it to GHCR
(`ghcr.io/tomkoren1/ai-builder-backend`/`-frontend`), and commits the new
tag into `helm/*/values.yaml`, which Argo CD's existing auto-sync then
picks up on its own. No manual step needed for ongoing changes — this
section is now only for the very first bring-up (before any image has
ever been pushed) or fully offline iteration.

**One-time step after the very first successful workflow run**: GHCR
packages default to **private** even when pushed from a public repo — go
to the package's own page (GitHub profile → Packages →
`ai-builder-backend`/`ai-builder-frontend`) → Package settings → Danger
Zone → Change visibility → Public. Skipping this means Kind's pulls fail
with 401/403 and Argo CD shows the Application stuck `Progressing`/
`Degraded` with an `ImagePullBackOff` on the pod.

Manual / offline path (no registry involved, same as before this CI
existed):
```
docker build -t ai-builder-backend:local backend/
docker build -t ai-builder-frontend:local frontend/
kind load docker-image ai-builder-backend:local --name ai-builder
kind load docker-image ai-builder-frontend:local --name ai-builder
```
Note this only works if `helm/*/values.yaml`'s `image.repository`/`tag`
still point at the local `:local` tags — once the CI workflow has run at
least once, it'll have overwritten those to point at GHCR, and you'd need
to manually revert them to use this path again.

## 2. Install Argo CD

```
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl wait --namespace argocd --for=condition=available deployment --all --timeout=300s
```

Get the initial admin password (delete the secret afterward per Argo CD's
own guidance, once you've logged in and changed it):
```powershell
$b64 = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))
```

Access the UI (no Ingress for it yet — port-forward):
```
kubectl port-forward -n argocd svc/argocd-server 8080:443
```
→ https://localhost:8080, user `admin`.

## 3. Bootstrap the app-of-apps

Applied once, manually — everything else in `argocd/applications/` is then
created/updated by Argo CD itself from Git. This is what actually creates
the `ai-builder` namespace (the `infrastructure-namespace` Application,
sync-wave -1) — do this before step 4, not after; the Secret there needs
the namespace to already exist.
```
kubectl apply -f argocd/bootstrap/root-application.yaml
```

Watch it reconcile:
```
kubectl get applications -n argocd -w
```
Expect, in order: `infrastructure-namespace` → Synced/Healthy, then
`backend`/`frontend`/`app-ingress` → `Degraded`/`Missing` (expected — they
need step 4's Secret first, which doesn't exist yet).

## 4. Create the ai-builder namespace's Secret

`backend-secrets` holds actual credentials, so like every other credential
in this project it's created out-of-band, not committed to Git.

Values come from the same places `backend/.env` already points at
(`terraform output`, the Gitea token, your `JWT_SECRET`) — see
`backend/.env.example` for what each one is:

```
kubectl create secret generic backend-secrets -n ai-builder \
  --from-literal=DATABASE_URL="postgresql+asyncpg://app:<postgres password>@postgres.postgres.svc.cluster.local:5432/app" \
  --from-literal=JWT_SECRET="<same generation method as PHASE2-RUNBOOK step 1>" \
  --from-literal=AWS_ORCHESTRATOR_APP_ACCESS_KEY_ID="<terraform output -raw orchestrator_app_access_key_id>" \
  --from-literal=AWS_ORCHESTRATOR_APP_SECRET_ACCESS_KEY="<terraform output -raw orchestrator_app_secret_access_key>" \
  --from-literal=AWS_ORCHESTRATOR_ROLE_ARN="<terraform output -raw orchestrator_role_arn>" \
  --from-literal=GITEA_ADMIN_TOKEN="<Gitea admin token, same scopes as PHASE2-RUNBOOK: write:organization, write:repository>"
```

Argo CD's `selfHeal` picks this up on its own within a few seconds —
`backend` should flip to `Synced`/`Healthy` without needing a manual sync
(check `kubectl describe application backend -n argocd` if it doesn't).

## 5. Run the database migration

Not automated (see the comment in `backend/Dockerfile` — no auto-migrate
on container start, to avoid multiple replicas racing on `alembic upgrade
head`). One-off, against the running pod:
```
kubectl exec -n ai-builder deploy/backend -- alembic upgrade head
```

## 6. Verify

Add to your hosts file if not already there (same pattern as
`localstack.local`/`gitea.local` from earlier phases):
```
127.0.0.1 app.local
```
Then:
```
curl http://app.local/api/docs   # backend, through the /api rewrite
```
Open `http://app.local` in a browser — should hit the frontend, login page
loads, and login/register calls succeed through `/api` (same-origin now —
no more `localhost:3000` ↔ `localhost:8000` cross-origin CORS dance from
`next dev`).

## Known follow-up (not done in this pass)

`ingress-nginx` and LocalStack are still installed imperatively by
`infra/up.ps1` (Helm directly), not reconciled by Argo CD — bringing them
under GitOps too needs Argo CD's "multiple sources" Application (public
Helm chart + this repo's `infra/ingress`/`infra/localstack` values files as
a second source), which wasn't built out in this pass to avoid shipping
something unverified against a live cluster. `overview.md`'s Phase 4 sync
waves lists this as wave 0 ("platform") — worth doing once Flow A above is
confirmed working end-to-end.
