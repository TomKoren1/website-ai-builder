# Project Overview: AI-Powered Website Builder

## What This Is

A DevOps learning project built around a real, working product: friends log in, chat with an AI (using their own LLM API key) to iteratively edit a website, preview the result live, and — once happy — push it. The push commits the generated site to Git, CI syncs it to S3, and it's served on their own domain.

The product is the vehicle. The goal is hands-on practice across auth, multi-tenancy, secrets management, GitOps, Kubernetes, IaC-style AWS emulation, and observability, all wired around one coherent user flow.

---

## Architecture & Tech Stack

* **Frontend**: Next.js — auth UI, project management, live preview canvas.
* **Backend & AI Orchestrator**: Python (FastAPI) — handles API requests, calls the LLM, validates/writes generated files, coordinates git commits and deploys.
* **Database**: PostgreSQL — users, auth/session tokens, projects, domain mappings, encrypted API keys, chat history, deployment history.
* **Infrastructure & Emulation**: Kind (Kubernetes in Docker) for the local cluster; LocalStack to emulate AWS services (S3 for static site hosting, Route53, **KMS** for secret encryption).
* **GitOps & Deployment**: A self-hosted Git server, CI/CD (Drone or GitHub Actions Runner), and Argo CD for platform-infra sync.
* **Monitoring**: Prometheus (via kube-prometheus-stack) + Grafana.

### Design corrections worth remembering (why they matter is inline below)

1. **Ingress can't route "by host header" straight to an S3 bucket.** NGINX Ingress backends must be a `ClusterIP` Service. Custom-domain routing needs either (a) naming the bucket exactly like the domain and relying on S3 virtual-hosted-style resolution (how real AWS + Route53 does it), or (b) a small reverse-proxy service that looks up `domain → bucket` in Postgres and proxies path-style to LocalStack S3. Build (b) first — it's more reliable in Kind/LocalStack and teaches you more.
2. **Argo CD does not deploy user website content.** ArgoCD reconciles Kubernetes resources from Git; pushing static files to S3 isn't a K8s object. ArgoCD's job is the *platform* (ingress-nginx, LocalStack, ESO, your own Next.js/FastAPI Deployments, Prometheus/Grafana). The "friend pushes → site goes live" path is handled entirely by CI (`aws s3 sync` against LocalStack), with no ArgoCD involvement.
3. **LocalStack Route53 won't resolve public DNS.** It's useful for practicing hosted-zone/record-set API calls and Terraform, but "his own domain" only becomes real once real Route53 (or any registrar) points at a real ingress/ALB IP. Keep that boundary explicit so Phase 1 doesn't quietly imply public reachability.

---

## API Key Security (cross-cutting — touches Phase 1, 2)

Friends bring their own LLM API key. It must never be stored in plaintext or handled like a Kubernetes Secret (K8s Secrets are base64-encoded, not encrypted, and meant for a handful of static cluster-level values — not per-user secrets created dynamically at runtime).

**Pattern: envelope encryption via KMS, stored in Postgres.**

1. User submits their API key over TLS to the FastAPI backend.
2. Backend generates a random **Data Encryption Key (DEK)**, encrypts the API key with it (AES-256-GCM).
3. Backend calls **KMS** (LocalStack locally, real AWS KMS later) to encrypt that DEK with a **Customer Master Key (CMK)** — the CMK itself never leaves KMS.
4. Postgres stores `ciphertext`, `encrypted_dek`, `nonce` — never plaintext.
5. At runtime, when the orchestrator needs the key: call `kms:Decrypt` on the encrypted DEK → decrypt the API key in memory → use it for the LLM call → discard immediately. Never logged, never written to disk.
6. Restrict `kms:Decrypt` to only the orchestrator's service account (least privilege, same principle as IRSA for ESO).
7. UI only ever shows a masked key (`sk-...ab12`) after entry, with a revoke/replace action.

This is what AWS Secrets Manager does internally — doing it directly against KMS + Postgres fits a high-cardinality, user-generated secret much better than provisioning a Secrets Manager entry per user (which also costs $0.40/secret/month at scale).

---

## Development Phases

### Phase 1: Local Environment Setup (Infrastructure)

**Kind Cluster**
- `kind create cluster --config kind-config.yaml` with `extraPortMappings` for 80/443 on the control-plane node — the only way to get real HTTP/HTTPS into a Kind cluster from the host.
- Single control-plane + 1–2 worker nodes is enough to practice scheduling/labels without overhead.

