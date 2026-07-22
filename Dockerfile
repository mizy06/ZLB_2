FROM node:22-bookworm-slim AS frontend-build

WORKDIR /frontend

RUN corepack enable \
    && corepack prepare pnpm@10.14.0 --activate

COPY frontend/package.json \
    frontend/pnpm-lock.yaml \
    frontend/pnpm-workspace.yaml \
    ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN sed -i \
        -e 's|http://deb.debian.org/debian-security|https://mirrors.cloud.tencent.com/debian-security|g' \
        -e 's|http://deb.debian.org/debian|https://mirrors.cloud.tencent.com/debian|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        age \
        fonts-noto-cjk \
        libreoffice-impress \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend-build /frontend/dist /app/frontend/dist

RUN mkdir -p /app/.data/mindmap_engine /app/backend/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
