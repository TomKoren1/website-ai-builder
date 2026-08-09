# reverse-proxy

Standalone FastAPI service with exactly one job: resolve a visitor's `Host` header to an S3 bucket (via a direct Postgres lookup on `domains`) and proxy the requested object back. This is the "Flow B" serving path from `../overview.md`'s correction #1 — a custom domain never gets its own pre-created Ingress rule (domains are added by users at runtime, long after this cluster's Ingress manifests are applied), so ingress-nginx routes anything it doesn't otherwise recognize here via its *default backend* instead (see `../infra/ingress/ingress-nginx-values.yaml`).

Deliberately a separate deployable from `backend/`, not a route bolted onto it — see `../infra/PHASE4-RUNBOOK-B.md`'s IAM section: it runs under its own narrowly-scoped `reverse-proxy-role` (S3 `GetObject`/`ListBucket` only, on the `site-*` bucket prefix — no create, no write), so a compromise of this public-facing, unauthenticated service can't touch anything the backend or CI can.

## Files

| File | What it does |
|---|---|
| `app/main.py` | The whole service. `_lookup_bucket()` queries `domains` directly (not through the backend API — this is a hot path, one query per visitor request). `serve()` is a catch-all route: default key `index.html`, S3 `NoSuchKey` → 404, everything else streamed back with a guessed `Content-Type`. |
| `app/aws_client.py` | Same STS assume-role pattern as `backend/app/aws/sts.py` (own long-lived creds → `reverse-proxy-role` → temp creds, cached) — deliberately duplicated rather than imported from the backend package, since these are genuinely separate deployables with separate credentials. |
| `app/config.py` | Settings — `DATABASE_URL` (same Postgres instance/DB as the backend; see the known-follow-up note below) plus the AWS/role config. |

## Known limitation

Uses the backend's own `app` Postgres user rather than a dedicated read-only role scoped to `SELECT` on `domains`. Credential-wise this service could write to any table, though the code never does — see the "Known follow-ups" section in `../infra/PHASE4-RUNBOOK-B.md`.
