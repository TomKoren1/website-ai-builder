from fastapi import FastAPI

from app.routers import api_keys, auth, chat, domains, projects

app = FastAPI(title="AI Website Builder API")

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(api_keys.router)
app.include_router(domains.router)
app.include_router(chat.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
