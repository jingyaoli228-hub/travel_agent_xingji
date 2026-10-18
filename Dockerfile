# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_AMAP_JS_API_KEY=""
ARG VITE_AMAP_JS_SECURITY_CODE=""
ENV VITE_AMAP_JS_API_KEY=${VITE_AMAP_JS_API_KEY}
ENV VITE_AMAP_JS_SECURITY_CODE=${VITE_AMAP_JS_SECURITY_CODE}
RUN npm run build

FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple \
    PIP_DEFAULT_TIMEOUT=30 \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache
WORKDIR /app
RUN sed -i 's|http://deb.debian.org|https://mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY requirements.txt ./
RUN pip install --no-cache-dir --retries 5 --timeout 30 -r requirements.txt
COPY --chown=app:app travel_agent ./travel_agent
COPY --chown=app:app config ./config
COPY --chown=app:app prompts ./prompts
COPY --chown=app:app intent_data ./intent_data
COPY --chown=app:app evaluation_cases ./evaluation_cases
COPY --chown=app:app skills ./skills
COPY --chown=app:app scripts ./scripts
RUN mkdir -p /home/app/.cache && chown -R app:app /home/app/.cache
USER app
EXPOSE 8000
CMD ["uvicorn", "travel_agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]

FROM caddy:2.10-alpine AS web
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-build /src/frontend/dist /srv

