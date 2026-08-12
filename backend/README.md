# Backend

FastAPI service for the AI website builder — auth, project/Git management, envelope-encrypted API key storage, and the AI chat/push flow. See [`../overview.md`](../overview.md) for the product-level design and [`../infra/PHASE2-RUNBOOK.md`](../infra/PHASE2-RUNBOOK.md) for how to get this running locally.

For how the pieces connect at runtime (request flows, where data actually lives), see [`WORKFLOW.md`](./WORKFLOW.md) — this file is about what each file *is*, that one is about what *happens*.

## Directory structure

```
backend/
├── requirements.txt        Python dependencies (pinned)
├── alembic.ini              Alembic config — points at migrations/
├── .env.example             Template for .env (committed; .env itself is gitignored)
├── migrations/               Alembic migration environment + generated migrations
│   ├── env.py                 Wires Alembic to our async engine + models
│   ├── script.py.mako         Template new migration files are generated from
│   └── versions/               Generated migration files (one per schema change)
└── app/                      The actual application package
```

## `app/` — file by file

### Top level

| File | What it does |
|---|---|
| `main.py` | FastAPI app instance. Wires every router in `app/routers/` into the app, plus CORS middleware (allows only `settings.frontend_origin`, credentials on — required for the browser to send/receive auth cookies cross-origin to the Next dev server). `/metrics` (Phase 5) exposes `app/metrics.py`'s custom metrics plus `prometheus_client`'s default process/GC metrics, unauthenticated — see the comment on that route for a known exposure gap via the `/api/*` Ingress rule. Entry point for `uvicorn app.main:app`. |
| `config.py` | `Settings` (pydantic-settings) — the single source of truth for every env var. Reads `.env` locally; reads real environment variables once deployed. Everything else imports `get_settings()` rather than touching `os.environ` directly. Includes `environment` (gates the cookie `Secure` flag — off for `next dev`'s plain-HTTP local server) and `frontend_origin` (the CORS allowlist entry). |
| `db.py` | SQLAlchemy async engine + session factory + declarative `Base`. `get_db()` is the FastAPI dependency every route uses to get a DB session. |
| `models.py` | SQLAlchemy ORM models — the 7 tables from `overview.md` (`users`, `sessions`, `projects`, `domains`, `api_keys`, `conversations`, `messages`, `deployments`). This is the schema's source of truth; Alembic migrations are generated *from* this file, not the other way around. `deployments.callback_token_hash` (Flow B) holds the hash of the one-time token handed to CI — see `chat.py`. |
| `schemas.py` | Pydantic request/response models (what the API actually accepts and returns) — deliberately separate from `models.py` (the DB shape) so the two can diverge, e.g. `ApiKeyOut` never has a `ciphertext` field even though the DB row does. `DomainCreate` deliberately has no `s3_bucket_name` field — see `domains.py`. `DeploymentCallback` is the one schema with no user auth behind it (see `chat.py`). |
| `crypto.py` | Envelope encryption for user-supplied LLM API keys: generates a per-row AES-256-GCM key (DEK), encrypts the API key with it, wraps the DEK via KMS. This is the implementation of the "API Key Security" design in `overview.md`. |
| `metrics.py` | Phase 5 — `prometheus_client` Counter/Histogram/Gauge definitions: `llm_requests_total`/`llm_request_duration_seconds` (by provider), `chat_requests_in_progress`, `deployment_callbacks_total` (Flow B's actual S3-push success/failure signal). Incremented from `chat.py`; scraped via `/metrics` (`main.py`) by the `ServiceMonitor` in `helm/backend/templates/`. |
| `gitea_client.py` | Thin HTTP client (`httpx`) for the Gitea REST API — creates a repo per project, commits/updates files in it, and (Flow B) `dispatch_workflow()` triggers a project's `.gitea/workflows/deploy.yml` via Gitea's Actions API with per-deployment inputs. Everything under a fixed `projects` org, since our users aren't Gitea users themselves. |

### `app/security/` — auth primitives

| File | What it does |
|---|---|
| `passwords.py` | Argon2 password hashing (`hash_password`/`verify_password`). |
| `jwt.py` | Access-token creation/verification (JWT, HS256) and refresh-token generation/hashing. Refresh tokens are opaque random strings, hashed with SHA-256 before storage — not JWTs, since they're checked against the DB anyway (to support revocation). |
| `deps.py` | `get_current_user` — the FastAPI dependency every protected route depends on. Reads the access token from either an httpOnly cookie or an `Authorization: Bearer` header, verifies it, loads the `User`. |
| `csrf.py` | Double-submit CSRF protection. `verify_csrf` is a dependency applied to every state-changing route: compares the non-httpOnly `csrf_token` cookie against an `X-CSRF-Token` header the frontend must echo back. An attacker's cross-site request can ride on auto-attached cookies but can't read the cookie's value to also set a matching header. Not applied to `register`/`login` (no CSRF cookie exists yet at that point) or any `GET`. |

### `app/aws/` — talking to LocalStack (later: real AWS)

| File | What it does |
|---|---|
| `sts.py` | Holds the orchestrator-app's only long-lived credentials and uses them for exactly one thing: `sts:AssumeRole` into `orchestrator-role` (the least-privilege role from Phase 1's Terraform). Caches the resulting temporary credentials in memory, refreshing shortly before they expire. |
| `kms.py` | `encrypt_dek`/`decrypt_dek` — calls KMS using the *temporary* credentials from `sts.py`, never the long-lived ones directly. This is what `crypto.py` calls into. |
| `s3.py` | `ensure_bucket_exists()` (Flow B) — creates a project's `site-{project_id}` bucket via the same assumed-role pattern. `orchestrator-role` only grants `s3:CreateBucket`/`ListBucket` on the `site-*` prefix — it never writes or reads object content; that's `ci-deploy-role`'s and `reverse-proxy-role`'s job respectively (separate identities entirely — see `infra/terraform/main.tf` and `reverse-proxy/`). |

### `app/llm/` — the provider-agnostic AI layer

| File | What it does |
|---|---|
| `base.py` | `LLMProvider` abstract interface + `ChatMessage` — the shape every provider adapter implements. |
| `anthropic_provider.py` | Calls Claude (`claude-opus-5`) via the official `anthropic` SDK. |
| `openai_provider.py` | Calls OpenAI's chat completions API. Model default here is explicitly flagged as unverified (unlike the Anthropic one, checked against a live model catalog) — confirm before relying on it. |
| `registry.py` | `get_provider(name)` — maps the `provider` string stored on an `api_keys` row (`"anthropic"` / `"openai"`) to the right adapter instance. |

### `app/routers/` — the actual API endpoints

| File | Endpoints | What it does |
|---|---|---|
| `auth.py` | `POST /auth/register`, `/login`, `/refresh`, `/logout`, `GET /auth/me` | Issues JWT access tokens + rotating hashed refresh tokens (httpOnly cookies) + a CSRF token (non-httpOnly). `/me` returns the current user — how the frontend learns "am I logged in," since the access token itself is unreadable by JS by design. |
| `projects.py` | `POST /projects`, `GET /projects`, `GET /projects/{id}` | Creates a project + its backing Gitea repo, and (Flow B) seeds `.gitea/workflows/deploy.yml` into it — a generic, `workflow_dispatch`-only workflow parameterized entirely via dispatch inputs, so it's identical across every project and never needs editing per-repo. Lists/fetches a user's own projects. |
| `api_keys.py` | `POST /api-keys`, `GET /api-keys`, `DELETE /api-keys/{id}` | Encrypt-on-write via `crypto.py`; reads only ever return `display_hint` (a masked preview), never plaintext. |
| `domains.py` | `POST /domains` | Records a project's custom-domain → S3-bucket mapping (consumed by the reverse-proxy — see `reverse-proxy/`). The bucket name (`site-{project_id}`) is generated here, never taken from the client, and the bucket is created here too (`app/aws/s3.py`) — reused across a project's later domains rather than created per-domain. |
| `chat.py` | `GET /projects/{id}/messages`, `POST /projects/{id}/chat`, `POST /projects/{id}/push`, `POST /projects/{id}/deployments/{id}/callback` | The core AI loop, plus `/messages` for the frontend to reconstruct chat history + accumulated files on page load. `/push` commits to Gitea and — if the project has a domain registered — creates the `Deployment` as `pending`, generates a one-time hashed callback token, and dispatches the CI workflow; `/callback` is how that workflow reports `success`/`failed` back (token-authenticated, no user session — see `WORKFLOW.md`). See `WORKFLOW.md` for the full request lifecycle. |

### `app/utils/`

| File | What it does |
|---|---|
| `paths.py` | `is_safe_project_path` — rejects any LLM-returned file path that tries to escape the project directory (`../`, absolute paths). The one server-side safety check the "AI writes files" design actually needs. |

## Migrations

Schema changes go: edit `app/models.py` → `alembic revision --autogenerate -m "..."` → **read the generated file** → `alembic upgrade head`. Autogenerate is a starting point, not something to trust blindly — this project has already hit a real Alembic gotcha (`compare_type` isn't on by default, so type-only column changes are silently skipped unless `migrations/env.py` explicitly enables it — it now does).
