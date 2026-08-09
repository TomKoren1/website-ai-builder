# Backend Workflow

How requests actually flow through the system, and where every piece of data lives. `README.md` maps files to purpose; this file maps *behavior*.

## External dependencies — how the backend reaches each one

```
                          ┌─────────────────────────────────────────┐
                          │              FastAPI backend             │
                          └───┬────────────┬────────────┬───────────┘
                              │            │            │
                    ┌─────────┘            │            └─────────┐
                    ▼                      ▼                      ▼
              PostgreSQL              LocalStack              Gitea
        (users, projects,      (S3/Route53/KMS/IAM/STS   (per-project git
         api_keys, messages,    — Phase 1 infra)          repos — Phase 2)
         deployments, ...)
```

| Dependency | Local dev address | Why that address |
|---|---|---|
| Postgres | `localhost:5432` via `kubectl port-forward` | Deliberately has no Ingress route — a DB shouldn't be reachable that way even locally. |
| LocalStack | `http://localstack.local` (ingress) | Same hostname the `aws` CLI and Terraform already use — one consistent path in, not a separate port-forward. |
| Gitea | `http://gitea.local` (ingress) | Same reasoning as LocalStack. |
| Anthropic / OpenAI | real internet APIs | Only ever called with a *user's own* decrypted key, in-memory, for the duration of one request. |

Once the backend itself is containerized and deployed in-cluster (Phase 4), all four addresses change to in-cluster Service DNS (e.g. `postgres.postgres.svc.cluster.local`) — see the comments at the top of `.env.example`.

## Auth: register / login / refresh / logout

```
register/login
  → argon2 hash check (or create) in `users`
  → issue access token (JWT, 15 min, signed HS256)
  → issue refresh token (random 256-bit string)
       - raw token  → httpOnly cookie, scoped to /auth/refresh only
       - sha256(token) → stored in `sessions.refresh_token_hash`
  → issue a CSRF token (random string) → NON-httpOnly cookie, path "/"
  → all three set as Set-Cookie on the response
       (CSRF cookie deliberately readable by JS — see below)

every protected route
  → reads access token from cookie OR `Authorization: Bearer`
  → verifies JWT signature + expiry
  → loads User by the `sub` claim

every state-changing route (POST/DELETE — not GET, not register/login)
  → verify_csrf: compare the csrf_token cookie against an X-CSRF-Token
    request header the frontend must set itself
  → reject (403) if either is missing or they don't match
  → why this works: an attacker's cross-site page can trigger a request
    that carries our cookies automatically (that's what SameSite=strict
    already blocks in most cases), but same-origin policy stops that page
    from ever reading the cookie's *value* — so it can't also produce a
    matching header. This is defense-in-depth on top of SameSite, not a
    replacement for it.

refresh (itself CSRF-protected, since it's state-changing)
  → look up sessions row by sha256(cookie's raw refresh token)
  → reject if missing or expired
  → ROTATE: overwrite that row's hash + expiry, mint new access+refresh
    tokens AND a new CSRF token
  → old refresh token cookie is now worthless — replaying it fails the hash lookup

logout (also CSRF-protected)
  → delete the sessions row matching the current refresh cookie
  → clear all three cookies

GET /auth/me
  → just get_current_user, no CSRF check (it's a read)
  → how the frontend learns "am I logged in, and as who" on page load,
    since the access token itself can't be read by JS to check directly
```

**Where it's stored**: `users` (email, argon2 hash), `sessions` (hashed refresh token + expiry — never the raw token). The JWT access token and the CSRF token are never persisted anywhere server-side; the access token is stateless (verified by signature), and the CSRF token is verified by simple cookie/header equality, not a DB lookup.

## Creating a project

```
POST /projects
  → verify caller is authenticated (get_current_user)
  → gitea_client.create_repo(): POST to Gitea's REST API,
      creates a new private repo under the fixed "projects" org
  → INSERT into `projects` (user_id, name, git_repo_path="projects/project-<hex>")
```

**Where it's stored**: the row in `projects` (metadata only) + the actual repo living in Gitea. The backend never stores site *content* itself — Gitea is the source of truth for that.

## Storing an API key (envelope encryption)

```
POST /api-keys  { provider, api_key }
  → generate a fresh 256-bit DEK (Data Encryption Key), locally, in memory
  → AES-256-GCM encrypt the API key with that DEK  → ciphertext + nonce
  → wrap the DEK itself via KMS:
       sts.py:  orchestrator-app's static creds → sts:AssumeRole → temp creds
       kms.py:  temp creds → kms:Encrypt(dek) → encrypted_dek
  → INSERT into `api_keys`: ciphertext, encrypted_dek, nonce, display_hint
       (display_hint computed once from the plaintext, before it's discarded —
        it's the only reason a later GET can show a masked preview at all)
  → plaintext key and raw DEK go out of scope here — never logged, never cached
```

**Where it's stored**: `api_keys.ciphertext` / `.encrypted_dek` / `.nonce` (all encrypted blobs) + `.display_hint` (safe to show, e.g. `sk-a...cdef`). The plaintext key is never written to disk anywhere, ever — only reconstructed transiently inside a `/chat` request.

## Chat (the core AI loop)

