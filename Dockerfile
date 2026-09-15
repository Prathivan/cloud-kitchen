# Container image for platforms that deploy from a Dockerfile rather
# than a buildpack (Aiven, Fly.io, Railway's Docker mode, a VPS, etc.)
# -- Render doesn't need this (it uses build.sh + Procfile instead),
# but this is required for anything that specifically wants a
# Dockerfile/compose.yaml, like Aiven's "Deploy from GitHub" scanner.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# libjpeg/zlib: needed at runtime by Pillow to handle the project's
# .jpeg images (menu photos, logo, etc.) -- psycopg2-binary already
# bundles its own libpq, so no separate Postgres client library needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh

# Most container platforms (Aiven included) inject $PORT at runtime and
# expect the app to bind to it -- docker-entrypoint.sh reads this, so
# EXPOSE here is documentation for local `docker run`, not a hard
# requirement of the platform.
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
