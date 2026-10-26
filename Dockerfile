# Doua imagini din acelasi proiect (ADR 0004):
#   ingest    - colectare + programare; Chromium vine din imaginea Playwright
#   dashboard - doar Streamlit, citeste copia data/bvb_read.duckdb
# Datele nu intra in imagine: data/ se monteaza din host.

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

# --- ingest ------------------------------------------------------------------
# Versiunea imaginii trebuie sa fie aceeasi cu playwright din uv.lock.
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble AS ingest
COPY --from=uv /uv /usr/local/bin/uv
ENV TZ=Europe/Bucharest \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    BVB_DATA_DIR=/data \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
USER pwuser
CMD ["bvb", "schedule"]

# --- dashboard ---------------------------------------------------------------
FROM python:3.12-slim AS dashboard
COPY --from=uv /uv /usr/local/bin/uv
ENV TZ=Europe/Bucharest \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    BVB_DATA_DIR=/data \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 bvb
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
USER bvb
EXPOSE 8501
# 0.0.0.0 doar in reteaua Docker; compose nu publica portul decat pe 127.0.0.1 al host-ului.
CMD ["bvb", "dashboard", "--address", "0.0.0.0"]