**LocalStack**
- Deploy via the `localstack/localstack` Helm chart, in-cluster, so Ingress/Services can address it like any other backend.
- `SERVICES=s3,route53,kms,iam,sts` — IAM and STS included so we can practice writing and attaching least-privilege policies (e.g. scoping the orchestrator's role to only `kms:Decrypt` on its own key, only `s3:PutObject`/`s3:GetObject` on customer buckets) against LocalStack's IAM enforcement, and use `AssumeRole`/STS for the service-to-service auth pattern instead of static credentials everywhere.
- `PERSISTENCE=1` set, but **confirmed non-functional on the free plan** — LocalStack's snapshot persistence has been paid-plan-only since v1.0. Treat LocalStack as ephemeral: a pod restart wipes buckets/keys/IAM state, recovered by re-running `terraform apply` (idempotent). Not a problem in practice since real site content is always re-derivable from Git via CI sync, never stored only in LocalStack.

**Ingress-NGINX**
- Install via Helm, `ingressClassName: nginx`.
- Two Ingress resources:
  - App domain (e.g. `app.local`) → frontend Service (Next.js); `/api` path → backend Service (FastAPI).
  - Catch-all/default-backend Ingress for unmatched hosts → the reverse-proxy Service that resolves custom domains to S3 buckets (see correction #1).
- Enable TLS even locally (self-signed or cert-manager) — `ssl-redirect` annotation, matching the "Always Use TLS" production practice even in dev.

---

### Phase 2: Backend & Database

**PostgreSQL schema**
```
users            id, email, password_hash, created_at
sessions         id, user_id, refresh_token_hash, expires_at, created_at
projects         id, user_id, name, git_repo_path, created_at
domains          id, project_id, domain_name, s3_bucket_name, verified, created_at
api_keys         id, user_id, provider, display_hint, ciphertext, encrypted_dek, nonce, created_at, last_used_at
conversations    id, project_id, created_at
messages         id, conversation_id, role, content, created_at
deployments      id, project_id, git_commit_sha, status, deployed_at
```
- `sessions`: JWT access tokens short-lived (~15 min), stateless. Refresh tokens stored **hashed**, rotated on each use so a leaked one can be revoked.
- `api_keys`: maps directly to the envelope-encryption design above.

**Python API (FastAPI)**
Core endpoints:
- `POST /auth/register`, `/auth/login`, `/auth/refresh`
- `POST /projects`, `GET /projects/:id` — creates a per-project Git repo on the self-hosted Git server at creation time; this is what the AI orchestrator commits to.
- `POST /projects/:id/chat` — loads current project file tree + user message, calls the LLM, returns a proposed file diff to the frontend for preview. **Does not commit** — matches the "preview first, push explicitly" requirement.
- `POST /projects/:id/push` — commits the currently-previewed files to the project's Git repo, triggering CI (Phase 4).
- `POST /api-keys`, `DELETE /api-keys/:id` — encrypt-on-write via KMS; reads only ever return a masked preview, never plaintext.
- `POST /domains` — records the domain→bucket mapping the reverse-proxy reads.

**AI orchestration**
- Output is static HTML/CSS/JS — no arbitrary code execution/sandboxing needed server-side.
- Still validate: LLM-returned file paths must never escape the project directory (basic path-traversal check) before anything is written to the Git working tree.

---

### Phase 3: Frontend Development

**Auth**
- FastAPI is the source of truth for identity — skip NextAuth's own DB/session model. Next.js calls the FastAPI `/auth` endpoints directly, stores the access token in an **httpOnly, Secure, SameSite=strict** cookie (not localStorage — avoids XSS token theft).
- Add CSRF protection since auth is now cookie-based (double-submit token, or rely on `SameSite=strict` for same-site API calls).

**Canvas & Preview**
- Render the AI's proposed HTML/CSS/JS in a **sandboxed iframe** via `srcDoc`: `<iframe sandbox="allow-scripts" srcDoc={generatedHtml} />`.
- No need to actually deploy anything to preview it — the sandbox attribute contains whatever the AI-generated page runs, which matters since it's content the user hasn't reviewed yet.

---

### Phase 4: GitOps & CI/CD

Two distinct flows — do not conflate them (see correction #2):

**Flow A — platform infra (ArgoCD)**
- App-of-Apps pattern: one root Application → `applications/{infrastructure,platform,apps}`.
- Sync waves: namespaces/RBAC (`-1`) → LocalStack/ESO/ingress-nginx (`0`) → backend/frontend Deployments (`1`) → Prometheus/Grafana (`2`).
- Repo pattern: **app repo + GitOps repo split** — Next.js/FastAPI source in one repo, Helm values/Application manifests in a separate `gitops-repo`. CI builds an image, then updates the GitOps repo's image tag (Argo CD Image Updater, or a scripted `kustomize edit set image` + commit).

**Flow B — user site content (CI only, no ArgoCD)**
- Each project's Git repo (created in Phase 2) has a CI pipeline (Drone/Actions Runner) triggered on push.
- Pipeline: lint/validate HTML → `aws s3 sync ./site s3://<bucket> --endpoint-url=http://localstack:4566` → callback to the API to update the `deployments` row (status, commit SHA).
- This is the actual "friend pushes → site is live" mechanism. ArgoCD is not involved.

---

### Phase 5: Monitoring & Observability

- Use the **kube-prometheus-stack** Helm chart (Prometheus Operator + Grafana + Alertmanager + kube-state-metrics bundled) rather than raw Prometheus — gives ServiceMonitor CRDs instead of hand-edited scrape configs.
- Instrument FastAPI with `prometheus_client`, expose `/metrics`, add a `ServiceMonitor` for auto-discovery.
- App-specific metrics worth tracking (beyond generic CPU/memory): LLM request latency and error rate, S3 push success/failure count, active chat sessions, per-user request rate (useful later for abuse/rate-limiting decisions).
- **Dashboards-as-code**: store Grafana dashboard JSON in the GitOps repo, provision via the sidecar/ConfigMap pattern — versioned, not hand-built in the UI.
- Lock down Grafana/ArgoCD UIs with real auth (no default admin/admin), scope RBAC roles (e.g. a `developer` Role that can view but not edit dashboards).

---

## Next Steps

- [ ] Scaffold Phase 1: Kind config + LocalStack Helm values + the two Ingress manifests
- [x] Define least-privilege IAM roles/policies in LocalStack (orchestrator role, ESO role) + STS AssumeRole wiring (Phase 1) — policy/role/trust-policy written correctly in Terraform; local *enforcement* of it is broken in the current LocalStack version (confirmed via testing, matches [upstream issue #7183](https://github.com/localstack/localstack/issues/7183)), so verification stops at "the code is correct," not "the emulator proved it."
- [ ] Decide reverse-proxy implementation for domain→bucket routing (Phase 1 / correction #1)
- [ ] Postgres schema migration for the tables above (Phase 2)
- [ ] FastAPI skeleton + KMS envelope-encryption helper for API keys (Phase 2)
