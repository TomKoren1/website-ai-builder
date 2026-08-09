FROM python:3.12-slim

WORKDIR /app

# System deps for building cryptography/asyncpg wheels if no prebuilt
# wheel matches this platform; removed from the final layer isn't worth
# the complexity of a multi-stage build here — this image is already slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .

RUN useradd --system --create-home app
USER app

EXPOSE 8000
# Migrations are deliberately NOT run here — `alembic upgrade head` on
# container start races if more than one replica starts at once. Run it
# as a one-off (kubectl exec into a running pod, or a Job) instead — see
# infra/PHASE4-RUNBOOK.md.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
