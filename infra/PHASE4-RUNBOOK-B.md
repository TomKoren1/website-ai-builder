# Phase 4 Runbook — Flow B: per-project CI → S3

Covers everything Flow A (`PHASE4-RUNBOOK.md`) doesn't: a project's site
bucket, the Gitea Actions workflow that syncs pushed files to it, the
reverse-proxy that actually serves them to visitors, and the Argo CD/IAM
pieces specific to that.

Prerequisite: Flow A done and verified (`app.local` serving the app itself
through Argo CD).

## 1. Apply the new Terraform (IAM)

`infra/terraform/main.tf` now also defines `ci-deploy-role` (S3 write, no
read/create) and `reverse-proxy-role` (S3 read-only), plus a `site-*`
CreateBucket grant on the existing `orchestrator-role`. Re-run:
```
cd infra/terraform
terraform plan -out=tfplan
terraform apply tfplan
terraform output   # new: ci_deploy_role_arn, ci_deploy_app_access_key_id/secret,
                    #      reverse_proxy_role_arn, reverse_proxy_app_access_key_id/secret
```

## 2. Run the backend migration

Adds `deployments.callback_token_hash` (see `chat.py`'s `push()` — this is
the one-time token CI uses to report status back):
```
kubectl exec -n ai-builder deploy/backend -- alembic upgrade head
```

## 3. Build + load the reverse-proxy image

```
docker build -t ai-builder-reverse-proxy:local reverse-proxy/
kind load docker-image ai-builder-reverse-proxy:local --name ai-builder
```

## 4. Create reverse-proxy-secrets

```
kubectl create secret generic reverse-proxy-secrets -n ai-builder \
  --from-literal=DATABASE_URL="postgresql+asyncpg://app:<postgres password>@postgres.postgres.svc.cluster.local:5432/app" \
  --from-literal=AWS_REVERSE_PROXY_APP_ACCESS_KEY_ID="<terraform output -raw reverse_proxy_app_access_key_id>" \
  --from-literal=AWS_REVERSE_PROXY_APP_SECRET_ACCESS_KEY="<terraform output -raw reverse_proxy_app_secret_access_key>" \
  --from-literal=AWS_REVERSE_PROXY_ROLE_ARN="<terraform output -raw reverse_proxy_role_arn>"
```

## 5. Push, let Argo CD pick up the new Application

