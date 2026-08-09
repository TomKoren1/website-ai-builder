# Phase 2 Runbook (infra prerequisites) — Postgres + Gitea

These stand up the two things the backend code depends on before any
FastAPI code is worth running. Manual steps first, same reasoning as
Phase 1 — once this is validated working, it's a natural candidate to
fold into `infra/up.ps1` since it'll become routine.

## 1. Generate shared DB credentials

Postgres and Gitea need matching credentials (Gitea authenticates to
Postgres as the same user). Generate one password, use it for both —
not committed to Git (same pattern as the LocalStack token).

```
powershell -Command "-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 24 | %{[char]$_})"
```
(Any random 24+ char string works here — this is local dev, not a value
that needs cryptographic ceremony.)

Save it somewhere you can paste from for the next few commands.

## 2. Create the postgres-credentials Secret
```
kubectl create namespace postgres
kubectl create secret generic postgres-credentials -n postgres --from-literal=POSTGRES_USER=app --from-literal=POSTGRES_PASSWORD=<paste password> --from-literal=POSTGRES_DB=app
```

## 3. Deploy Postgres
```
kubectl apply -f infra/postgres/manifests.yaml
kubectl get pods -n postgres -w
```
(Ctrl+C once `1/1 Running`.) This also runs the init script that creates
the `gitea` database — check it worked:
```
kubectl exec -n postgres postgres-0 -- psql -U app -l
```
Should list both `app` and `gitea` databases.

## 4. Create Gitea's credentials

Same password as step 1, different Secret (namespace-scoped, so Gitea's
namespace needs its own copy — see the comment in infra/gitea/values.yaml
for why):
```
kubectl create namespace gitea
kubectl create secret generic gitea-db-credentials -n gitea --from-literal=POSTGRES_USER=app --from-literal=POSTGRES_PASSWORD=<paste same password>
```

Gitea admin account — generate a separate password the same way as step 1:
```
kubectl create secret generic gitea-admin-secret -n gitea --from-literal=username=admin --from-literal=password=<paste a new password>
```

## 5. Install Gitea
```
helm repo add gitea-charts https://dl.gitea.com/charts/
helm repo update gitea-charts
helm install gitea gitea-charts/gitea -n gitea -f infra/gitea/values.yaml
kubectl get pods -n gitea -w
```
(Ctrl+C once ready — Gitea's first boot is slower than the others, it's
running DB migrations.)

## 6. Hosts file
Add to `C:\Windows\System32\drivers\etc\hosts` (as Administrator):
```
127.0.0.1 gitea.local
```

## 7. Verify
```
curl http://gitea.local/api/v1/version
```
Should return JSON with a `version` field. Then log into
`http://gitea.local` in a browser with the admin credentials from step 4
to confirm the web UI works too.

## 8. Create the Gitea organization for project repos

The backend creates every project's repo under a fixed org (`app/gitea_client.py`).
Create it once via the Gitea web UI (`http://gitea.local` → `+` → New Organization,
name it `projects`) or via API:
```
curl -X POST http://gitea.local/api/v1/orgs -u admin:<admin password> -H "Content-Type: application/json" -d "{\"username\": \"projects\"}"
```

## 9. Generate a Gitea admin API token

Log into `http://gitea.local` as admin → Settings → Applications → Generate New Token.
Gitea uses fine-grained scopes, not a single "repo" checkbox — check both
`write:organization` (needed once, for creating the `projects` org below) and
`write:repository` (needed per-project, for creating each repo). Save it — it
goes in `backend/.env` as `GITEA_ADMIN_TOKEN`.

## 10. Backend setup

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Now edit `.env` and fill in every value — the Postgres password from step 1, the
Terraform outputs from Phase 1 (`terraform output -raw ...` in `infra/terraform`),
and the Gitea token from step 9.

## 11. Port-forward Postgres (separate terminal, leave running)
```
kubectl port-forward -n postgres svc/postgres 5432:5432
```

## 12. Generate and run the initial migration
```
cd backend
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```
Check the generated file under `migrations/versions/` before running `upgrade` —
autogenerate is a starting point, not something to trust blindly.

## 13. Run the backend
```
cd backend
uvicorn app.main:app --reload
```

## 14. Smoke test
```
curl http://localhost:8000/health
curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d "{\"email\":\"you@example.com\",\"password\":\"testpass123\"}"
```
The register call should return a JSON body with `access_token`, and
`Set-Cookie` headers for both `access_token` and `refresh_token`.

## Known gotchas to watch for
- If Gitea's pod crash-loops on a database connection error, double-check
  the password in `gitea-db-credentials` (namespace `gitea`) exactly
  matches `postgres-credentials` (namespace `postgres`) — they're
  independent Secret objects, nothing keeps them in sync automatically.
- If `psql -l` in step 3 doesn't show the `gitea` database, the init
  script only runs when the PVC's data directory is empty. If you're
  re-running this after a previous attempt, you'll need to delete the PVC
  (`kubectl delete pvc -n postgres data-postgres-0`) and let the
  StatefulSet recreate it before the init script will run again.
