from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_workspace_csv() -> dict[str, str]:
    candidates = sorted(PROJECT_ROOT.glob("ZLB-apiKey-*.csv"))
    if not candidates:
        return {}

    values: dict[str, str] = {}
    with candidates[0].open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) >= 2:
                values[row[0].strip()] = row[1].strip()
    return values


@dataclass(frozen=True)
class Settings:
    api_key: str
    openai_base_url: str
    workspace_name: str
    workspace_id: str
    model: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    max_chunk_chars: int = 1800
    chunk_overlap_chars: int = 240
    extraction_concurrency: int = 4

    @property
    def key_configured(self) -> bool:
        return bool(self.api_key)


def load_settings() -> Settings:
    csv_values = _read_workspace_csv()
    return Settings(
        api_key=os.getenv("DASHSCOPE_API_KEY", csv_values.get("apiKey", "")),
        openai_base_url=os.getenv(
            "BAILIAN_OPENAI_BASE_URL",
            csv_values.get(
                "openAiCompatible",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        ).rstrip("/"),
        workspace_name=csv_values.get("workspaceName", "未命名工作空间"),
        workspace_id=csv_values.get("workspaceId", ""),
        model=os.getenv("BAILIAN_MODEL", "qwen3.7-plus"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        ).rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )


settings = load_settings()
