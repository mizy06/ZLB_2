FROM node:22-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3 AS frontend-build

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


FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS app-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple \
    HOME=/tmp

RUN sed -i \
        -e 's|http://deb.debian.org/debian-security|http://mirrors.cloud.tencent.com/debian-security|g' \
        -e 's|http://deb.debian.org/debian|http://mirrors.cloud.tencent.com/debian|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        age=1.2.1-1+b5 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        libreoffice-impress=4:25.2.3-2+deb13u6 \
        libreoffice-writer=4:25.2.3-2+deb13u6 \
        poppler-utils=25.03.0-5+deb13u4 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/constraints.txt /app/backend/constraints.txt
RUN python -m pip install -r /app/backend/requirements.txt

RUN groupadd --gid 10001 zlb \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin zlb

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
LABEL org.opencontainers.image.revision=${GIT_SHA}

COPY --chown=10001:10001 Dockerfile compose.prod.yml /app/
COPY --chown=10001:10001 backend /app/backend
COPY --chown=10001:10001 --from=frontend-build /frontend/dist /app/frontend/dist

# The production image has one generation route: the editorial vision loop.
# Do not ship the retired C+ runtime, its solver stack, or its support tools.
RUN rm -rf \
        /app/backend/tests \
        /app/backend/tools \
    && rm -f \
        /app/backend/app/agent_prompts.py \
        /app/backend/app/agents.py \
        /app/backend/app/chunking.py \
        /app/backend/app/claim_fidelity.py \
        /app/backend/app/cplus_pipeline.py \
        /app/backend/app/graph_builder.py \
        /app/backend/app/heuristics.py \
        /app/backend/app/pdf_layout_knowledge.py \
        /app/backend/app/pdf_page_knowledge.py \
        /app/backend/app/pdf_page_transcription.py \
        /app/backend/app/pipeline.py \
        /app/backend/app/review_service.py \
        /app/backend/app/semantic_dedupe.py \
        /app/backend/app/visual_analysis.py \
        /app/backend/app/mindmap_engine/normalize.py \
        /app/backend/app/mindmap_engine/router.py \
        /app/backend/app/mindmap_engine/service.py \
        /app/backend/app/mindmap_engine/topology.py \
        /app/backend/app/mindmap_engine/validate.py

RUN mkdir -p /app/.data/mindmap_engine /app/backend/uploads \
    && chown -R 10001:10001 /app/.data /app/backend/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

USER 10001:10001

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM app-base AS production

ENV MINDMAP_PIPELINE_MODE=editorial_ppt_vision
