from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
