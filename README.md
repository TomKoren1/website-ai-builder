# AI Website Builder

A hands-on DevOps learning project built around a real product: friends log in, chat with an AI (their own LLM API key) to iteratively edit a website, preview it live, and push it — CI syncs the static site to S3 and it goes live on their own domain.

The product is the vehicle. The goal is practicing DevOps end-to-end — auth, secrets management, Kubernetes, IaC, GitOps, and observability — around one coherent, real user flow, instead of isolated tutorial exercises.

Full architecture, design decisions, and the phase-by-phase build plan live in [`overview.md`](./overview.md).

## Status

- [x] **Phase 1 — Local environment**: Kind cluster, ingress-nginx, LocalStack (S3/Route53/KMS/IAM/STS), least-privilege IAM via Terraform
- [ ] **Phase 2 — Backend & database**: PostgreSQL schema, FastAPI, AI orchestration, KMS envelope-encrypted API keys
- [ ] **Phase 3 — Frontend**: Next.js auth, live preview canvas
- [ ] **Phase 4 — GitOps & CI/CD**: Argo CD (platform infra) + CI-driven S3 sync (user site content)
- [ ] **Phase 5 — Observability**: kube-prometheus-stack, Grafana dashboards-as-code

## Architecture

| Layer | Choice |
|---|---|
| Frontend | Next.js |
| Backend / AI orchestrator | Python (FastAPI) |
| Database | PostgreSQL |
| Local cluster | Kind |
| AWS emulation | LocalStack (S3, Route53, KMS, IAM, STS) |
| GitOps (platform infra only) | Argo CD |
| CI/CD (user site content) | Drone / GitHub Actions Runner |
| Observability | Prometheus + Grafana |

Two deliberately separate deployment flows:
- **Platform infra** (ingress-nginx, LocalStack, the app's own frontend/backend) is reconciled by **Argo CD** from Git.
- **User site content** (the AI-generated static sites) is pushed by **CI** (`aws s3 sync`) — not something Argo CD touches, since S3 objects aren't Kubernetes resources.

See `overview.md` for the full reasoning, including corrections made along the way (domain→bucket routing, why ArgoCD is scoped the way it is, LocalStack's persistence/licensing limitations on the free plan).

## Repo structure

```
overview.md              full design doc — read this first
infra/
  kind/                   Kind cluster config
  ingress/                ingress-nginx Helm values + Ingress manifests
  localstack/             LocalStack Helm values (SERVICES, IAM enforcement, etc.)
  terraform/              LocalStack-backed AWS resources (S3, KMS, IAM least-privilege policy)
  up.ps1                  idempotent bring-up script for the whole Phase 1 stack
  PHASE1-RUNBOOK.md        manual step-by-step commands (what up.ps1 automates)
```

## Getting started (Phase 1)

**Prerequisites**: Docker, [Kind](https://kind.sigs.k8s.io/), `kubectl`, [Helm](https://helm.sh/), [Terraform](https://developer.hashicorp.com/terraform), AWS CLI, and a free [LocalStack](https://app.localstack.cloud) account (auth token required even for non-commercial use as of March 2026).

Bring the whole stack up:
```
powershell -ExecutionPolicy Bypass -File infra\up.ps1
```
It's idempotent — safe to run whether the stack is down, half up, or already running. First run will prompt for your LocalStack auth token (never stored in Git). See `infra/PHASE1-RUNBOOK.md` for the manual, step-by-step version if you want to understand what each step does before automating it.

## Why these choices

A few decisions worth calling out (details in `overview.md`):
- **Bucket-name-as-domain convention** for routing custom domains to S3 buckets — mirrors how real AWS + Route53 static hosting actually works.
- **Envelope encryption via KMS** for user-supplied LLM API keys, not Kubernetes Secrets — K8s Secrets are base64 (not encrypted) and meant for a handful of static values, not dynamically-created per-user secrets.
- **Argo CD scoped to platform infra only** — it reconciles Kubernetes resources from Git; pushing static files to S3 isn't a K8s object, so that path is CI-only.