`argocd/applications/reverse-proxy.yaml` is new — commit/push it (and
everything else in this change) so the root Application's next sync
creates it:
```
kubectl get applications -n argocd -w
```
Expect `reverse-proxy` to appear and go `Synced`/`Healthy` (it'll be
`Degraded` until step 4's Secret exists, same as `backend` was in Flow A).

## 6. Point ingress-nginx's default backend at it

`infra/ingress/ingress-nginx-values.yaml` now sets
`controller.extraArgs.default-backend-service` (and `updateStrategy.type:
Recreate` — see the note below) — this is a values change to an
already-installed release, so (per the note already in that file from
Phase 1) it needs a manual upgrade, not just editing the file:
```
helm upgrade ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx -f infra/ingress/ingress-nginx-values.yaml
```
Do this *after* step 5 — the reverse-proxy Service needs to exist first,
or nginx's default backend points at nothing.

**If this is upgrading an ingress-nginx that was installed before the
`Recreate` strategy existed in this values file**, the upgrade will likely
fail outright:
```
Deployment.apps "ingress-nginx-controller" is invalid: spec.strategy.rollingUpdate: Forbidden: may not be specified when strategy `type` is 'Recreate'
```
This happens because the live Deployment still has a `rollingUpdate` block
from before, and Helm's server-side apply won't clear a field it isn't
explicitly told to remove. One-time fix, then re-run the `helm upgrade`
above:
```
kubectl patch deployment ingress-nginx-controller -n ingress-nginx --type=json -p "[{\"op\":\"replace\",\"path\":\"/spec/strategy\",\"value\":{\"type\":\"Recreate\"}}]"
```
(A cluster that installs ingress-nginx fresh with this values file from the
start never hits this — it's only a stale-field issue on an upgrade. Also
worth knowing: on this single-node Kind setup, `RollingUpdate` genuinely
cannot succeed for a `hostPort`-bound controller like this one — the new
pod can never schedule while the old one still holds the ports, so it just
sits `Pending` forever with no error, and the *old* pod (with the old
config) keeps serving everything. If you ever see that — `kubectl get pods
-n ingress-nginx` showing two pods, one `Pending` indefinitely — this
`Recreate` change is why it's there. See `docs/errors.md`.)

## 7. Enable Gitea Actions + register a runner

`infra/gitea/values.yaml` now sets `gitea.config.actions.ENABLED: true`:
```
helm upgrade gitea gitea-charts/gitea -n gitea -f infra/gitea/values.yaml
```

Get a runner registration token (Gitea UI: Site Administration → Actions →
Runners → "Create new Runner", or via CLI in the gitea pod):
```
kubectl exec -n gitea deploy/gitea -- gitea actions generate-runner-token
```

```
kubectl create secret generic act-runner-token -n gitea --from-literal=token=<paste token>
kubectl apply -f infra/gitea/act-runner.yaml
kubectl get pods -n gitea -w   # wait for act-runner-xxx to be 2/2 Running
```
Confirm it registered: Gitea UI → Site Administration → Actions → Runners
should show one online runner.

**If the runner's first job ever gets stuck** — logs show `task N repo is
...` and then nothing, no error, for many minutes, with `docker ps -a`
inside the `dind` sidecar staying empty the whole time — this was seen
once and never root-caused (see `docs/errors.md`). Deleting the pod and
letting the Deployment recreate it (a fresh registration) reliably
unstuck it:
```
kubectl delete pod -n gitea -l app=act-runner
kubectl wait --namespace gitea --for=condition=ready pod -l app=act-runner --timeout=120s
```

## 8. Create org-level Actions secrets

Every project repo's `.gitea/workflows/deploy.yml` (seeded automatically at
project creation — see `projects.py`) references these by name. Set once
at the `projects` org level (Gitea UI: `projects` org → Settings → Actions
→ Secrets, or via API) so every project's workflow can use them without
per-repo duplication:

| Secret | Value |
|---|---|
| `CI_DEPLOY_APP_ACCESS_KEY_ID` | `terraform output -raw ci_deploy_app_access_key_id` |
| `CI_DEPLOY_APP_SECRET_ACCESS_KEY` | `terraform output -raw ci_deploy_app_secret_access_key` |
| `CI_DEPLOY_ROLE_ARN` | `terraform output -raw ci_deploy_role_arn` |
| `AWS_ENDPOINT_URL` | `http://localstack.localstack.svc.cluster.local:4566` (in-cluster — the runner pod reaches LocalStack directly, not through the ingress) |
| `BACKEND_URL` | `http://backend.ai-builder.svc.cluster.local:8000` |

The seeded workflow (`projects.py`'s `_CI_WORKFLOW`) already installs the
AWS CLI itself and sets `AWS_DEFAULT_REGION` explicitly — Gitea's own
`ubuntu-latest` runner image doesn't ship the AWS CLI the way GitHub's
hosted runners do, and the CLI refuses to run with no region configured
even against LocalStack (see `docs/errors.md` for both). If your `backend`
image predates this, rebuild/redeploy it (step 1 of `PHASE4-RUNBOOK.md`)
before testing — otherwise every *new* project already gets the fixed
workflow, but any project created before the fix has the old, broken
version committed in its repo and needs its `.gitea/workflows/deploy.yml`
edited by hand (Gitea UI) to pick up the fix.

## 9. End-to-end test

1. Create a project through the app (`app.local`), send a chat message so
   it has an `index.html`.
2. Register a domain for it — any hostname works locally, e.g.
   `myproject.local` — through `POST /domains` (no UI for this yet; use
   `curl` or the browser devtools console against the running frontend).
   This creates the `site-{project_id}` bucket (Flow A's orchestrator-role
   change from step 1).
3. Click Push. Watch `kubectl get pods -n gitea -w` — a new Actions job pod
   should appear briefly. Check the deployment's status flips from
   `pending` to `success` (`GET /projects/{id}/messages` doesn't show this
   — check via the `deployments` table directly for now, no frontend UI
   for deployment status yet):
   ```
   kubectl exec -n postgres postgres-0 -- psql -U app -c "select id, status, deployed_at from deployments order by created_at desc limit 5;"
   ```
4. Add `myproject.local` to your hosts file pointing at `127.0.0.1`, then:
   ```
   curl http://myproject.local/
   ```
   Should return the pushed `index.html` — this request went through
   ingress-nginx's default backend (no `Ingress` rule for `myproject.local`
   exists — that's the point) to the reverse-proxy, which looked up the
   bucket in Postgres and fetched the object from LocalStack S3.

## Known follow-ups (not done in this pass)

- **Reverse-proxy DB access** uses the same `app` Postgres user as the
  backend, not a dedicated read-only role scoped to `SELECT` on `domains`
  only. Credential-wise this service could write to any table, though the
  code never does. Worth a real Postgres role (`GRANT SELECT ON domains TO
  reverse_proxy;`) once this stack has more than one person's trust
  boundary to actually enforce.
- **No frontend UI for domains or deployment status** — `POST /domains`
  and reading `deployments.status` both currently require `curl`/direct DB
  access. A real "Domains" page and a status indicator on the push button
  are natural next frontend work, not part of Flow B itself.
- **act_runner and Gitea Actions aren't behind Argo CD** — same category as
  ingress-nginx/LocalStack in Flow A's known follow-up: installed
  imperatively here, worth folding into GitOps later.
