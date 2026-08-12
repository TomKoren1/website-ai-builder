from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import get_settings
from app.routers import api_keys, auth, chat, domains, projects

settings = get_settings()

app = FastAPI(title="AI Website Builder API")

# allow_credentials=True is required for the browser to send/receive our
# auth cookies cross-origin (Next dev server on :3000, API on :8000) — and
# per the Fetch spec, allow_credentials=True cannot be combined with a
# wildcard origin, so this must name the frontend's exact origin rather
# than "*". expose the CSRF header name isn't needed here (that's a
# request header we read, not a response header the browser must be told
# it's allowed to expose to JS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(api_keys.router)
app.include_router(domains.router)
app.include_router(chat.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    # No auth on this route. The ServiceMonitor scrapes it in-cluster, but
    # KNOWN GAP: app-ingress.yaml's /api(/|$)(.*) rule forwards *any*
    # /api/* path to the backend after stripping the prefix, including
    # /api/metrics — so this is also reachable from outside the cluster
    # right now. Not urgent (no secrets in these metrics, just counts/
    # latencies) but worth tightening later with a dedicated Ingress rule
    # that 404s this one path before the general rule matches.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
