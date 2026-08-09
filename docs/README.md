# docs

Cross-cutting reference material that doesn't belong to one specific part of the codebase (unlike `backend/README.md`, `backend/WORKFLOW.md`, `frontend/README.md`, or the `infra/PHASE*-RUNBOOK.md` files, which are scoped to what they sit next to). This is where standalone write-ups accumulate — architecture deep-dives, incident/error postmortems, anything worth keeping but not tied to a single directory's lifecycle.

`overview.md` at the repo root remains the one place for the overall design and phase plan — files here supplement it, they don't replace it.

## Index

| File | What it covers |
|---|---|
| [`errors.md`](./errors.md) | Real bugs/incidents hit while building this project — root cause and fix for each, grouped by area (backend/data, security, frontend, infra). |
