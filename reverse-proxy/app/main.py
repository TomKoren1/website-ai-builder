import mimetypes

from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.aws_client import s3_client
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url)

app = FastAPI(title="reverse-proxy")


async def _lookup_bucket(host: str) -> str | None:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT s3_bucket_name FROM domains WHERE domain_name = :host"),
            {"host": host},
        )
        row = result.first()
        return row[0] if row else None


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


# Catch-all: this service has exactly one job (resolve host -> bucket,
# proxy the object), so every path is handled the same way rather than
# having distinct routes per file type.
@app.get("/{path:path}")
async def serve(path: str, request: Request):
    # nginx forwards the original Host header through from the ingress
    # (see infra/ingress/manifests/localstack-ingress.yaml-style catch-all
    # rule this service sits behind) — that's the domain a visitor actually
    # typed, which is what's stored in `domains.domain_name`. Strip a port
    # if present (e.g. local testing on a non-80 port).
    host = request.headers.get("host", "").split(":")[0]
    bucket = await _lookup_bucket(host)
    if bucket is None:
        return PlainTextResponse("No site registered for this domain", status_code=404)

    # S3 keys aren't filesystem paths — a ".." in here just names a
    # differently-shaped object, not a real traversal — so no extra
    # validation is needed beyond picking a sane default key.
    key = path or "index.html"
    if key.endswith("/"):
        key += "index.html"

    try:
        obj = s3_client().get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return PlainTextResponse("Not found", status_code=404)
        raise

    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(content=obj["Body"].read(), media_type=content_type)
