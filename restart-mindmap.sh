#!/usr/bin/env bash
set -Eeuo pipefail

echo "Stopping old container if running..."
docker stop zlb-mindmap-single-shot 2>/dev/null || true
docker rm zlb-mindmap-single-shot 2>/dev/null || true

echo "Starting zlb-mindmap-single-shot with self-contained production image..."
docker run -d \
  --name zlb-mindmap-single-shot \
  --restart unless-stopped \
  -p 0.0.0.0:5173:8000 \
  -v zlb-mindmap-single-shot-data:/app/.data/mindmap_engine \
  -v zlb-mindmap-single-shot-uploads:/app/backend/uploads \
  -v /home/ZLB_2/runtime/secrets/qwen.prod.enc.env.age:/run/secrets/qwen.enc.env.age:ro \
  -v /home/ZLB_2/runtime/secrets/qwen-age-identity.prod.txt:/run/secrets/qwen-age-identity.txt:ro \
  -e MINDMAP_PROVIDER_RETRY_BASE_SECONDS=0.5 \
  -e MINDMAP_EDITORIAL_MODEL=qwen3.8-max-preview \
  -e MINDMAP_EDITORIAL_UPLOAD_CONCURRENCY=8 \
  -e MINDMAP_EDITORIAL_THINKING_BUDGET= \
  -e MINDMAP_EDITORIAL_MAX_REQUEST_MIB=96 \
  -e MINDMAP_EDITORIAL_RENDER_DPI=120 \
  -e MINDMAP_BLACKBOARD_PATH=/app/.data/mindmap_engine/blackboard.sqlite3 \
  -e MINDMAP_PROVIDER_TIMEOUT_SECONDS=90 \
  -e MINDMAP_PDF_PAGE_EXTRACTION_MODE=direct \
  -e QWEN_SECRETS_FILE=/run/secrets/qwen.enc.env.age \
  -e MINDMAP_EDITORIAL_PATCH_THINKING_BUDGET= \
  -e MINDMAP_EDITORIAL_JPEG_QUALITY=82 \
  -e MINDMAP_PROVIDER_MAX_ATTEMPTS=1 \
  -e MINDMAP_EDITORIAL_PATCH_MAX_OUTPUT_TOKENS= \
  -e MINDMAP_PDF_TRANSCRIPTION_MIN_CONFIDENCE=0.85 \
  -e MINDMAP_PDF_TRANSCRIPTION_DPI=192 \
  -e MINDMAP_EDITORIAL_REVISION_MAX_OUTPUT_TOKENS=14000 \
  -e MINDMAP_EDITORIAL_MAX_REVISIONS= \
  -e MINDMAP_MAX_IMAGE_PIXELS=40000000 \
  -e MINDMAP_EDITORIAL_FULL_REWRITE_FALLBACK= \
  -e MINDMAP_PDF_TRANSCRIPTION_CONCURRENCY=8 \
  -e GIT_SHA=22f70d9-dirty-diy-loop-20260802-r1 \
  -e MINDMAP_MAX_DOCUMENT_PAGES=150 \
  -e MINDMAP_WORKBENCH_OWNER_ID=token-086f79da94125cebb7e1 \
  -e QWEN_MODEL=qwen3.8-max \
  -e MINDMAP_MAX_CONCURRENT_JOBS=1 \
  -e MINDMAP_QWEN_PRODUCTION_PROFILE=standard \
  -e EXTERNAL_ENGINE_TOKEN=a2fd45258b99df53ddd42167a9ebfe03bacd522db652b100f19f7d11326b5344 \
  -e MINDMAP_ENV=production \
  -e MINDMAP_EDITORIAL_REVIEW_MAX_OUTPUT_TOKENS= \
  -e MINDMAP_EDITORIAL_PATCH_REVISIONS=true \
  -e MINDMAP_EDITORIAL_REVIEW_THINKING_BUDGET= \
  -e MINDMAP_EDITORIAL_RESPONSES_ENABLED=true \
  -e MINDMAP_PROVIDER_CONCURRENCY=8 \
  -e MINDMAP_EDITORIAL_MAX_DEPTH=6 \
  -e QWEN_TEMPERATURE=0.1 \
  -e ASSET_ACCESS_TOKEN= \
  -e MINDMAP_PIPELINE_MODE=editorial_ppt_vision \
  -e QWEN_VISION_MODEL=qwen3.8-max \
  -e MINDMAP_PDF_TRANSCRIPTION_MAX_ATTEMPTS=3 \
  -e MINDMAP_EDITORIAL_TIMEOUT_SECONDS=900 \
  -e MINDMAP_EDITORIAL_DRAFT_MAX_OUTPUT_TOKENS= \
  -e MINDMAP_EDITORIAL_IMAGE_MAX_EDGE= \
  -e MINDMAP_MAX_UPLOAD_BYTES=83886080 \
  -e MINDMAP_EDITORIAL_CONTENT_REVIEW_THINKING_BUDGET= \
  -e QWEN_AGE_IDENTITY_FILE=/run/secrets/qwen-age-identity.txt \
  -e MINDMAP_PROVIDER_RETRY_DELAY_CAP_SECONDS=30 \
  -e QWEN_BASE_URL=https://ws-r1lp2twiz8lj5t79.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 \
  -e MINDMAP_EXPORT_CONCURRENCY=1 \
  -e MINDMAP_PROVIDER_CIRCUIT_COOLDOWN_SECONDS=120 \
  -e MINDMAP_PDF_TRANSCRIPTION_MODE=vision_nodes_strict \
  -e MINDMAP_DATA_DIR=/app/.data/mindmap_engine \
  -e IMAGE_DIGEST=workspace-multidoc-context-20260823 \
  --health-cmd "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)\"" \
  --health-interval 30s \
  --health-timeout 5s \
  --health-retries 3 \
  --health-start-period 30s \
  zlb-mindmap-agent:workspace-multidoc-context-20260823 \
  python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

echo "Waiting for service to become healthy..."
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:5173/api/health | grep -q '"status":"ok"'; then
    echo "Service is UP and HEALTHY!"
    curl -s http://127.0.0.1:5173/api/health
    exit 0
  fi
  sleep 1
done

echo "Failed to start"
docker logs --tail 40 zlb-mindmap-single-shot
exit 1

