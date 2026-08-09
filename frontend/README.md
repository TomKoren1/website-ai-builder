# Frontend

Next.js (App Router, TypeScript, Tailwind) client for the AI website builder — auth UI, project dashboard, the chat + live preview workspace, and API key management. See [`../overview.md`](../overview.md) for the product-level design and [`../backend/README.md`](../backend/README.md) / [`../backend/WORKFLOW.md`](../backend/WORKFLOW.md) for the API it talks to.

By design there is no Next.js API layer, no server-side session, and no SSR cookie-forwarding: every page is client-rendered and calls the FastAPI backend directly over `fetch` with `credentials: "include"`. FastAPI is the sole source of truth for identity — this app never has its own notion of a session.

## Getting started

```
npm install
npm run dev
```

Requires the backend running (see `../infra/PHASE2-RUNBOOK.md`) and `.env.local` set from `.env.local.example` — in particular `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`) and the backend's `FRONTEND_ORIGIN`/CORS config pointing back at `http://localhost:3000`.

## Directory structure

```
frontend/
├── app/                 Routes (App Router — one folder per URL segment)
├── components/          Shared, reusable UI pieces
├── lib/                 Everything that isn't a component: API client, auth context, preview logic
└── .env.local.example   Template for .env.local (committed; .env.local itself is gitignored)
```

## `lib/` — the non-visual core

| File | What it does |
|---|---|
| `api.ts` | The only place that calls the backend. A typed `request<T>()` wrapper around `fetch`: always sends `credentials: "include"` (so the httpOnly auth cookies ride along cross-origin to the FastAPI dev server), attaches `X-CSRF-Token` from the readable `csrf_token` cookie on every state-changing request (`POST`/`PUT`/`PATCH`/`DELETE`), and throws a typed `ApiError` (status + backend `detail`) on non-2xx. Exports one typed function per endpoint (`login`, `register`, `logout`, `me`, `listProjects`, `createProject`, `getProject`, `listApiKeys`, `createApiKey`, `deleteApiKey`, `createDomain`, `getMessages`, `chat`, `push`) plus the TS interfaces mirroring the backend's Pydantic schemas — deliberately kept snake_case field-for-field with the API responses rather than remapped to camelCase, so there's no translation layer to keep in sync. |
| `auth.tsx` | `AuthProvider`/`useAuth` — the single client-side auth context, mounted once in `app/layout.tsx`. Calls `GET /auth/me` on mount to establish "logged in or not" (the access token is httpOnly, so there's no other way to know from the client); `loading` starts `true` and every gated page waits on it before deciding what to render. `login`/`register`/`logout` call the backend then update local state and redirect. |
| `preview.ts` | `buildPreviewHtml(files, entryPath?)` — turns the AI's flat `{path: content}` file map into one self-contained HTML string for the sandboxed preview iframe. Inlines any local `<link rel="stylesheet">`/`<script src>` (a `srcDoc` iframe has no server, so a relative `css/style.css` reference would otherwise 404 silently) and injects a click-interceptor script that turns local `<a href>` clicks into a `postMessage` to the parent instead of a real (impossible) navigation. Regex-based on purpose — good enough for the plain static HTML this app deals with, not a general HTML parser. |

## `components/`

| File | What it does |
|---|---|
| `RequireAuth.tsx` | Wraps a page's content; redirects to `/login` once `useAuth()` resolves to no user, shows a loading state until then. Every authenticated route (`dashboard`, `api-keys`, `projects/[id]`) is wrapped in this rather than duplicating the check. |
| `Header.tsx` | Top nav — links to Projects/API Keys, current user email, log out. Renders nothing when logged out. |
| `PreviewFrame.tsx` | Owns the sandboxed `<iframe sandbox="allow-scripts" srcDoc={...}>` that renders `buildPreviewHtml`'s output. No `allow-same-origin` — this is AI-generated content the user hasn't reviewed yet, so it can run its own JS but can't reach this app's cookies, storage, or origin. Listens for the `preview-navigate` `postMessage` from `preview.ts`'s injected script to swap in a different page, and resets to the entry page whenever the `files` object gets a new identity (i.e. a new chat turn arrived). |

## `app/` — routes

| Route | What it does |
|---|---|
| `layout.tsx` | Root layout — wraps every page in `<AuthProvider><Header />{children}</AuthProvider>`. |
| `page.tsx` (`/`) | No UI of its own — redirects to `/dashboard` or `/login` once auth state resolves. |
| `login/page.tsx`, `register/page.tsx` | Email/password forms calling `useAuth().login` / `.register`. |
| `dashboard/page.tsx` (`/dashboard`) | Lists the user's projects, form to create a new one (which also provisions a Gitea repo backend-side — surfaces the backend's error detail directly since repo creation is the slow/likely-to-fail step). |
| `api-keys/page.tsx` (`/api-keys`) | Add/list/delete LLM provider API keys. Reads only ever show `display_hint` (a masked preview) — the plaintext key is never sent back down after creation. |
| `projects/[id]/page.tsx` (`/projects/:id`) | The main workspace: chat panel + live preview + push button. See below. |

### The workspace (`projects/[id]/page.tsx`)

This is the one nontrivial page, so it's worth spelling out the state model:

- **`turns`** — the visible chat log (`{role, content}[]`).
- **`files`** — a `Record<path, content>` accumulated across turns, not any single response. Each `/chat` response only includes files it created or changed (per the backend's system prompt), so this running merge is the actual current state of the site; both the preview and the push button read from it.
- **History hydration** — on mount, `GET /projects/:id/messages` is fetched and replayed: each stored assistant message's `content` is the same raw JSON shape a live `/chat` response has (`{reply, files}`), so `mergeProposedFiles` rebuilds both `turns` and `files` from it exactly the way a live session would have built them. Without this, a page reload would lose the conversation and the proposed-but-unpushed files even though both still exist server-side.
- **Push** — flattens the current `files` map to a list and calls `POST /projects/:id/push`, which commits to the project's Gitea repo. Nothing is written to Git until this is clicked — chat only ever proposes.

## Known constraints (worth knowing before "fixing" them)

- **No SSR, no Next.js API routes, no middleware-based auth** — an explicit design choice (see `overview.md` Phase 3), not an oversight. Everything talks to FastAPI directly from the browser.
- **The preview iframe has no server behind it.** Multi-page navigation and local asset references are simulated (`preview.ts` inlining + `postMessage`), not real HTTP — that's why they're regex-based rather than following actual links.