```
POST /projects/{id}/chat  { provider, message }
  1. verify project belongs to caller
  2. look up api_keys row for (user, provider)
  3. DECRYPT (reverse of the storage flow):
       kms:Decrypt(encrypted_dek) via the same STS-assumed temp creds → DEK
       AES-256-GCM decrypt(ciphertext, nonce, DEK) → plaintext API key
  4. load this project's conversation history from `messages`
  5. call the provider adapter (app/llm/registry.py) with:
       - the decrypted key (used only for this one call)
       - a system prompt instructing a strict JSON output contract:
         {"reply": "...", "files": [{"path": "...", "content": "..."}]}
  6. json.loads() the model's response
  7. validate every returned file path via is_safe_project_path()
       (rejects "../", absolute paths — the LLM's output is untrusted input)
  8. store both the user message and the raw assistant JSON in `messages`
  9. update api_keys.last_used_at
  10. return {reply, proposed_files} to the caller

  Nothing is written to Git yet. This is a PREVIEW.
```

**Where it's stored**: `conversations` (one per project) + `messages` (role/content pairs — the assistant's stored content is the raw JSON the model returned, so it round-trips correctly as context on the next turn). The proposed files exist only in the HTTP response at this point — not in Gitea, not anywhere else.

## Push (preview → committed → deployed)

```
POST /projects/{id}/push  { files, commit_message }
  → verify project belongs to caller
  → validate every path via is_safe_project_path() again
      (independently of chat — push doesn't trust that its input necessarily
       came from a validated chat response)
  → gitea_client.commit_files(): one Gitea "create or update file" API call
      per file, against the project's repo, branch "main"
  → look up this project's `domains` row (a project may not have one yet)

  no domain registered:
    → INSERT into `deployments` (status="success", deployed_at=now)
        (nothing to actually deploy to — the commit landing in Git is the
         only meaningful outcome, so there's no "pending" state to be in)

  domain registered:
    → generate a one-time token: raw value + sha256(raw) — same
      hash-not-plaintext pattern as refresh tokens
    → INSERT into `deployments` (status="pending", callback_token_hash=hash)
    → gitea_client.dispatch_workflow(): triggers the project's
      .gitea/workflows/deploy.yml (seeded at project creation — see
      projects.py) via Gitea's Actions API, passing {bucket_name,
      project_id, deployment_id, raw_token} as workflow_dispatch inputs
    → response returns to the caller immediately — status is still
      "pending" at this point; the frontend doesn't wait for CI
```

**Where it's stored**: the actual site files live in Gitea from this point on (that's the real deployment artifact). `deployments` in Postgres is a log of push attempts; `status` starts `pending` (when there's something to deploy) or `success` (when there isn't) and is updated by the callback below.

## Deployment callback (CI → backend)

```
POST /projects/{id}/deployments/{id}/callback  { status, token }
  → NO get_current_user, NO CSRF — the caller is a CI job, not a browser
    session; the token itself is the only authentication
  → load the Deployment row, reject (404) unless:
      - it exists and belongs to this project
      - callback_token_hash is non-null (i.e. not already consumed)
      - sha256(body.token) matches callback_token_hash
        (secrets.compare_digest — constant-time, same discipline as CSRF)
  → UPDATE deployments: status = body.status, deployed_at = now,
    callback_token_hash = NULL
      (nulling it out is what makes this single-use — a replayed callback,
       or a second one from a superseded push, now just 404s)
```

Runs inside `.gitea/workflows/deploy.yml`, after `aws s3 sync` (using
`ci-deploy-role`'s write-only credentials — see `infra/terraform/main.tf`)
either succeeds or fails against LocalStack S3. From there, a visitor
reaching the site goes through a *separate* service entirely — see
`../reverse-proxy/` — which reads `domains`/`s3_bucket_name` directly and
proxies the object using its own read-only `reverse-proxy-role`
credentials. The backend has no role in serving traffic once a deployment
succeeds; it only ever brokers the create-bucket and report-status steps.

## Quick reference: "where is X?"

| Data | Lives in |
|---|---|
| User's password | `users.password_hash` (argon2, never plaintext) |
| Refresh token | `sessions.refresh_token_hash` (sha256, never plaintext) + raw value only in the client's httpOnly cookie |
| Access token | Nowhere server-side — stateless JWT, verified by signature |
| User's LLM API key | `api_keys.ciphertext`/`.encrypted_dek`/`.nonce` (KMS-wrapped envelope encryption); plaintext only ever exists transiently in memory during a `/chat` call |
| Chat history | `messages`, one row per turn, linked via `conversations.project_id` |
| Generated site files (preview) | Nowhere persistent — only in the `/chat` HTTP response until pushed |
| Generated site files (pushed) | The project's Gitea repo (`projects/project-<hex>`), branch `main`, then synced by CI into `s3://site-{project_id}` |
| Deploy history | `deployments` (metadata only — the files themselves are in Gitea/S3, not duplicated into Postgres) |
| Deployment callback token | `deployments.callback_token_hash` (sha256, never plaintext) + raw value only ever in the CI job's `workflow_dispatch` inputs, single-use |
| Domain → bucket mapping | `domains.domain_name` / `.s3_bucket_name` — read directly by `reverse-proxy/` (not through the backend API) to serve visitor traffic |
